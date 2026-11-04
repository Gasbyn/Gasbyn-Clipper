"""Automatické aktualizace: kontrola nejnovější Release na GitHubu a instalace Setup.exe."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

import requests

from version import APP_VERSION, GITHUB_REPO

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _parse(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_frozen() -> bool:
    """Aktualizace dává smysl jen u sestavené .exe, ne při běhu ze zdrojáků."""
    return getattr(sys, "frozen", False)


def check_for_update() -> Optional[dict]:
    """Vrátí {'version', 'url', 'notes'} když je na GitHubu novější verze, jinak None."""
    r = requests.get(API_LATEST, timeout=10,
                     headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    data = r.json()
    latest = data.get("tag_name", "")
    if _parse(latest) <= _parse(APP_VERSION):
        return None
    for asset in data.get("assets", []):
        if asset.get("name", "").lower() == "setup.exe":
            return {"version": latest.lstrip("vV"),
                    "url": asset["browser_download_url"],
                    "notes": data.get("body", "") or ""}
    return None


def download_installer(url: str, progress: Callable[[float], None] | None = None) -> Path:
    """Stáhne Setup.exe. Při chybě nebo neúplném souboru ho smaže, aby se nespustil poškozený."""
    dest = Path(tempfile.gettempdir()) / "GasbynClipper-Setup.exe"
    dest.unlink(missing_ok=True)
    try:
        # (připojení, čtení) - čtení je dlouhé kvůli souboru ~115 MB
        with requests.get(url, stream=True, timeout=(15, 60), allow_redirects=True) as r:
            r.raise_for_status()
            expected = int(r.headers.get("content-length", 0))
            done = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress and expected:
                        progress(min(1.0, done / expected))
        if expected and done != expected:
            raise OSError(f"stažení je neúplné ({done} z {expected} B)")
        if dest.stat().st_size < 1024 * 1024:
            raise OSError("stažený soubor je příliš malý, pravděpodobně chyba serveru")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest


def install_and_restart(installer: Path) -> None:
    """Spustí tichou instalaci. Volající pak musí aplikaci ukončit."""
    subprocess.Popen([str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
