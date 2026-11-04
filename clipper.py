#!/usr/bin/env python3
"""Gasbyn Clipper - příkazová řádka (stejné jádro jako GUI).

Příklady:
  python clipper.py "https://kick.com/.../videos/..."
  python clipper.py stream.mp4 --no-captions --min-score 70
  python clipper.py --check
  python clipper.py --clean downloads
"""

import argparse
import sys
import threading

from core import (Reporter, Cancelled, load_or_default, save, run_job,
                  check_environment, clean_cache, cache_report)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Gasbyn Clipper")
    p.add_argument("source", nargs="?", help="URL VODu nebo cesta k videu (jinak z nastavení)")
    p.add_argument("--no-captions", action="store_true", help="klipy bez titulků")
    p.add_argument("--min-score", type=int, help="minimální hodnocení 0-100")
    p.add_argument("--count", type=float, help="klipů na hodinu materiálu")
    p.add_argument("--reselect", action="store_true", help="znovu zavolat AI (ignorovat cache)")
    p.add_argument("--check", action="store_true", help="jen zkontroluj prostředí")
    p.add_argument("--clean", choices=["downloads", "transcripts", "selections", "all"],
                   help="vyčistí cache a skončí")
    args = p.parse_args()

    cfg = load_or_default()

    if args.clean:
        clean_cache(cfg, args.clean, Reporter())
        return
    if args.check:
        for line in check_environment(cfg):
            print(line)
        print(f"Cache: {cache_report(cfg)['total'] / 1024 ** 2:.1f} MB")
        return

    if args.min_score is not None:
        cfg["clips"]["min_score"] = args.min_score
    if args.count is not None:
        cfg["clips"]["count_per_hour"] = args.count

    source = args.source or cfg["source"]["url"]
    if not source:
        sys.exit("Zadej URL nebo cestu k videu, nebo ho vyplň v nastavení (source.url).")

    rep = Reporter(log=print, progress=lambda f, t: None, cancel=threading.Event())
    try:
        run_job(source, cfg, rep, reselect=args.reselect,
                captions_override=False if args.no_captions else None)
    except Cancelled as exc:
        print(exc)
    except RuntimeError as exc:
        sys.exit(f"Chyba: {exc}")


if __name__ == "__main__":
    main()
