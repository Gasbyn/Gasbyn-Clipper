"""Automatické aktualizace: kontrola nejnovější Release na GitHubu a instalace Setup.exe.

Vylepšeno pro verzi 1.2.0 – robustnější stahování, více pokusů, lepší bezpečnost.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from version import APP_VERSION, GITHUB_REPO

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
MAX_INSTALLER_SIZE = 400 * 1024 * 1024  # 400 MB bezpečnostní limit
MAX_DOWNLOAD_ATTEMPTS = 3


def _parse(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_frozen() -> bool:
    """Aktualizace dává smysl jen u sestavené .exe, ne při běhu ze zdrojáků."""
    return getattr(sys, "frozen", False)


def check_for_update() -> Optional[dict]:
    """Vrátí {'version', 'url', 'notes'} když je na GitHubu novější verze, jinak None."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"GasbynClipper/{APP_VERSION}",
    }
    last_exc: Exception | None = None
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            r = requests.get(API_LATEST, timeout=12, headers=headers)
            if r.status_code == 404:
                raise RuntimeError(
                    "GitHub nevrátil nejnovější release (404). Repozitář je pravděpodobně soukromý – "
                    "aktualizace bez přihlášení fungují jen u veřejného repozitáře.")
            r.raise_for_status()
            data = r.json()
            latest = data.get("tag_name", "")
            if _parse(latest) <= _parse(APP_VERSION):
                return None
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if name == "setup.exe" or name.endswith("-setup.exe"):
                    return {
                        "version": latest.lstrip("vV"),
                        "url": asset["browser_download_url"],
                        "notes": (data.get("body") or "").strip(),
                        "size": int(asset.get("size") or 0),
                    }
            return None
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_DOWNLOAD_ATTEMPTS:
                time.sleep(attempt * 1.5)
    if last_exc:
        raise last_exc
    return None


def download_installer(
    url: str,
    progress: Callable[[float], None] | None = None,
    expected_size: int = 0,
) -> Path:
    """Stáhne Setup.exe do unikátního souboru s opakovanými pokusy a kontrolou velikosti."""
    if not url.startswith("https://github.com/Gasbyn/Gasbyn-Clipper/releases/download/"):
        raise ValueError("Odkaz ke stažení nevede na důvěryhodné vydání Gasbyn Clipperu.")

    fd, filename = tempfile.mkstemp(prefix="GasbynClipper-Setup-", suffix=".exe")
    os.close(fd)
    dest = Path(filename)

    headers = {"User-Agent": f"GasbynClipper/{APP_VERSION}"}
    last_exc: Exception | None = None

    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            with requests.get(url, stream=True, timeout=(15, 120), allow_redirects=True, headers=headers) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or expected_size or 0)
                if total > MAX_INSTALLER_SIZE:
                    raise OSError(f"Instalátor je nečekaně velký ({total / 1024**2:.0f} MB).")

                done = 0
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        done += len(chunk)
                        if done > MAX_INSTALLER_SIZE:
                            raise OSError("Stažený soubor překročil bezpečnostní limit.")
                        if progress and total:
                            progress(min(1.0, done / total))

            if total and done != total:
                raise OSError(f"Stažení je neúplné ({done} z {total} B)")
            if dest.stat().st_size < 1024 * 512:
                raise OSError("Stažený soubor je příliš malý, pravděpodobně chyba serveru.")
            return dest
        except Exception as exc:
            last_exc = exc
            dest.unlink(missing_ok=True)
            if attempt < MAX_DOWNLOAD_ATTEMPTS:
                time.sleep(attempt * 2)

    dest.unlink(missing_ok=True)
    raise last_exc or RuntimeError("Stažení aktualizace selhalo.")


def _ps_quote(value: str) -> str:
    """Bezpečné escapování cesty do PowerShell string literálu."""
    return "'" + value.replace("'", "''") + "'"


def install_and_restart(installer: Path) -> None:
    """Počká na ukončení aplikace, provede tichou aktualizaci a znovu spustí novou verzi.

    Instalátor se spouští až po ukončení aktuálního procesu, aby Windows
    mohl přepsat načtené DLL.
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
$workDir = Split-Path -Parent $appExe

# Počkej na bezpečné ukončení aplikace (max 90 s)
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Process -Id $parentPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {{
    Start-Sleep -Milliseconds 400
}}
if (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) {{
    throw "Aplikace se nepodařilo bezpečně ukončit."
}}

try {{
    $p = Start-Process -FilePath $installer -ArgumentList @('/SILENT', '/CLOSEAPPLICATIONS', '/NORESTART') -Wait -PassThru
    if ($null -eq $p -or $p.ExitCode -ne 0) {{
        $code = if ($null -ne $p) {{ $p.ExitCode }} else {{ 'null' }}
        throw "Instalátor skončil s kódem $code."
    }}
    Start-Sleep -Seconds 1
    if (Test-Path -LiteralPath $appExe) {{
        Start-Process -FilePath $appExe -WorkingDirectory $workDir
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
