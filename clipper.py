#!/usr/bin/env python3
"""Gasbyn Clipper: z dlouhého VOD (Kick / YouTube / lokální soubor) udělá vertikální klipy.

Pipeline:
  1. stažení videa (yt-dlp) nebo použití lokálního souboru
  2. přepis řeči (faster-whisper)
  3. AI (Ollama lokálně nebo OpenRouter) vybere nejlepší momenty
  4. ffmpeg vystřihne klipy, ořízne na 9:16 a volitelně zapálí titulky
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests
import yaml

if getattr(sys, "frozen", False):
    # po sestavení do .exe: nastavení a ffmpeg leží vedle EXE
    ROOT = Path(sys.executable).resolve().parent
    os.environ["PATH"] = str(ROOT) + os.pathsep + os.environ.get("PATH", "")
else:
    ROOT = Path(__file__).resolve().parent


def ffmpeg_bin() -> str:
    """ffmpeg přibalený v instalaci, jinak ffmpeg z PATH."""
    bundled = ROOT / "ffmpeg" / "ffmpeg.exe"
    return str(bundled) if bundled.exists() else "ffmpeg"


# ---------------------------------------------------------------- utilita

def load_settings(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return text[:80] or "video"


def has_cuda() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# ---------------------------------------------------------------- 1. zdroj

def get_source(source: str, work_dir: Path, cfg: dict) -> tuple[Path, str]:
    """Vrátí (cesta k videu, id videa)."""
    local = Path(source)
    if local.exists():
        return local.resolve(), slugify(local.stem)

    import yt_dlp

    out_dir = work_dir / "downloads"
    out_dir.mkdir(parents=True, exist_ok=True)
    height = cfg["download"]["max_height"]
    opts = {
        "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=True)
    raw_id = str(info.get("id", "video"))
    path = out_dir / f"{raw_id}.mp4"
    if not path.exists():
        raise SystemExit(f"Stažení se nepovedlo, soubor {path} neexistuje.")
    return path, slugify(raw_id)


# ---------------------------------------------------------------- 2. přepis

def transcribe(video: Path, out_json: Path, cfg: dict) -> list[dict]:
    if out_json.exists():
        print("Přepis už existuje, používám uložený.")
        return json.loads(out_json.read_text(encoding="utf-8"))

    from faster_whisper import WhisperModel

    t = cfg["transcription"]
    device = t["device"]
    if device == "auto":
        device = "cuda" if has_cuda() else "cpu"
    compute = "float16" if device == "cuda" else "int8"

    print(f"Přepisuji model {t['model']} na {device} ...")
    model = WhisperModel(t["model"], device=device, compute_type=compute)
    language = None if t["language"] == "auto" else t["language"]
    segments, _info = model.transcribe(
        str(video), language=language, vad_filter=True, beam_size=5
    )

    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        if len(result) % 300 == 0:
            print(f"  ... přepsáno {seg.end / 60:.0f} min")

    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


# ---------------------------------------------------------------- 3. výběr AI

SYSTEM_PROMPT = """Jsi střihač, který z dlouhého streamu vybírá nejlepší krátké vertikální klipy (Shorts, Reels, TikTok).

