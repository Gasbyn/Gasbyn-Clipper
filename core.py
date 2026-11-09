"""Jádro Gasbyn Clipperu: stažení, přepis, AI hodnocení 0-100, výběr, střih, cache.

Používá ho GUI (app.py) i příkazová řádka (clipper.py). Průběh hlásí přes Reporter,
zrušení funguje přes threading.Event.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

from schema import load_settings, write_settings, default_settings

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

# Uživatelská data (nastavení, výstupy, cache, loadouty, YouTube token) jsou mimo instalaci,
# aby aktualizace instalátorem nic nepřepsala. Zdroje (ffmpeg) zůstávají v ROOT.
if getattr(sys, "frozen", False):
    DATA_ROOT = Path(os.environ.get("APPDATA") or Path.home()) / "GasbynClipper"
else:
    DATA_ROOT = ROOT
try:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_ROOT = ROOT

SETTINGS_FILE = DATA_ROOT / "settings.yaml"


# ---------------------------------------------------------------- hlášení a zrušení

class Cancelled(Exception):
    pass


class Reporter:
    def __init__(self, log: Callable[[str], None] = print,
                 progress: Optional[Callable[[float, str], None]] = None,
                 cancel: Optional[threading.Event] = None):
        self._log = log
        self._progress = progress or (lambda frac, text: None)
        self._cancel = cancel or threading.Event()

    def log(self, msg: str) -> None:
        self._log(f"{datetime.now():%H:%M:%S}  {msg}")

    def progress(self, frac: float, text: str = "") -> None:
        self._progress(max(0.0, min(1.0, frac)), text)

    def check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled("Zpracování bylo zrušeno.")


# ---------------------------------------------------------------- pomocné

def ffmpeg_bin() -> str:
    bundled = ROOT / "ffmpeg" / "ffmpeg.exe"
    return str(bundled) if bundled.exists() else "ffmpeg"


def ffmpeg_available() -> bool:
    return Path(ffmpeg_bin()).exists() or shutil.which("ffmpeg") is not None


def slugify(text: str, limit: int = 80) -> str:
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return text[:limit] or "video"


def has_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def work_root(cfg: dict) -> Path:
    return DATA_ROOT / cfg["cache"]["work_dir"]


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


# ---------------------------------------------------------------- profily a rychlost

FORMAT_WEIGHTS = {
    "short": {"hook": 25, "emotion": 20, "standalone": 15, "payoff": 15, "humor": 10, "pacing": 15},
    "long": {"hook": 15, "emotion": 15, "standalone": 25, "payoff": 30, "humor": 5, "pacing": 10},
}


def apply_profile(cfg: dict) -> dict:
    """Formát klipů nastaví délky a váhy hodnocení. Short-form max 60 s, long-form 1 až 60 min."""
    out = copy.deepcopy(cfg)
    c = out["clips"]
    if c["format"] == "long":
        c["min_seconds"] = 60
        c["max_seconds"] = int(c["long_minutes"]) * 60
        weights = FORMAT_WEIGHTS["long"]
    else:
        c["min_seconds"] = 20
        c["max_seconds"] = min(60, int(c["max_seconds"]))
        weights = FORMAT_WEIGHTS["short"]
    for key, val in weights.items():
        out["scoring"][f"weight_{key}"] = val
    return out


def apply_speed(cfg: dict) -> dict:
    """Priorita rychlosti: rychlé zkracuje přepis i odpověď AI, kvalitní jde na přesnost."""
    out = copy.deepcopy(cfg)
    mode = out["ai"]["speed_mode"]
    out["ai"]["_meta"] = True  # generovat popis a hashtagy
    if mode == "rychlé":
        if out["transcription"]["model"] in ("large-v3", "medium", "large-v3-turbo"):
            out["transcription"]["model"] = "small"
        out["transcription"]["beam_size"] = 1
        out["ai"]["chunk_minutes"] = max(int(out["ai"]["chunk_minutes"]), 45)
        out["ai"]["ollama_num_ctx"] = min(int(out["ai"]["ollama_num_ctx"]), 8192)
        out["ai"]["_meta"] = False
    elif mode == "kvalitní":
        out["transcription"]["beam_size"] = max(int(out["transcription"]["beam_size"]), 5)
        out["ai"]["chunk_minutes"] = min(int(out["ai"]["chunk_minutes"]), 20)
    return out


# ---------------------------------------------------------------- učení z hodnocení

def learning_path(cfg: dict) -> Path:
    return work_root(cfg) / "learning.json"


def load_learning(cfg: dict) -> dict:
    path = learning_path(cfg)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"good": [], "bad": []}


def record_feedback(cfg: dict, clip: dict, good: bool) -> None:
    """Uloží hodnocení klipu (👍/👎), aby se z něj AI příště učila."""
    data = load_learning(cfg)
    entry = {
        "title": clip.get("title", ""),
        "reason": clip.get("reason", ""),
        "score": round(float(clip.get("score", 0)), 1),
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    key = "good" if good else "bad"
    data[key] = (data.get(key, []) + [entry])[-100:]
    path = learning_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def learning_block(cfg: dict) -> str:
    lc = cfg.get("learning", {})
    if not lc.get("enabled") or int(lc.get("examples", 0)) <= 0:
        return ""
    data = load_learning(cfg)
    n = int(lc["examples"])
    good = data.get("good", [])[-n:]
    bad = data.get("bad", [])[-n:]
    if not good and not bad:
        return ""
    lines = ["The creator's past feedback (learn from it):"]
    if good:
        lines.append("Clips the creator LIKED (aim for this style):")
        lines += [f"- {g['title']}: {g['reason']}" for g in good]
    if bad:
        lines.append("Clips the creator DISLIKED (avoid this style):")
        lines += [f"- {b['title']}: {b['reason']}" for b in bad]
    return "\n".join(lines)


# ---------------------------------------------------------------- cache

def cache_report(cfg: dict) -> dict:
    root = work_root(cfg)
    downloads = root / "downloads"
    jobs = root / "jobs"
    return {
        "downloads": _size(downloads),
        "transcripts": sum(_size(j / "transcript.json") for j in jobs.iterdir()) if jobs.exists() else 0,
        "selections": sum(_size(j / "candidates.json") + _size(j / "clips.json")
                          for j in jobs.iterdir()) if jobs.exists() else 0,
        "learning": _size(learning_path(cfg)),
        "total": _size(root),
    }


def clean_cache(cfg: dict, what: str, rep: Reporter) -> int:
    """what: downloads | transcripts | selections | all. Vrací uvolněné bajty."""
    root = work_root(cfg)
    freed = 0

    def remove(path: Path) -> None:
        nonlocal freed
        if not path.exists():
            return
        freed += _size(path)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

    if what in ("downloads", "all"):
        remove(root / "downloads")
    jobs = root / "jobs"
    if jobs.exists():
        for job in jobs.iterdir():
            if what in ("transcripts", "all"):
                remove(job / "transcript.json")
            if what in ("selections", "all"):
                remove(job / "candidates.json")
                remove(job / "clips.json")
            if what == "all":
                remove(job)
    rep.log(f"Cache vyčištěna ({what}), uvolněno {freed / 1024 ** 2:.1f} MB.")
    return freed


def auto_clean(cfg: dict, rep: Reporter) -> None:
    """Smaže staré položky podle nastavení a hlídá maximální velikost cache."""
    c = cfg["cache"]
    root = work_root(cfg)
    if not root.exists():
        return
    now = time.time()
    days = c["auto_clean_days"]
    if days > 0:
        cutoff = now - days * 86400
        for f in (root / "downloads").glob("*") if (root / "downloads").exists() else []:
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                rep.log(f"Smazáno staré stažení: {f.name}")
        jobs = root / "jobs"
        if jobs.exists():
            for job in jobs.iterdir():
                if job.is_dir() and job.stat().st_mtime < cutoff:
                    shutil.rmtree(job, ignore_errors=True)
                    rep.log(f"Smazána stará pracovní složka: {job.name}")

    limit = c["max_cache_gb"] * 1024 ** 3
    if _size(root) > limit:
        rep.log("Cache je větší než povolený limit, mažu nejstarší stažená videa.")
        downloads = sorted((root / "downloads").glob("*"), key=lambda p: p.stat().st_mtime) \
            if (root / "downloads").exists() else []
        for f in downloads:
            if _size(root) <= limit:
                break
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------- 1. zdroj

def get_source(source: str, cfg: dict, rep: Reporter) -> tuple[Path, str, bool]:
    """Vrátí (cesta k videu, id videa, bylo_staženo)."""
    local = Path(source.strip().strip('"'))
    if local.exists():
        return local.resolve(), slugify(local.stem), False

    import yt_dlp

    dl_dir = work_root(cfg) / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    d = cfg["download"]
    height = int(d["max_height"])

    base_opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                 "retries": int(d["retries"])}
    if d["cookies_file"]:
        base_opts["cookiefile"] = d["cookies_file"]

    candidates = [source] + ALT_URLS.get(source, [])
    info, last_exc = None, None
    for candidate in candidates:
        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(candidate, download=False)
            source = candidate
            break
        except yt_dlp.utils.DownloadError as exc:
            last_exc = exc
            if candidate == candidates[-1]:
                raise
            rep.log(f"Kick nevrátil {candidate} ({str(exc)[:80]}), zkouším další možné ID ...")
    if info is None:
        raise last_exc
    raw_id = str(info.get("id", "video"))
    path = dl_dir / f"{raw_id}.mp4"

    if path.exists() and path.stat().st_size > 0:
        rep.log("Video už je stažené, používám ho.")
        return path, slugify(raw_id), True

    rep.log(f"Stahuji video ({raw_id}) ...")

    def hook(data: dict) -> None:
        rep.check()
        if data.get("status") != "downloading":
            return
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
        done = data.get("downloaded_bytes", 0)
        if total:
            frac = min(1.0, done / total)
            rep.progress(0.25 * frac,
                         f"Stahuji video {done / 1024 ** 3:.2f} / {total / 1024 ** 3:.2f} GB "
                         f"({frac * 100:.0f} %)")

    opts = dict(base_opts)
    opts.update({
        "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(dl_dir / "%(id)s.%(ext)s"),
        "progress_hooks": [hook],
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([source])
    if not path.exists():
        raise RuntimeError(f"Stažení se nepovedlo, soubor {path.name} nevznikl.")
    return path, slugify(raw_id), True


# ---------------------------------------------------------------- 2. přepis

def transcribe(video: Path, out_json: Path, cfg: dict, rep: Reporter) -> list[dict]:
    if out_json.exists():
        rep.log("Přepis je v cache, přeskakuji přepis.")
        return json.loads(out_json.read_text(encoding="utf-8"))

    from faster_whisper import WhisperModel

    t = cfg["transcription"]
    device = t["device"]
    if device == "auto":
        device = "cuda" if has_cuda() else "cpu"
    compute = t["compute_type"]
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"

    language = None if t["language"].strip().lower() in ("", "auto") else t["language"].strip()

    def run(dev: str, comp: str) -> list[dict]:
        rep.log(f"Přepisuji model {t['model']} na {dev} ({comp}) ...")
        model = WhisperModel(t["model"], device=dev, compute_type=comp)
        segments, info = model.transcribe(
            str(video),
            language=language,
            vad_filter=bool(t["vad_filter"]),
            beam_size=int(t["beam_size"]),
            initial_prompt=t["initial_prompt"] or None,
        )
        total = float(info.duration or 1.0)
        out: list[dict] = []
        for seg in segments:
            rep.check()
            out.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                        "text": seg.text.strip()})
            local = min(1.0, seg.end / total)
            rep.progress(0.25 + 0.30 * local, f"Přepisuji řeč {local * 100:.0f} %")
        return out

    try:
        result = run(device, compute)
    except RuntimeError as exc:
        # CUDA knihovny (cuBLAS/cuDNN) chybí nebo nejdou načíst - spadneme na procesor.
        msg = str(exc).lower()
        if device != "cuda" or not any(k in msg for k in ("cublas", "cudnn", "cuda", ".dll")):
            raise
        rep.log("GPU nejde použít (chybí CUDA knihovny, např. cublas64_12.dll). "
                "Přepisuji na procesoru - bude to pomalejší. Pro GPU nainstaluj CUDA 12 runtime "
                "nebo v Nastavení přepni zařízení na cpu.")
        result = run("cpu", "int8")

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


# ---------------------------------------------------------------- 3. AI hodnocení

PROMPT = """You are an expert short-form video editor (YouTube Shorts, TikTok, Instagram Reels). You find moments in a long livestream that can go viral.
{context}
For each clip candidate, score honestly from 0 to 100 on each criterion:
- hook: does the first 3 seconds grab attention (surprise, question, bold claim, conflict)?
- emotion: strength of emotion (laughter, shock, anger, excitement, tension).
- standalone: understandable without knowing the rest of the stream?
- payoff: does it end on a punchline, resolution or strong moment?
- humor: how funny is it?

