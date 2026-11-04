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

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def token_path(root: Path) -> Path:
    return root / "youtube_token.json"


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
