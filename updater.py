"""Automatické aktualizace: kontrola nejnovější Release na GitHubu a instalace Setup.exe."""

from __future__ import annotations

import os
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
    if r.status_code == 404:
        raise RuntimeError(
            "GitHub nevrátil nejnovější release (404). Repozitář je pravděpodobně soukromý - "
            "aktualizace bez přihlášení fungují jen u veřejného repozitáře.")
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
    """Stáhne Setup.exe do unikátního souboru; nedotkne se případného starého stažení."""
    fd, filename = tempfile.mkstemp(prefix="GasbynClipper-Setup-", suffix=".exe")
    os.close(fd)
    dest = Path(filename)
    try:
        with requests.get(url, stream=True, timeout=(15, 60), allow_redirects=True) as r:
            r.raise_for_status()
            expected = int(r.headers.get("content-length", 0))
            done = 0
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
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


def _ps_quote(value: str) -> str:
    """Bezpečné escapování cesty do PowerShell string literálu."""
    return "'" + value.replace("'", "''") + "'"


def install_and_restart(installer: Path) -> None:
    """Počká na ukončení aplikace, provede aktualizaci a znovu spustí novou verzi.

    Důležité: instalátor se nesmí rozběhnout souběžně s procesem, který má aktualizovat.
    Jinak může Windows odmítnout přepsání načtených DLL (např. MSVCP140_1.dll).
    """
    if not is_frozen():
        raise RuntimeError("Automatická instalace funguje pouze v nainstalované verzi.")

    app_exe = Path(sys.executable).resolve()
    installer = installer.resolve()
    helper = Path(tempfile.gettempdir()) / f"GasbynClipper-update-{os.getpid()}.ps1"
    script = f"""
$ErrorActionPreference = 'Stop'
$parentPid = {os.getpid()}
$installer = {_ps_quote(str(installer))}
$appExe = {_ps_quote(str(app_exe))}
while (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) {{
    Start-Sleep -Milliseconds 500
}}
try {{
    $p = Start-Process -FilePath $installer -ArgumentList @('/SILENT', '/CLOSEAPPLICATIONS') -Wait -PassThru
    if ($p.ExitCode -ne 0) {{
        throw "Instalátor skončil s kódem $($p.ExitCode)."
    }}
    if (Test-Path -LiteralPath $appExe) {{
        Start-Process -FilePath $appExe -WorkingDirectory (Split-Path -Parent $appExe)
    }}
}} finally {{
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}}
"""
    helper.write_text(script, encoding="utf-8-sig")
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except OSError:
        helper.unlink(missing_ok=True)
        raise