Rules:
- Start and end on natural sentence boundaries, using the timestamps given.
- Clip length between {min} and {max} seconds.
- Skip small talk, dead air, sponsor reads, repetition and filler.
- Return at most {n} clips from this part, best first. Return an empty list if nothing is good. Do not invent moments that are not in the transcript.
- title: catchy, at most 60 characters, in the same language as the transcript.
{meta}
- reason: one short sentence on why this clip works.
{extra}
{learn}
Respond ONLY with JSON in this exact shape:
{{"clips": [{{"start": 0.0, "end": 0.0, "hook": 0, "emotion": 0, "standalone": 0, "payoff": 0, "humor": 0, "title": "", "description": "", "hashtags": [], "reason": ""}}]}}"""

META_ON = ("- description: one or two sentences.\n"
           "- hashtags: 3 to 5 hashtags without spaces.")
META_OFF = ("- description: leave empty.\n"
            "- hashtags: leave empty list.")


def build_prompt(cfg: dict, n: int) -> str:
    c, ai = cfg["clips"], cfg["ai"]
    context = f"Channel context: {ai['channel_context']}" if ai["channel_context"].strip() else ""
    extra = f"Extra instructions from the creator: {ai['extra_instructions']}" if ai["extra_instructions"].strip() else ""
    meta = META_ON if ai.get("_meta", True) else META_OFF
    return (PROMPT.replace("{context}", context)
            .replace("{min}", str(c["min_seconds"]))
            .replace("{max}", str(c["max_seconds"]))
            .replace("{n}", str(n))
            .replace("{meta}", meta)
            .replace("{extra}", extra)
            .replace("{learn}", learning_block(cfg)))


def _call_llm(cfg: dict, system: str, user: str) -> str:
    ai = cfg["ai"]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    timeout = int(ai["timeout_s"])

    if ai["provider"] == "ollama":
        r = requests.post(
            f"{ai['ollama_url'].rstrip('/')}/api/chat",
            json={
                "model": ai["ollama_model"],
                "stream": False,
                "format": "json",
                "options": {"temperature": float(ai["temperature"]),
                            "num_ctx": int(ai["ollama_num_ctx"])},
                "messages": messages,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    key = _openrouter_key(cfg)
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": ai["openrouter_model"], "temperature": float(ai["temperature"]),
              "messages": messages},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _openrouter_key(cfg: dict) -> str:
    env = cfg["ai"]["openrouter_api_key_env"]
    key = os.environ.get(env, "")
    if not key:
        raise RuntimeError(f"Chybí klíč OpenRouter. Nastav proměnnou prostředí {env}.")
    return key


def ask_llm(cfg: dict, system: str, user: str, rep: Reporter) -> str:
    last: Exception | None = None
    for attempt in range(int(cfg["ai"]["max_retries"]) + 1):
        rep.check()
        try:
            return _call_llm(cfg, system, user)
        except (requests.RequestException, KeyError, ValueError, RuntimeError) as exc:
            last = exc
            rep.log(f"AI nereagovala ({exc}), zkouším znovu ...")
            time.sleep(3)
    raise RuntimeError(f"AI je nedostupná: {last}")


def parse_clips(text: str) -> list[dict]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    clips = data.get("clips", [])
    return clips if isinstance(clips, list) else []


def build_chunks(segments: list[dict], chunk_seconds: float) -> list[list[dict]]:
    chunks, current, chunk_start = [], [], 0.0
    for seg in segments:
        if current and seg["start"] - chunk_start >= chunk_seconds:
            chunks.append(current)
            current, chunk_start = [], seg["start"]
        current.append(seg)
    if current:
        chunks.append(current)
    return chunks


def pacing_score(segments: list[dict], start: float, end: float) -> float:
    """Heuristika: tempo řeči v klipu (ideál 2 až 3,2 slova za sekundu)."""
    words = 0
    for s in segments:
        if s["end"] <= start or s["start"] >= end:
            continue
        words += len(s["text"].split())
    length = max(0.1, end - start)
    wps = words / length
    if wps < 2.0:
        return clamp(100 - (2.0 - wps) * 50)
    if wps > 3.2:
        return clamp(100 - (wps - 3.2) * 40)
    return 100.0


def score_with_ai(segments: list[dict], cfg: dict, rep: Reporter) -> list[dict]:
    chunk_min = int(cfg["ai"]["chunk_minutes"])
    chunks = build_chunks(segments, chunk_min * 60)
    per_chunk = max(1, round(float(cfg["clips"]["count_per_hour"]) * chunk_min / 60) + 1)
    system = build_prompt(cfg, per_chunk)
    candidates: list[dict] = []

    for i, chunk in enumerate(chunks, 1):
        rep.check()
        lo, hi = chunk[0]["start"], chunk[-1]["end"]
        rep.log(f"AI hodnotí část {i}/{len(chunks)} ({lo / 60:.0f}-{hi / 60:.0f} min) ...")
        rep.progress(0.55 + 0.20 * (i - 1) / len(chunks),
                     f"AI hodnotí část {i}/{len(chunks)}")
        text = "Transcript part (times in seconds):\n" + "\n".join(
            f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in chunk)
        raw = ask_llm(cfg, system, text, rep)

        for clip in parse_clips(raw):
            try:
                s, e = float(clip["start"]), float(clip["end"])
            except (KeyError, TypeError, ValueError):
                continue
            candidates.append({
                "start": round(s, 2),
                "end": round(e, 2),
                "hook": clamp(float(clip.get("hook", 0) or 0)),
                "emotion": clamp(float(clip.get("emotion", 0) or 0)),
                "standalone": clamp(float(clip.get("standalone", 0) or 0)),
                "payoff": clamp(float(clip.get("payoff", 0) or 0)),
                "humor": clamp(float(clip.get("humor", 0) or 0)),
                "title": str(clip.get("title", "")).strip() or "klip",
                "description": str(clip.get("description", "")).strip(),
                "hashtags": [str(h) for h in clip.get("hashtags", []) if h][:8]
                if isinstance(clip.get("hashtags"), list) else [],
                "reason": str(clip.get("reason", "")).strip(),
                "pacing": round(pacing_score(segments, s, e), 1),
            })
    return candidates


def final_score(cand: dict, cfg: dict) -> float:
    """Vážený průměr 0-100 podle vah v nastavení."""
    sc = cfg["scoring"]
    weights = {
        "hook": sc["weight_hook"], "emotion": sc["weight_emotion"],
        "standalone": sc["weight_standalone"], "payoff": sc["weight_payoff"],
        "humor": sc["weight_humor"], "pacing": sc["weight_pacing"],
    }
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    weighted = sum(cand[k] * w for k, w in weights.items())
    return round(clamp(weighted / total), 1)


def select_clips(candidates: list[dict], cfg: dict, duration: float) -> list[dict]:
    """Přepočítá skóre, zahodí podle délky a prahu, vybere nejlepší bez velkého překryvu."""
    c = cfg["clips"]
    min_len, max_len = c["min_seconds"], c["max_seconds"]
    max_overlap = c["max_overlap_percent"] / 100.0
    target = max(1, round(float(c["count_per_hour"]) * duration / 3600))

    pool = []
    for cand in candidates:
        length = cand["end"] - cand["start"]
        if length < min_len or length > max_len or cand["start"] < 0 or cand["end"] > duration + 1:
            continue
        item = dict(cand)
        item["score"] = final_score(cand, cfg)
        if item["score"] >= c["min_score"]:
            pool.append(item)
    pool.sort(key=lambda x: x["score"], reverse=True)

    def overlap(a: dict, b: dict) -> float:
        inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
        if inter <= 0:
            return 0.0
        shorter = min(a["end"] - a["start"], b["end"] - b["start"])
        return inter / shorter

    chosen: list[dict] = []
    for cand in pool:
        if all(overlap(cand, other) <= max_overlap for other in chosen):
            chosen.append(cand)
        if len(chosen) >= target:
            break
    return chosen


# ---------------------------------------------------------------- 4. střih, titulky, efekty

def caption_items(segments: list[dict], start: float, end: float, words: int,
                  uppercase: bool) -> list[tuple[float, float, str]]:
    items = []
    for seg in segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        tokens = seg["text"].split()
        if not tokens:
            continue
        span = (seg["end"] - seg["start"]) or 0.1
        n = len(tokens)
        cursor = 0
        for i in range(0, n, words):
            group = tokens[i:i + words]
            g_start = seg["start"] + span * cursor / n
            cursor += len(group)
            g_end = seg["start"] + span * cursor / n
            if g_end <= start or g_start >= end:
                continue
            text = " ".join(group)
            items.append((max(g_start, start) - start, min(g_end, end) - start,
                          text.upper() if uppercase else text))
    return items


def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".", ",")


def write_srt(path: Path, items: list[tuple[float, float, str]]) -> None:
    lines = []
    for idx, (a, b, text) in enumerate(items, 1):
        lines += [str(idx), f"{srt_time(a)} --> {srt_time(b)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    """Načte titulky z .srt (čas od začátku klipu)."""
    def secs(h, m, s, ms) -> float:
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    items = []
    if not path.exists():
        return items
    text = path.read_text(encoding="utf-8")
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", lines[1])
        if not m:
            continue
        g = m.groups()
        items.append((secs(*g[0:4]), secs(*g[4:8]), " ".join(lines[2:])))
    return items


POSITION_ALIGN = {"bottom": 2, "middle": 5, "top": 8}
EFFECT_KINDS = ["none", "fade", "unblur", "shake"]
LOADOUT_MAX_VIEWS = 5


def default_effects() -> dict:
    return {"intro": "none", "intro_seconds": 0.6, "image": "", "image_x": 0.5,
            "image_y": 0.4, "image_scale": 0.3, "image_start": 0.0, "image_end": 0.0}


def _even(n: float) -> int:
    n = int(round(n))
    return max(2, n - n % 2)


# ---------------------------------------------------------------- údaje o VODu (ffprobe)

def ffprobe_bin() -> str:
    bundled = ROOT / "ffmpeg" / "ffprobe.exe"
    return str(bundled) if bundled.exists() else "ffprobe"


def probe_video(path: Path) -> dict:
    """Délka, rozlišení, snímky za sekundu a bitrate videa."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", check=True).stdout
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fmt = data.get("format", {})
    try:
        n, d = (v.get("avg_frame_rate") or "30/1").split("/")
        fps = float(n) / float(d) if float(d) else 30.0
    except ValueError:
        fps = 30.0
    bitrate = int(fmt.get("bit_rate") or v.get("bit_rate") or 0) // 1000
    return {"duration": float(fmt.get("duration") or 0), "width": int(v.get("width") or 1920),
            "height": int(v.get("height") or 1080), "fps": round(fps, 2), "kbps": bitrate}


