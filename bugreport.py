"""Anonymní hlášení chyb Gasbyn Clipper – logy, sestava PC, popis, snímky."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    from version import APP_VERSION, GITHUB_REPO
except Exception:
    APP_VERSION = "?"
    GITHUB_REPO = "Gasbyn/Gasbyn-Clipper"


def _safe(cmd: list[str], timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return (r.stdout or r.stderr or "").strip()[:4000]
    except Exception as exc:
        return f"(nedostupné: {exc})"


def collect_system_info() -> dict:
    info = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "system": platform.system(),
        "release": platform.release(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "cwd": str(Path.cwd()),
        "executable": sys.executable,
    }
    if sys.platform == "win32":
        info["wmic_cpu"] = _safe(["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors"])
        info["wmic_mem"] = _safe(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"])
        info["wmic_gpu"] = _safe(["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM,DriverVersion"])
    try:
        from core import has_cuda, ffmpeg_bin, ffmpeg_available
        info["faster_whisper_cuda"] = has_cuda()
        info["ffmpeg"] = ffmpeg_bin()
        info["ffmpeg_ok"] = ffmpeg_available()
    except Exception as exc:
        info["core_probe"] = str(exc)
    return info


def collect_recent_logs(log_text: str = "", max_chars: int = 12000) -> str:
    text = (log_text or "").strip()
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


def build_report(description: str, log_text: str = "", extra: dict | None = None) -> dict:
    return {
        "description": (description or "").strip()[:4000],
        "system": collect_system_info(),
        "log": collect_recent_logs(log_text),
        "extra": extra or {},
    }


def save_report(report: dict, dest_dir: Path | None = None) -> Path:
    dest_dir = dest_dir or Path(tempfile.gettempdir()) / "GasbynClipperReports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = dest_dir / f"bugreport_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    txt = dest_dir / f"bugreport_{stamp}.txt"
    lines = [
        f"Gasbyn Clipper – hlášení chyby {stamp}",
        f"Verze: {report['system'].get('app_version')}",
        f"OS: {report['system'].get('platform')}",
        "",
        "=== Popis ===",
        report.get("description") or "(bez popisu)",
        "",
        "=== Sestava ===",
        json.dumps(report["system"], ensure_ascii=False, indent=2),
        "",
        "=== Log ===",
        report.get("log") or "(prázdný)",
    ]
    txt.write_text("\n".join(lines), encoding="utf-8")
    return txt


def open_github_issue(report: dict, report_file: Path) -> None:
    title = "Bug report: " + (report.get("description") or "chyba")[:80].replace("\n", " ")
    body_parts = [
        "### Popis",
        report.get("description") or "(doplň)",
        "",
        "### Verze / OS",
        f"- App: `{report['system'].get('app_version')}`",
        f"- OS: `{report['system'].get('platform')}`",
        f"- Frozen: `{report['system'].get('frozen')}`",
        f"- FFmpeg: `{report['system'].get('ffmpeg')}` ok={report['system'].get('ffmpeg_ok')}",
        f"- CUDA (whisper): `{report['system'].get('faster_whisper_cuda')}`",
        "",
        "### Log (zkrácený)",
        "```",
        (report.get("log") or "")[:3500],
        "```",
        "",
        f"_Kompletní report uložen lokálně: `{report_file}` – přilož ho prosím k issue._",
        "",
        "_Odesláno anonymně z aplikace Gasbyn Clipper._",
    ]
    body = "\n".join(body_parts)
    if len(body) > 5500:
        body = body[:5500] + "\n\n… (zkráceno, viz lokální soubor)"
    q = urllib.parse.urlencode({"title": title, "body": body, "labels": "bug"})
    webbrowser.open(f"https://github.com/{GITHUB_REPO}/issues/new?{q}")


def submit_bug_report(description: str, log_text: str = "", extra: dict | None = None) -> Path:
    report = build_report(description, log_text, extra)
    path = save_report(report)
    try:
        open_github_issue(report, path)
    except Exception:
        pass
    return path
