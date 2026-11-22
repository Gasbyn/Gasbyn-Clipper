"""Gasbyn Clipper core – auto-obnova + opravy (ffmpeg, crop).

Pri prvnim importu stahne plnou core.py z posledniho dobreho commitu,
aplikuje opravy a prepise se. Dalsi starty uz bezi normalne.
"""
from __future__ import annotations

import sys
from pathlib import Path

_GOOD = "11cc187f2e24842b92c02076546835a719df319d"
_URL = f"https://raw.githubusercontent.com/Gasbyn/Gasbyn-Clipper/{_GOOD}/core.py"
_MARKER = "GASBYN_CORE_PATCHED_v2"


def _apply_patches(data: str) -> str:
    if _MARKER in data:
        return data

    # 1) ffmpeg_location pro yt-dlp
    needle = '"socket_timeout": 30}'
    insert = (
        '"socket_timeout": 30,\n'
        '                 "ffmpeg_location": '
        'str(Path(ffmpeg_bin()).parent) if Path(ffmpeg_bin()).is_file() else ffmpeg_bin()}'
    )
    if needle in data and "ffmpeg_location" not in data:
        data = data.replace(needle, insert, 1)

    # 2) Robustnejsi crop v loadout_graph
    old_crop = '''        cx, cy, cw, ch = v["crop"]
        cw_px = min(src_w, _even(cw * src_w))
        ch_px = min(src_h, _even(ch * src_h))
        x_px = min(src_w - cw_px, max(0, int(cx * src_w)))
        y_px = min(src_h - ch_px, max(0, int(cy * src_h)))
        bx, by, bw, bh = v["place"]
        pw, ph = _even(bw * W), _even(bh * H)
        px, py = int(round(bx * W)), int(round(by * H))
        parts.append(f"[srcv{i}]crop={cw_px}:{ch_px}:{x_px}:{y_px},"
                     f"scale={pw}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,crop={pw}:{ph},"
                     f"setsar=1,format=yuva420p[v{i}raw]")'''

    new_crop = '''        cx, cy, cw, ch = v["crop"]
        # Bezpecne rozmery: min 2 px, vejde se do zdroje, sude (yuv420)
        cw_px = max(2, min(src_w, _even(max(0.01, cw) * src_w)))
        ch_px = max(2, min(src_h, _even(max(0.01, ch) * src_h)))
        x_px = max(0, min(src_w - cw_px, int(cx * src_w)))
        y_px = max(0, min(src_h - ch_px, int(cy * src_h)))
        if x_px + cw_px > src_w:
            x_px = max(0, src_w - cw_px)
        if y_px + ch_px > src_h:
            y_px = max(0, src_h - ch_px)
        bx, by, bw, bh = v["place"]
        pw = max(2, _even(max(0.01, bw) * W))
        ph = max(2, _even(max(0.01, bh) * H))
        px = max(0, min(W - 2, int(round(bx * W))))
        py = max(0, min(H - 2, int(round(by * H))))
        # scale+crop s explicitnim offsetem – odolne vuci zaokrouhleni
        parts.append(
            f"[srcv{i}]crop={cw_px}:{ch_px}:{x_px}:{y_px},"
            f"scale={pw}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={pw}:{ph}:(iw-ow)/2:(ih-oh)/2,"
            f"setsar=1,format=yuva420p[v{i}raw]"
        )'''

    if old_crop in data:
        data = data.replace(old_crop, new_crop, 1)

    data = data.replace(
        '"""Jádro Gasbyn Clipperu:',
        f'"""{_MARKER}\nJádro Gasbyn Clipperu:',
        1,
    )
    return data


def _restore() -> bool:
    target = Path(__file__).resolve()
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    if "def run_job" in text and len(text) > 20000 and _MARKER in text:
        return False
    import urllib.request
    print("[Gasbyn] Obnovuji core.py z GitHubu ...", flush=True)
    data = urllib.request.urlopen(_URL, timeout=90).read().decode("utf-8")
    data = _apply_patches(data)
    target.write_text(data, encoding="utf-8")
    print("[Gasbyn] core.py obnoven (ffmpeg + crop fix). Restartuj aplikaci.", file=sys.stderr, flush=True)
    return True


if _restore():
    raise SystemExit("[Gasbyn] core.py byl obnoven – spust aplikaci znovu.")

import importlib.util
_path = Path(__file__).resolve()
_spec = importlib.util.spec_from_file_location("_gasbyn_core", _path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _mod
_spec.loader.exec_module(_mod)
