"""Gasbyn Clipper core – auto-obnova + ffmpeg fix pro yt-dlp.

Pri prvnim importu stahne plnou core.py z posledniho dobreho commitu,
aplikuje opravu ffmpeg_location a prepise se. Dalsi starty uz bezi normalne.
"""
from __future__ import annotations

import sys
from pathlib import Path

_GOOD = "11cc187f2e24842b92c02076546835a719df319d"
_URL = f"https://raw.githubusercontent.com/Gasbyn/Gasbyn-Clipper/{_GOOD}/core.py"


def _restore() -> bool:
    target = Path(__file__).resolve()
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    if "def run_job" in text and len(text) > 20000:
        return False
    import urllib.request
    print("[Gasbyn] Obnovuji core.py z GitHubu ...", flush=True)
    data = urllib.request.urlopen(_URL, timeout=90).read().decode("utf-8")
    needle = '"socket_timeout": 30}'
    insert = (
        '"socket_timeout": 30,\n'
        '                 "ffmpeg_location": '
        'str(Path(ffmpeg_bin()).parent) if Path(ffmpeg_bin()).is_file() else ffmpeg_bin()}'
    )
    if needle in data and "ffmpeg_location" not in data:
        data = data.replace(needle, insert, 1)
    target.write_text(data, encoding="utf-8")
    print("[Gasbyn] core.py obnoven. Restartuj aplikaci.", file=sys.stderr, flush=True)
    return True


if _restore():
    raise SystemExit("[Gasbyn] core.py byl obnoven – spust aplikaci znovu.")

import importlib.util
_path = Path(__file__).resolve()
_spec = importlib.util.spec_from_file_location("_gasbyn_core", _path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _mod
_spec.loader.exec_module(_mod)
