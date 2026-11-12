"""Nahrávání klipů na YouTube přes oficiální YouTube Data API (OAuth, zdarma).

Potřebuješ vlastní OAuth klient (typ "Desktop app") z Google Cloud Console.
Stáhni jeho JSON a v Nastavení ho vyber jako "Soubor client_secret". Postup je v README.

Limity (důležité):
- Denní kvóta projektu je obvykle 10 000 jednotek. Jedno nahrání stojí přibližně 1 600,
  takže vyjde zhruba 6 nahrání za den.
- Dokud projekt neprojde auditem YouTube, videa se nahrají jako soukromá, bez ohledu
  na nastavení viditelnosti.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def token_path(root: Path) -> Path:
    return root / "youtube_token.json"


def find_client_secret(root: Path, configured: str = "") -> Optional[Path]:
    """Najde client_secret JSON: nejdřív to, co je v Nastavení, pak soubor ve složce aplikace
    (client_secret*.json). Uživatel tak stačí jednou zkopírovat JSON do složky dat."""
    if configured and Path(configured).exists():
        return Path(configured)
    root.mkdir(parents=True, exist_ok=True)
    hits = sorted(root.glob("client_secret*.json")) or sorted(root.glob("*client_secret*.json"))
    return hits[0] if hits else None


def connect(client_secret: Path, root: Path) -> None:
    """Otevře prohlížeč, přihlásí účet a uloží token lokálně."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    token_path(root).write_text(creds.to_json(), encoding="utf-8")


def load_credentials(client_secret: Path, root: Path):
    """Vrátí platné přihlašovací údaje (obnoví token, pokud vypršel), jinak None."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tp = token_path(root)
    if not tp.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tp.write_text(creds.to_json(), encoding="utf-8")
    return creds if creds.valid else None


def is_connected(root: Path) -> bool:
    return token_path(root).exists()


def disconnect(root: Path) -> None:
    token_path(root).unlink(missing_ok=True)


def upload(video: Path, title: str, description: str, tags: list[str], privacy: str,
           creds, progress: Optional[Callable[[float], None]] = None) -> str:
    """Nahraje video a vrátí ID videa na YouTube."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    if privacy not in ("private", "unlisted", "public"):
        privacy = "private"
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [t.lstrip("#")[:30] for t in tags][:15],
            "categoryId": "20",  # Gaming; přepiš v nastavení, pokud potřebuješ jinou
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress:
            progress(status.progress())
    return response["id"]


def fetch_short_performance(root: Path, limit: int = 50) -> dict:
    """Načte poslední vlastní krátká videa a statistiky pro personalizaci odhadů."""
    from datetime import datetime, timezone
    import re
    from googleapiclient.discovery import build
    creds = load_credentials(Path(), root)
    if not creds: return {"videos": [], "median_views": 0, "sample_size": 0}
    api = build("youtube", "v3", credentials=creds, cache_discovery=False)
    channel = api.channels().list(part="contentDetails", mine=True, maxResults=1).execute()
    items = channel.get("items", [])
    if not items: return {"videos": [], "median_views": 0, "sample_size": 0}
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    playlist = api.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=min(50, max(1, limit))).execute()
    ids = [x.get("contentDetails", {}).get("videoId") for x in playlist.get("items", [])]
    ids = [x for x in ids if x]
    if not ids: return {"videos": [], "median_views": 0, "sample_size": 0}
    data = api.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids)).execute()
    now = datetime.now(timezone.utc); videos = []
    for item in data.get("items", []):
        duration = item.get("contentDetails", {}).get("duration", "")
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match: continue
        seconds = int(match.group(1) or 0)*3600 + int(match.group(2) or 0)*60 + int(match.group(3) or 0)
        if seconds <= 0 or seconds > 180: continue
        published = item.get("snippet", {}).get("publishedAt", "")
        try: age_days = max(1.0, (now - datetime.fromisoformat(published.replace("Z", "+00:00"))).total_seconds()/86400)
        except (TypeError, ValueError): age_days = 7.0
        views = int(item.get("statistics", {}).get("viewCount", 0))
        videos.append({"title": item.get("snippet", {}).get("title", ""), "views": views, "views_per_day": views/age_days, "tags": item.get("snippet", {}).get("tags", [])[:8]})
    if not videos: return {"videos": [], "median_views": 0, "sample_size": 0}
    rates = sorted(v["views_per_day"] for v in videos); mid = len(rates)//2
    median = rates[mid] if len(rates)%2 else (rates[mid-1]+rates[mid])/2
    return {"videos": videos, "median_views": round(median*7), "sample_size": len(videos)}