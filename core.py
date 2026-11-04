"""Jádro Gasbyn Clipperu: stažení, přepis, AI hodnocení 0-100, výběr, střih, cache.

Používá ho GUI (app.py) i příkazová řádka (clipper.py). Průběh hlásí přes Reporter,
zrušení funguje přes threading.Event.
"""

from __future__ import annotations

import json
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

SETTINGS_FILE = ROOT / "settings.yaml"


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
    return ROOT / cfg["cache"]["work_dir"]


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

    with yt_dlp.YoutubeDL(base_opts) as ydl:
        info = ydl.extract_info(source, download=False)
    raw_id = str(info.get("id", "video"))
    path = dl_dir / f"{raw_id}.mp4"

    if path.exists() and path.stat().st_size > 0:
        rep.log("Video už je stažené, používám ho.")
        return path, slugify(raw_id), True

    rep.log(f"Stahuji video ({raw_id}) ...")

    def hook(data: dict) -> None:
        rep.check()
        if data.get("status") == "downloading" and data.get("total_bytes"):
            frac = data.get("downloaded_bytes", 0) / data["total_bytes"]
            rep.progress(0.25 * frac, "Stahuji video")

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

    rep.log(f"Přepisuji model {t['model']} na {device} ({compute}) ...")
    model = WhisperModel(t["model"], device=device, compute_type=compute)
    language = None if t["language"].strip().lower() in ("", "auto") else t["language"].strip()
    segments, info = model.transcribe(
        str(video),
        language=language,
        vad_filter=bool(t["vad_filter"]),
        beam_size=int(t["beam_size"]),
        initial_prompt=t["initial_prompt"] or None,
    )
    total = float(info.duration or 1.0)

    result = []
    for seg in segments:
        rep.check()
        result.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                       "text": seg.text.strip()})
        rep.progress(0.25 + 0.30 * min(1.0, seg.end / total), "Přepisuji řeč")

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
- description: one or two sentences.
- hashtags: 3 to 5 hashtags without spaces.
{extra}
Respond ONLY with JSON in this exact shape:
{{"clips": [{{"start": 0.0, "end": 0.0, "hook": 0, "emotion": 0, "standalone": 0, "payoff": 0, "humor": 0, "title": "", "description": "", "hashtags": [], "reason": ""}}]}}"""


def build_prompt(cfg: dict, n: int) -> str:
    c, ai = cfg["clips"], cfg["ai"]
    context = f"Channel context: {ai['channel_context']}" if ai["channel_context"].strip() else ""
    extra = f"Extra instructions from the creator: {ai['extra_instructions']}" if ai["extra_instructions"].strip() else ""
    return (PROMPT.replace("{context}", context)
            .replace("{min}", str(c["min_seconds"]))
            .replace("{max}", str(c["max_seconds"]))
            .replace("{n}", str(n))
            .replace("{extra}", extra))


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
    import os
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
        rep.progress(0.55 + 0.20 * (i - 1) / len(chunks), "AI hodnotí klipy")
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


# ---------------------------------------------------------------- 4. střih a titulky

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


POSITION_ALIGN = {"bottom": 2, "middle": 5, "top": 8}


def render_clip(video: Path, segments: list[dict], clip: dict, out_dir: Path,
                cfg: dict, index: int, rep: Reporter) -> Path:
    o, cap = cfg["output"], cfg["captions"]
    w, h = int(o["width"]), int(o["height"])

    try:
        name = o["file_pattern"].format(index=index, score=round(clip["score"]),
                                        title=slugify(clip["title"], 40))
    except (KeyError, IndexError, ValueError):
        name = f"klip_{index:02d}"
    name = slugify(name, 120)

    vf = [f"crop=trunc(ih*{w}/{h}/2)*2:ih", f"scale={w}:{h}", "setsar=1"]

    if cap["enabled"]:
        items = caption_items(segments, clip["start"], clip["end"],
                              int(cap["words_per_caption"]), bool(cap["uppercase"]))
        srt_name = f"{name}.srt"
        write_srt(out_dir / srt_name, items)
        style = ",".join([
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
        vf.append(f"subtitles={srt_name}:force_style='{style}'")

    out_file = out_dir / f"{name}.mp4"
    cmd = [
        ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{clip['start']:.3f}", "-i", str(video),
        "-t", f"{clip['end'] - clip['start']:.3f}",
        "-vf", ",".join(vf),
        "-r", str(int(o["fps"])),
        "-c:v", "libx264", "-preset", o["preset"], "-crf", str(int(o["crf"])),
        "-c:a", "aac", "-b:a", o["audio_bitrate"], "-movflags", "+faststart",
        out_file.name,
    ]
    rep.check()
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg selhal u klipu {index}: {proc.stderr.strip()[-400:]}")

    if o["write_txt"]:
        tags = " ".join(clip.get("hashtags", []))
        (out_dir / f"{name}.txt").write_text(
            f"{clip['title']}\n\n{clip.get('description', '')}\n\n{tags}\n\n"
            f"Hodnocení: {clip['score']:.0f}/100\n"
            f"Čas ve streamu: {clip['start']:.0f}s - {clip['end']:.0f}s\n"
            f"Hook {clip['hook']:.0f} | emoce {clip['emotion']:.0f} | srozumitelnost "
            f"{clip['standalone']:.0f} | pointa {clip['payoff']:.0f} | humor "
            f"{clip['humor']:.0f} | tempo {clip['pacing']:.0f}\n"
            f"Proč: {clip.get('reason', '')}\n",
            encoding="utf-8",
        )
    clip["file"] = out_file.name
    return out_file


# ---------------------------------------------------------------- hlavní běh

def run_job(source: str, cfg: dict, rep: Reporter, *, reselect: bool = False,
            captions_override: Optional[bool] = None) -> dict:
    """Celý pipeline. Vrací {'out_dir': Path, 'clips': [...]} nebo vyhodí výjimku."""
    if not ffmpeg_available():
        raise RuntimeError("Chybí ffmpeg. Nainstaluj ho nebo přidej do PATH.")
    if captions_override is not None:
        cfg["captions"]["enabled"] = captions_override

    rep.progress(0.0, "Začínám")
    video, video_id, downloaded = get_source(source, cfg, rep)
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

    out_dir = ROOT / cfg["output"]["folder"] / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, clip in enumerate(chosen, 1):
        rep.check()
        rep.log(f"Stříhám klip {i}/{len(chosen)} (hodnocení {clip['score']:.0f}): {clip['title']}")
        rep.progress(0.75 + 0.25 * (i - 1) / max(1, len(chosen)), "Stříhám klipy")
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
        import os
        env = cfg["ai"]["openrouter_api_key_env"]
        lines.append(f"OpenRouter klíč: {'nastaven' if os.environ.get(env) else 'CHYBÍ (' + env + ')'}")
    return lines


def load_or_default() -> dict:
    return load_settings(SETTINGS_FILE)


def save(cfg: dict) -> None:
    write_settings(SETTINGS_FILE, cfg)


__all__ = ["run_job", "Reporter", "Cancelled", "load_or_default", "save", "cache_report",
           "clean_cache", "auto_clean", "check_environment", "ROOT", "SETTINGS_FILE",
           "default_settings", "ffmpeg_available"]
