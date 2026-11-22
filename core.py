"""Jádro Gasbyn Clipperu: stažení, přepis, AI hodnocení 0-100, výběr, střih, cache.

Používá ho GUI (app.py) i příkazová řádka (clipper.py). Průběh hlásí přes Reporter,
zrušení funguje přes threading.Event.
"""

from __future__ import annotations

import base64
import copy
import json
import hashlib
import math
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

if getattr(sys, "frozen", False):
    DATA_ROOT = Path(os.environ.get("APPDATA") or Path.home()) / "GasbynClipper"
else:
    DATA_ROOT = ROOT
try:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_ROOT = ROOT

SETTINGS_FILE = DATA_ROOT / "settings.yaml"


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


def ffmpeg_bin() -> str:
    bundled = ROOT / "ffmpeg" / "ffmpeg.exe"
    return str(bundled) if bundled.exists() else "ffmpeg"


def ffmpeg_available() -> bool:
    return Path(ffmpeg_bin()).exists() or shutil.which("ffmpeg") is not None