def extract_frame(video: Path, out_png: Path, at: float = 1.0) -> Path:
    """Uloží jeden snímek videa (pro loadout)."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.2f}",
           "-i", str(video), "-frames:v", "1", str(out_png)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_png


def _frame_at(video: Path, t: float, out: Path, width: Optional[int] = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
           "-i", str(video), "-frames:v", "1"]
    if width:
        cmd += ["-vf", f"scale={width}:-2"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _heuristic_frame_score(png: Path) -> float:
    """Bez AI: přednost mají snímky s kontrastem a rozumným jasem (ne černá, ne bílá obrazovka)."""
    from PIL import Image, ImageStat
    with Image.open(png) as im:
        stat = ImageStat.Stat(im.convert("L"))
    mean, sd = stat.mean[0], stat.stddev[0]
    score = min(sd, 70.0) / 70.0 * 100.0
    if mean < 40 or mean > 215:
        score *= 0.3
    return score


FRAME_PROMPT = (
    "Toto je snímek z herního livestreamu. Posuzuješ, jak vhodný je jako úvodní snímek "
    "vertikálního klipu 9:16. Nejlepší je záběr na webkameru streamera (obličej), buď samotný, "
    "nebo spolu s hrou. Nevhodné jsou černá obrazovka, menu, nastavení, přechod, prázdná scéna "
    "nebo jen text. Vrať pouze JSON: "
    '{"score": číslo 0-100, "webcam": true/false, "game": true/false}.'
)


def _vision_frame_score(png: Path, cfg: dict, timeout: int = 120) -> dict:
    """Ohodnotí snímek přes Ollamu (multimodální model, např. gemma3). Vyhodí výjimku, když to nejde."""
    ai = cfg["ai"]
    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    r = requests.post(
        f"{ai['ollama_url'].rstrip('/')}/api/chat",
        json={"model": ai["ollama_model"], "stream": False, "format": "json",
              "options": {"temperature": 0.1},
              "messages": [{"role": "user", "content": FRAME_PROMPT, "images": [b64]}]},
        timeout=timeout,
    )
    r.raise_for_status()
    data = json.loads(r.json()["message"]["content"])
    return {"score": float(data.get("score", 0)),
            "webcam": bool(data.get("webcam")), "game": bool(data.get("game"))}


def pick_best_frame(video: Path, duration: float, out_png: Path, cfg: dict,
                    log: Callable[[str], None] = print, candidates: int = 12) -> Path:
    """Najde vhodný úvodní snímek: prohledá VOD a vybere záběr s webkamerou (samotnou nebo s hrou).

    Když Ollama neběží nebo model neumí obrázky, použije jednoduché hodnocení kontrastu.
    Vybraný snímek se uloží v plném rozlišení na out_png.
    """
    if duration <= 0:
        return extract_frame(video, out_png, 1.0)
    tmp = out_png.parent / "candidates" / out_png.stem
    tmp.mkdir(parents=True, exist_ok=True)
    times = [duration * (0.05 + 0.9 * i / max(1, candidates - 1)) for i in range(candidates)]
    log(f"Hledám vhodný snímek ({candidates} kandidátů z celého VODu)…")

    scored = []
    for i, t in enumerate(times):
        png = _frame_at(video, t, tmp / f"c{i:02d}.png", width=480)
        try:
            h = _heuristic_frame_score(png)
        except Exception:  # noqa: BLE001
            h = 0.0
        scored.append({"t": t, "png": png, "heur": h, "vision": None})

    use_vision = True
    for c in scored:
        if not use_vision:
            break
        try:
            c["vision"] = _vision_frame_score(c["png"], cfg)
        except Exception as exc:  # noqa: BLE001
            log(f"AI neohodnotila snímky ({exc}); použit jednodušší výběr. "
                "Zkontroluj, že v Ollamě běží multimodální model (např. gemma3).")
            use_vision = False

    def key(c: dict) -> float:
        v = c["vision"]
        if v is None:
            return c["heur"]
        s = v["score"] if v["webcam"] else v["score"] * 0.4
        return s + c["heur"] * 0.05

    best = max(scored, key=key)
    v = best["vision"]
    detail = (f"skóre {v['score']:.0f}, webkamera: {'ano' if v['webcam'] else 'ne'}, "
              f"hra: {'ano' if v['game'] else 'ne'}") if v else "jednoduchý výběr"
    m, s = divmod(int(best["t"]), 60)
    h, m = divmod(m, 60)
    stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    log(f"Vybrán snímek v {stamp} ({detail}).")
    for c in scored:
        c["png"].unlink(missing_ok=True)
    return _frame_at(video, best["t"], out_png)


def auto_output(cfg: dict, probe: dict) -> dict:
    """Výstup podle VODu a formátu: rozlišení, snímky, CRF podle bitrate zdroje."""
    o = cfg["output"]
    short = cfg["clips"]["format"] == "short"
    sw, sh = probe["width"], probe["height"]
    if short:
        w, h = (1080, 1920) if sh >= 1080 else (720, 1280)
    else:
        w = min(sw, 1920)
        w = _even(w)
        h = _even(w * sh / sw)
    fps = 60 if probe.get("fps", 30) >= 50 else 30
    kbps = probe.get("kbps") or 0
    spec = {"width": w, "height": h, "fps": fps,
            "crf": 21 if kbps >= 5000 else 23, "preset": "veryfast", "audio_bitrate": "160k"}
    o.update(spec)
    return spec


# ---------------------------------------------------------------- loadouty

def default_loadout(fmt: str, src_w: int, src_h: int, effects: Optional[dict] = None) -> dict:
    """Výchozí rozložení: short-form = střed 9:16 z rámce, long-form = celý rámec."""
    fx = {**default_effects(), **(effects or {})}
    if fmt == "short":
        cw = min(1.0, (9 / 16) * src_h / src_w)
        crop = [round(0.5 - cw / 2, 4), 0.0, round(cw, 4), 1.0]
    else:
        crop = [0.0, 0.0, 1.0, 1.0]
    views = [{"crop": crop, "place": [0.0, 0.0, 1.0, 1.0],
              "anim": fx["intro"] if fx["intro"] in EFFECT_KINDS else "none",
              "anim_seconds": float(fx["intro_seconds"])}]
    photos = []
    if fx.get("image"):
        s = float(fx["image_scale"])
        photos.append({"path": fx["image"],
                       "place": [round(float(fx["image_x"]) - s / 2, 4),
                                 round(float(fx["image_y"]) - s / 2, 4), s, s],
                       "anim": "none", "anim_seconds": 0.6,
                       "start": float(fx["image_start"]), "end": float(fx["image_end"])})
    return {"name": "výchozí", "background": "#000000", "views": views, "photos": photos}


def clean_loadout(lo: dict) -> dict:
    """Ořízne seznamy na povolené délky a doplní chybějící pole."""
    out = {"name": str(lo.get("name", "loadout")), "background": lo.get("background", "#000000"),
           "views": [], "photos": []}
    for v in lo.get("views", [])[:LOADOUT_MAX_VIEWS]:
        out["views"].append({"crop": [float(x) for x in v["crop"]],
                             "place": [float(x) for x in v["place"]],
                             "anim": v.get("anim", "none") if v.get("anim") in EFFECT_KINDS else "none",
                             "anim_seconds": float(v.get("anim_seconds", 0.6))})
    for p in lo.get("photos", []):
        out["photos"].append({"path": str(p["path"]), "place": [float(x) for x in p["place"]],
                              "anim": p.get("anim", "none") if p.get("anim") in EFFECT_KINDS else "none",
                              "anim_seconds": float(p.get("anim_seconds", 0.6)),
                              "start": float(p.get("start", 0)), "end": float(p.get("end", 0))})
    return out


def loadout_dir(cfg: dict) -> Path:
    d = work_root(cfg) / "loadouts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_loadouts(cfg: dict) -> list[str]:
    return sorted(p.stem for p in loadout_dir(cfg).glob("*.json") if p.stem != "_last")


def load_loadout(cfg: dict, name: str) -> Optional[dict]:
    path = loadout_dir(cfg) / f"{slugify(name)}.json"
    if not path.exists():
        return None
    return clean_loadout(json.loads(path.read_text(encoding="utf-8")))


def save_loadout(cfg: dict, lo: dict) -> str:
    lo = clean_loadout(lo)
    name = slugify(lo["name"]) or "loadout"
    (loadout_dir(cfg) / f"{name}.json").write_text(
        json.dumps(lo, ensure_ascii=False, indent=1), encoding="utf-8")
    return name


def last_loadout(cfg: dict) -> Optional[dict]:
    path = loadout_dir(cfg) / "_last.json"
    if path.exists():
        try:
            return clean_loadout(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
    return None


def remember_loadout(cfg: dict, lo: dict) -> None:
    """Poslední použitý loadout se načte i u dalšího VODu."""
    (loadout_dir(cfg) / "_last.json").write_text(
        json.dumps(clean_loadout(lo), ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- filtrový graf

def _anim_chain(src: str, out: str, kind: str, d: float, w: int, h: int, tag: str) -> str:
    """Animace na začátku jednoho záběru nebo fotky. Bez [vstup] na začátku."""
    d = max(0.1, float(d))
    if kind == "fade":
        return f"[{src}]fade=t=in:st=0:d={d}[{out}]"
    if kind == "unblur":
        a, b, c = f"{tag}a", f"{tag}b", f"{tag}c"
        return (f"[{src}]split[{a}][{b}];"
                f"[{b}]boxblur=20:2,format=rgba,fade=t=out:st=0:d={d}:alpha=1[{c}];"
                f"[{a}][{c}]overlay[{out}]")
    if kind == "shake":
        amp = max(2, int(w * 0.02))
        return (f"[{src}]crop={w - 2 * amp}:{h - 2 * amp}"
                f":x='{amp}+{amp}*sin(t*45)*max(0,1-t/{d})'"
                f":y='{amp}+{amp}*cos(t*38)*max(0,1-t/{d})',scale={w}:{h}[{out}]")
    return f"[{src}]null[{out}]"


def loadout_graph(lo: dict, W: int, H: int, src_w: int, src_h: int, duration: float,
                  photos: list[dict], subs: Optional[tuple[str, str]]) -> str:
    """Složí filter_complex: záběry (vstup 0), fotky (vstupy 1..n), titulky, výstup [vout]."""
    parts = []
    bg = str(lo.get("background", "#000000")).lstrip("#")
    parts.append(f"color=c=0x{bg}:s={W}x{H}:d={duration:.3f}[base0]")
    cur = "base0"
    for i, v in enumerate(lo["views"][:LOADOUT_MAX_VIEWS]):
        cx, cy, cw, ch = v["crop"]
        cw_px = min(src_w, _even(cw * src_w))
        ch_px = min(src_h, _even(ch * src_h))
        x_px = min(src_w - cw_px, max(0, int(cx * src_w)))
        y_px = min(src_h - ch_px, max(0, int(cy * src_h)))
        bx, by, bw, bh = v["place"]
        pw, ph = _even(bw * W), _even(bh * H)
        px, py = int(round(bx * W)), int(round(by * H))
        parts.append(f"[0:v]crop={cw_px}:{ch_px}:{x_px}:{y_px},"
                     f"scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},"
                     f"setsar=1,format=yuva420p[v{i}raw]")
        parts.append(_anim_chain(f"v{i}raw", f"v{i}", v.get("anim", "none"),
                                 v.get("anim_seconds", 0.6), pw, ph, f"tv{i}"))
        nxt = f"o{i}"
        parts.append(f"[{cur}][v{i}]overlay={px}:{py}[{nxt}]")
        cur = nxt
    for j, p in enumerate(photos):
        bx, by, bw, bh = p["place"]
        pw, ph = _even(bw * W), _even(bh * H)
        px, py = int(round(bx * W)), int(round(by * H))
        start = float(p.get("start", 0))
        end = float(p.get("end", 0)) or duration
        parts.append(f"[{j + 1}:v]scale={pw}:{ph}:force_original_aspect_ratio=decrease,"
                     f"format=yuva420p,setpts=PTS-STARTPTS[p{j}raw]")
        parts.append(_anim_chain(f"p{j}raw", f"p{j}", p.get("anim", "none"),
                                 p.get("anim_seconds", 0.6), pw, ph, f"tp{j}"))
        nxt = f"q{j}"
        parts.append(f"[{cur}][p{j}]overlay=x='{px}+({pw}-w)/2':y='{py}+({ph}-h)/2'"
                     f":enable='between(t,{start:.2f},{end:.2f})'[{nxt}]")
        cur = nxt
    if subs:
        parts.append(f"[{cur}]subtitles={subs[0]}:force_style='{subs[1]}',format=yuv420p[vout]")
    else:
        parts.append(f"[{cur}]format=yuv420p[vout]")
    return ";".join(parts)


def caption_style(cap: dict) -> str:
    return ",".join([
        f"FontName={cap['font']}",
        f"FontSize={int(cap['font_size'])}",
        f"PrimaryColour={cap['text_color']}",
        f"OutlineColour={cap['outline_color']}",
        f"Outline={int(cap['outline_width'])}",
        f"Shadow={int(cap['shadow'])}",
        f"Bold={1 if cap['bold'] else 0}",
        f"Alignment={POSITION_ALIGN.get(cap['position'], 2)}",
        f"MarginV={int(cap['margin_v'])}",
    ])


def render_clip(video: Path, segments: list[dict], clip: dict, out_dir: Path,
                cfg: dict, index: int, rep: Reporter,
                items_override: Optional[list] = None,
                name_override: Optional[str] = None) -> Path:
    """Vystřihne klip podle loadoutu (short-form) nebo celého rámce (long-form).

    clip['output_spec'] a clip['src_size'] drží parametry z doby běhu, takže přerenderování
    v editoru dá stejný výsledek i bez znovu zjištěných údajů o VODu.
    """
    o, cap = cfg["output"], cfg["captions"]
    spec = clip.get("output_spec") or {"width": int(o["width"]), "height": int(o["height"]),
                                       "fps": int(o["fps"]), "crf": int(o["crf"]),
                                       "preset": o["preset"], "audio_bitrate": o["audio_bitrate"]}
    W, H = int(spec["width"]), int(spec["height"])

    if name_override:
        name = name_override
    else:
        try:
            name = o["file_pattern"].format(index=index, score=round(clip["score"]),
                                            title=slugify(clip["title"], 40))
        except (KeyError, IndexError, ValueError):
            name = f"klip_{index:02d}"
        name = slugify(name, 120)

    duration = float(clip["end"]) - float(clip["start"])
    src_w, src_h = clip.get("src_size") or [1920, 1080]
    fmt = clip.get("format") or cfg["clips"]["format"]
    if fmt == "short" and clip.get("loadout"):
        lo = clean_loadout(clip["loadout"])
    else:
        lo = default_loadout(fmt, src_w, src_h, clip.get("effects"))
    photos = [p for p in lo["photos"] if Path(p["path"]).exists()]
    for p in lo["photos"]:
        if p not in photos:
            rep.log(f"Fotka {Path(p['path']).name} nebyla nalezena, přeskakuji ji.")

    subs = None
    if cap["enabled"]:
        if items_override is not None:
            items = items_override
        else:
            items = caption_items(segments, clip["start"], clip["end"],
                                  int(cap["words_per_caption"]), bool(cap["uppercase"]))
        srt_name = f"{name}.srt"
        write_srt(out_dir / srt_name, items)
        subs = (srt_name, caption_style(cap))

    graph = loadout_graph(lo, W, H, int(src_w), int(src_h), duration, photos, subs)

    out_file = out_dir / f"{name}.mp4"
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{clip['start']:.3f}", "-i", str(video)]
    for p in photos:
        cmd += ["-loop", "1", "-i", str(p["path"])]
    cmd += ["-t", f"{duration:.3f}", "-filter_complex", graph,
            "-map", "[vout]", "-map", "0:a?",
            "-r", str(int(spec["fps"])),
            "-c:v", "libx264", "-preset", str(spec["preset"]), "-crf", str(int(spec["crf"])),
            "-c:a", "aac", "-b:a", str(spec["audio_bitrate"]), "-movflags", "+faststart"]
    fade_views = [v for v in lo["views"] if v.get("anim") == "fade"]
    if fade_views:
        d = max(0.1, float(fade_views[0].get("anim_seconds", 0.6)))
        cmd += ["-af", f"afade=t=in:st=0:d={d}"]
    cmd.append(out_file.name)

    rep.check()
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg selhal u klipu {index}: {proc.stderr.strip()[-400:]}")

    if o["write_txt"]:
        tags = " ".join(clip.get("hashtags", []))
        (out_dir / f"{name}.txt").write_text(
            f"{clip['title']}\n\n{clip.get('description', '')}\n\n{tags}\n\n"
            f"Hodnocení: {clip.get('score', 0):.0f}/100\n"
            f"Čas ve streamu: {clip['start']:.0f}s - {clip['end']:.0f}s\n"
            f"Hook {clip.get('hook', 0):.0f} | emoce {clip.get('emotion', 0):.0f} | srozumitelnost "
            f"{clip.get('standalone', 0):.0f} | pointa {clip.get('payoff', 0):.0f} | humor "
            f"{clip.get('humor', 0):.0f} | tempo {clip.get('pacing', 0):.0f}\n"
            f"Proč: {clip.get('reason', '')}\n",
            encoding="utf-8",
        )
    clip["file"] = out_file.name
    return out_file


# ---------------------------------------------------------------- hlavní běh

def run_job(source: str, cfg: dict, rep: Reporter, *, reselect: bool = False,
            captions_override: Optional[bool] = None,
            loadout: Optional[dict] = None) -> dict:
    """Celý pipeline. Vrací {'out_dir': Path, 'clips': [...]} nebo vyhodí výjimku."""
    if not ffmpeg_available():
        raise RuntimeError("Chybí ffmpeg. Nainstaluj ho nebo přidej do PATH.")
    cfg = apply_speed(apply_profile(cfg))
    if captions_override is not None:
        cfg["captions"]["enabled"] = captions_override

    rep.progress(0.0, "Začínám")
    video, video_id, downloaded = get_source(source, cfg, rep)
    probe = probe_video(video)
    spec = auto_output(cfg, probe)
    fmt = cfg["clips"]["format"]
    if fmt == "short":
        loadout = clean_loadout(loadout) if loadout else (
            last_loadout(cfg) or default_loadout("short", probe["width"], probe["height"]))
        remember_loadout(cfg, loadout)
    else:
        loadout = None
    rep.log(f"Video {probe['width']}x{probe['height']}, {probe['kbps']} kb/s, "
            f"{probe['duration'] / 60:.0f} min. Výstup {spec['width']}x{spec['height']}, "
            f"{spec['fps']} fps, CRF {spec['crf']}.")
    job = work_root(cfg) / "jobs" / video_id
    job.mkdir(parents=True, exist_ok=True)

    segments = transcribe(video, job / "transcript.json", cfg, rep)
    if not segments:
        raise RuntimeError("V tomto videu nebyla nalezena žádná řeč.")
    duration = segments[-1]["end"]
    rep.progress(0.55, "Přepis hotový")

    cand_path = job / "candidates.json"
    if cand_path.exists() and not reselect:
        rep.log("Hodnocení AI je v cache, nevolám AI znovu (změna nastavení se projeví hned).")
        candidates = json.loads(cand_path.read_text(encoding="utf-8"))
    else:
        candidates = score_with_ai(segments, cfg, rep)
        cand_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")

    chosen = select_clips(candidates, cfg, duration)
    rep.log(f"AI navrhla {len(candidates)} momentů, prahem {cfg['clips']['min_score']}/100 "
            f"prošlo {len(chosen)} klipů.")

    out_dir = DATA_ROOT / cfg["output"]["folder"] / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, clip in enumerate(chosen, 1):
        rep.check()
        rep.log(f"Stříhám klip {i}/{len(chosen)} (hodnocení {clip['score']:.0f}): {clip['title']}")
        rep.progress(0.75 + 0.25 * (i - 1) / max(1, len(chosen)),
                     f"Stříhám klip {i}/{len(chosen)}")
        clip["format"] = fmt
        clip["src_size"] = [probe["width"], probe["height"]]
        clip["output_spec"] = spec
        clip["loadout"] = loadout
        render_clip(video, segments, clip, out_dir, cfg, i, rep)

    manifest = {"video_id": video_id, "created": datetime.now().isoformat(timespec="seconds"),
                "source": source, "clips": chosen}
    (out_dir / "clips.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                        encoding="utf-8")

    if downloaded and not cfg["download"]["keep_source"]:
        (work_root(cfg) / "downloads" / f"{video_id}.mp4").unlink(missing_ok=True)
    if not cfg["cache"]["keep_transcripts"]:
        (job / "transcript.json").unlink(missing_ok=True)
    if not cfg["cache"]["keep_selections"]:
        cand_path.unlink(missing_ok=True)
    auto_clean(cfg, rep)

    rep.progress(1.0, "Hotovo")
    rep.log(f"Hotovo: {len(chosen)} klipů ve složce {out_dir}")
    return {"out_dir": out_dir, "clips": chosen}


# ---------------------------------------------------------------- Ollama na pozadí

def start_ollama_background(cfg: dict) -> bool:
    """Při startu aplikace spustí Ollamu bez okna, když běží na tomto počítači a není spuštěná."""
    if cfg["ai"]["provider"] != "ollama" or ollama_models(cfg) is not None or not ollama_installed():
        return ollama_models(cfg) is not None
    local = os.environ.get("LOCALAPPDATA", "")
    exe = Path(local) / "Programs" / "Ollama" / "ollama.exe" if local else None
    cmd = [str(exe) if exe and exe.exists() else "ollama", "serve"]
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        subprocess.Popen(cmd, creationflags=flags, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        return False
    for _ in range(30):
        time.sleep(0.5)
        if ollama_models(cfg) is not None:
            return True
    return False


# ---------------------------------------------------------------- hledání videí na Kicku

KICK_API = "https://kick.com/api/v2/channels/{slug}/{kind}"
# url z vyhledávání -> záložní url (jiné možné ID téhož VODu)
ALT_URLS: dict[str, list[str]] = {}


def _kick_item(raw: dict, slug: str, kind: str) -> Optional[dict]:
    if kind == "videos":
        idents = []
        for cand in ((raw.get("video") or {}).get("uuid"), raw.get("uuid")):
            if cand and str(cand) not in idents:
                idents.append(str(cand))
        title = raw.get("session_title") or raw.get("title") or "bez názvu"
        urls = [f"https://kick.com/{slug}/videos/{i}" for i in idents]
        url = urls[0] if urls else ""
        ALT_URLS[url] = urls[1:] if url else []
    else:
        ident = raw.get("id") or raw.get("clip_id")
        title = raw.get("title") or "bez názvu"
        url = f"https://kick.com/{slug}/clips/{ident}" if ident else ""
    if not url:
        return None
    duration = raw.get("duration") or raw.get("length") or 0
    try:
        duration = float(duration)
        seconds = duration / 1000 if duration > 100000 else duration  # některá API dávají ms
    except (TypeError, ValueError):
        seconds = 0.0
    return {"title": str(title), "url": url, "created": str(raw.get("created_at", ""))[:16],
            "seconds": seconds, "kind": kind,
            "thumbnail": (raw.get("thumbnail") or {}).get("src", "")
            if isinstance(raw.get("thumbnail"), dict) else (raw.get("thumbnail") or "")}


def search_kick(channel: str, kinds: list[str], limit: int = 12) -> list[dict]:
    """Nejnovější videa a/nebo klipy kanálu na Kicku. kinds: ['videos'] a/nebo ['clips']."""
    slug = channel.strip().strip("/").split("/")[-1].lower()
    if not slug:
        raise ValueError("Zadej jméno kanálu, např. gasbyn.")
    results: list[dict] = []
    for kind in kinds:
        r = requests.get(KICK_API.format(slug=slug, kind=kind), timeout=15,
                         headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data.get("videos", []))
        for raw in items or []:
            item = _kick_item(raw, slug, kind)
            if item:
                results.append(item)
    results.sort(key=lambda x: x["created"], reverse=True)
    return results[:limit]


def stop_ollama() -> None:
    """Při ukončení Gasbyn Clipperu vypne i Ollamu (server i tray aplikaci)."""
    try:
        if os.name == "nt":
            flags = 0x08000000  # CREATE_NO_WINDOW
            for image in ("ollama app.exe", "ollama.exe"):
                subprocess.run(["taskkill", "/IM", image, "/F", "/T"], capture_output=True,
                               creationflags=flags, timeout=15)
        else:
            subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


# ---------------------------------------------------------------- připravenost (první spuštění)

OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"


def ollama_models(cfg: dict) -> Optional[list[str]]:
    """Seznam staženého modelu v Ollamě, nebo None když Ollama neběží."""
    try:
        r = requests.get(f"{cfg['ai']['ollama_url'].rstrip('/')}/api/tags", timeout=4)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return None


def ollama_installed() -> bool:
    local = os.environ.get("LOCALAPPDATA", "")
    return bool(local and (Path(local) / "Programs" / "Ollama" / "ollama.exe").exists()) \
        or shutil.which("ollama") is not None


def pull_ollama_model(cfg: dict, rep: Reporter) -> None:
    """Stáhne model v Ollamě a hlásí průběh (POST /api/pull, streamovaná odpověď)."""
    model = cfg["ai"]["ollama_model"]
    rep.log(f"Stahuji model {model} do Ollamy ...")
    with requests.post(f"{cfg['ai']['ollama_url'].rstrip('/')}/api/pull",
                       json={"model": model, "stream": True}, stream=True, timeout=None) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            rep.check()
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(data["error"])
            total, done = data.get("total"), data.get("completed")
            if total and done:
                rep.progress(done / total, f"Model {model}: {done / total * 100:.0f} %")
    rep.log(f"Model {model} je připravený.")


def prefetch_whisper(cfg: dict, rep: Reporter) -> None:
    """Stáhne model Whisper předem, aby první přepis nečekal na stahování."""
    from faster_whisper import WhisperModel
    t = cfg["transcription"]
    device = "cuda" if has_cuda() else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    rep.log(f"Stahuji přepisovací model Whisper {t['model']} (jednorázově, několik GB) ...")
    rep.progress(0.5, f"Whisper {t['model']}")
    WhisperModel(t["model"], device=device, compute_type=compute)
    rep.log("Přepisovací model je připravený.")


def setup_status(cfg: dict) -> dict:
    """Co je hotové a co chybí k okamžitému používání."""
    models = ollama_models(cfg) if cfg["ai"]["provider"] == "ollama" else None
    want = cfg["ai"]["ollama_model"]
    return {
        "ffmpeg": ffmpeg_available(),
        "ollama_running": models is not None,
        "ollama_installed": ollama_installed(),
        "model_ready": bool(models) and any(m.split(":")[0] == want.split(":")[0] and
                                            (":" not in want or m == want) for m in models),
        "provider": cfg["ai"]["provider"],
    }


def check_environment(cfg: dict) -> list[str]:
    """Vrací seznam stavů pro obrazovku Nastavení / příkaz --check."""
    lines = [f"ffmpeg: {'OK' if ffmpeg_available() else 'CHYBÍ'}",
             f"GPU (CUDA): {'ano' if has_cuda() else 'ne, poběží na procesoru'}"]
    if cfg["ai"]["provider"] == "ollama":
        try:
            requests.get(f"{cfg['ai']['ollama_url'].rstrip('/')}/api/tags", timeout=5).raise_for_status()
            lines.append("Ollama: OK")
        except requests.RequestException:
            lines.append("Ollama: NEDOSTUPNÁ (spusť Ollamu a stáhni model)")
    else:
        env = cfg["ai"]["openrouter_api_key_env"]
        lines.append(f"OpenRouter klíč: {'nastaven' if os.environ.get(env) else 'CHYBÍ (' + env + ')'}")
    return lines


def load_or_default() -> dict:
    """Nastavení z DATA_ROOT. Když chybí, přenese starý soubor z instalace a jinak vytvoří výchozí."""
    if not SETTINGS_FILE.exists():
        legacy = ROOT / "settings.yaml"
        if legacy.exists() and legacy != SETTINGS_FILE:
            shutil.copyfile(legacy, SETTINGS_FILE)
    cfg = load_settings(SETTINGS_FILE)
    if not SETTINGS_FILE.exists():
        write_settings(SETTINGS_FILE, cfg)
    return cfg


def save(cfg: dict) -> None:
    write_settings(SETTINGS_FILE, cfg)


__all__ = ["run_job", "Reporter", "Cancelled", "load_or_default", "save", "cache_report",
           "clean_cache", "auto_clean", "check_environment", "ROOT", "DATA_ROOT", "SETTINGS_FILE",
           "default_settings", "ffmpeg_available", "record_feedback", "render_clip",
           "parse_srt", "get_source", "default_effects", "EFFECT_KINDS", "probe_video",
           "extract_frame", "pick_best_frame", "default_loadout", "clean_loadout", "list_loadouts", "load_loadout",
           "save_loadout", "last_loadout", "remember_loadout", "start_ollama_background", "stop_ollama",
           "search_kick"]