Pravidla:
- Vybírej momenty, které dávají smysl i bez kontextu: vtipné výměny, silné názory, reakce, příběh s pointou, napínavá situace.
- Každý klip musí začínat a končit přirozeně (začátek věty, konec myšlenky), použij časy z přepisu.
- Délka klipu: mezi {min} a {max} sekundami.
- Přeskoč small talk, prázdná místa, sponzorské čtení, opakování a výplň.
- Ke každému klipu napiš krátký výstižný titulek ve stejném jazyce jako přepis.
- Vrať nejvýše {n} klipů z této části, seřazené od nejlepšího. Pokud nic dobrého není, vrať prázdný seznam.
- Odpověz POUZE JSONem v tomto tvaru:
{{"clips": [{{"start": <sekundy>, "end": <sekundy>, "score": <1-10>, "title": "...", "reason": "..."}}]}}"""


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


def format_chunk(chunk: list[dict]) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in chunk)


def ask_llm(cfg: dict, system: str, user: str) -> str:
    ai = cfg["ai"]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    if ai["provider"] == "ollama":
        o = ai["ollama"]
        r = requests.post(
            f"{o['url'].rstrip('/')}/api/chat",
            json={
                "model": o["model"],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_ctx": o["num_ctx"]},
                "messages": messages,
            },
            timeout=900,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    if ai["provider"] == "openrouter":
        o = ai["openrouter"]
        key = os.environ.get(o["api_key_env"], "")
        if not key:
            raise SystemExit(f"Nastav proměnnou prostředí {o['api_key_env']} s klíčem OpenRouter.")
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": o["model"], "temperature": 0.3, "messages": messages},
            timeout=900,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    raise SystemExit(f"Neznámý ai.provider: {ai['provider']}")


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


def overlap_ratio(a: dict, b: dict) -> float:
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if inter <= 0:
        return 0.0
    shorter = min(a["end"] - a["start"], b["end"] - b["start"])
    return inter / shorter


def pick_clips(segments: list[dict], cfg: dict, duration: float) -> list[dict]:
    c = cfg["clips"]
    chunk_min = cfg["ai"]["chunk_minutes"]
    chunks = build_chunks(segments, chunk_min * 60)
    per_chunk = max(1, round(c["count_per_hour"] * chunk_min / 60) + 1)

    candidates = []
    for i, chunk in enumerate(chunks, 1):
        lo, hi = chunk[0]["start"], chunk[-1]["end"]
        print(f"AI prochází část {i}/{len(chunks)} ({lo / 60:.0f}-{hi / 60:.0f} min) ...")
        system = SYSTEM_PROMPT.format(min=c["min_seconds"], max=c["max_seconds"], n=per_chunk)
        raw = ask_llm(cfg, system, "Část přepisu (časy v sekundách):\n" + format_chunk(chunk))

        for clip in parse_clips(raw):
            try:
                s, e = float(clip["start"]), float(clip["end"])
            except (KeyError, TypeError, ValueError):
                continue
            length = e - s
            if length < c["min_seconds"] or length > c["max_seconds"] or s < 0 or e > duration + 1:
                continue
            try:
                score = float(clip.get("score", 5))
            except (TypeError, ValueError):
                score = 5.0
            candidates.append({
                "start": round(s, 2),
                "end": round(e, 2),
                "score": score,
                "title": str(clip.get("title", "klip")).strip() or "klip",
                "reason": str(clip.get("reason", "")).strip(),
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    target = max(1, round(c["count_per_hour"] * duration / 3600))

    chosen = []
    for cand in candidates:
        if all(overlap_ratio(cand, other) <= 0.25 for other in chosen):
            chosen.append(cand)
        if len(chosen) >= target:
            break
    return chosen


# ---------------------------------------------------------------- 4. střih

def caption_items(segments: list[dict], start: float, end: float, words: int) -> list[tuple]:
    """Rozdělí přepis na krátké titulky (čas od začátku klipu, text)."""
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
            items.append((max(g_start, start) - start, min(g_end, end) - start, " ".join(group)))
    return items


def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".", ",")


def write_srt(path: Path, items: list[tuple]) -> None:
    lines = []
    for idx, (a, b, text) in enumerate(items, 1):
        lines += [str(idx), f"{srt_time(a)} --> {srt_time(b)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def render_clip(video: Path, segments: list[dict], clip: dict, out_dir: Path, cfg: dict, index: int) -> Path:
    name = f"klip_{index:02d}"
    o, cap = cfg["output"], cfg["captions"]
    w, h = o["width"], o["height"]

    vf = [
        f"crop=trunc(ih*{w}/{h}/2)*2:ih",   # střed záběru na výšku, 9:16
        f"scale={w}:{h}",
        "setsar=1",
    ]

    if cap["enabled"]:
        items = caption_items(segments, clip["start"], clip["end"], cap["words_per_caption"])
        srt_name = f"{name}.srt"
        write_srt(out_dir / srt_name, items)
        style = ",".join([
            f"FontName={cap['font']}",
            f"FontSize={cap['font_size']}",
            f"PrimaryColour={cap['text_color']}",
            "OutlineColour=&H00000000",
            f"Outline={cap['outline_width']}",
            "Shadow=0",
            "Bold=1",
            "Alignment=2",
            f"MarginV={cap['margin_bottom']}",
        ])
        vf.append(f"subtitles={srt_name}:force_style='{style}'")

    out_file = out_dir / f"{name}.mp4"
    cmd = [
        ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{clip['start']:.3f}", "-i", str(video),
        "-t", f"{clip['end'] - clip['start']:.3f}",
        "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", o["preset"], "-crf", str(o["crf"]),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        out_file.name,
    ]
    # spouštíme ve složce klipu, aby filtr subtitles našel .srt bez složitých cest
    subprocess.run(cmd, cwd=out_dir, check=True)

    (out_dir / f"{name}.txt").write_text(
        f"{clip['title']}\n\nČas ve streamu: {clip['start']:.0f}s - {clip['end']:.0f}s\n"
        f"Skóre: {clip['score']:.0f}/10\nProč: {clip['reason']}\n",
        encoding="utf-8",
    )
    return out_file


# ---------------------------------------------------------------- hlavní běh

def process(source: str, cfg: dict) -> None:
    work = ROOT / cfg["work_dir"]
    video, video_id = get_source(source, work, cfg)
    job_dir = work / video_id
    job_dir.mkdir(parents=True, exist_ok=True)

    segments = transcribe(video, job_dir / "transcript.json", cfg)
    if not segments:
        raise SystemExit("V videu jsem nenašel žádnou řeč.")
    duration = segments[-1]["end"]

    clips_json = job_dir / "clips.json"
    if clips_json.exists():
        print("Výběr klipů už existuje, používám uložený (smaž clips.json pro nový výběr).")
        clips = json.loads(clips_json.read_text(encoding="utf-8"))
    else:
        clips = pick_clips(segments, cfg, duration)
        clips_json.write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")

    if not clips:
        print("AI nenašla žádné dobré klipy.")
        return

    out_dir = ROOT / cfg["output_dir"] / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, clip in enumerate(clips, 1):
        print(f"Stříhám klip {i}/{len(clips)}: {clip['title']}")
        render_clip(video, segments, clip, out_dir, cfg, i)

    print(f"Hotovo: {len(clips)} klipů ve složce {out_dir}")


def check(cfg: dict) -> None:
    found = Path(ffmpeg_bin()).exists() or shutil.which("ffmpeg")
    print("ffmpeg:        ", "OK" if found else "CHYBÍ (přidej do PATH)")
    print("CUDA (GPU):    ", "ano" if has_cuda() else "ne, poběží na CPU")
    if cfg["ai"]["provider"] == "ollama":
        url = cfg["ai"]["ollama"]["url"].rstrip("/")
        try:
            requests.get(f"{url}/api/tags", timeout=5).raise_for_status()
            print("Ollama:        OK")
        except requests.RequestException:
            print("Ollama:         NEDOSTUPNÁ, spusť Ollamu a stáhni model")
    else:
        env = cfg["ai"]["openrouter"]["api_key_env"]
        print("OpenRouter klíč:", "nastaven" if os.environ.get(env) else f"CHYBÍ (proměnná {env})")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Gasbyn Clipper")
    p.add_argument("source", nargs="?", help="URL VODu nebo cesta k lokálnímu videu (jinak source.url v settings.yaml)")
    p.add_argument("--no-captions", action="store_true", help="klipy bez titulků")
    p.add_argument("--count", type=int, help="počet klipů na hodinu materiálu")
    p.add_argument("--check", action="store_true", help="jen zkontroluj prostředí")
    args = p.parse_args()

    cfg = load_settings(ROOT / "settings.yaml")
    if args.no_captions:
        cfg["captions"]["enabled"] = False
    if args.count:
        cfg["clips"]["count_per_hour"] = args.count

    if args.check:
        check(cfg)
        return

    source = args.source or cfg["source"]["url"]
    if not source and sys.stdin.isatty():
        # spuštěno dvojklikem / ze zástupce: zeptej se na URL
        source = input("Vlož URL VODu nebo cestu k videu a potvrď Enter: ").strip().strip('"')
    if not source:
        sys.exit("Zadej URL nebo cestu k videu, nebo nastav source.url v settings.yaml.")
    process(source, cfg)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if getattr(sys, "frozen", False) and exc.code not in (0, None):
            print(f"\nChyba: {exc.code}")
        if getattr(sys, "frozen", False):
            input("\nStiskni Enter pro zavření...")
        raise
    if getattr(sys, "frozen", False):
        input("\nHotovo. Stiskni Enter pro zavření...")
