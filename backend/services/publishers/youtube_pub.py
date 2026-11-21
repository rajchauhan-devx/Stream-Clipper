import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from backend.config import BASE_DIR, YOUTUBE_CLIENT_SECRETS_FILE

logger = logging.getLogger("gta6-studio.publisher.youtube")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = BASE_DIR / "youtube_token.json"

class YouTubePublisher:
    def __init__(self):
        self.secrets_file = Path(YOUTUBE_CLIENT_SECRETS_FILE)

    def _get_authenticated_service(self):
        """Authenticates with YouTube Data API v3 using OAuth2 tokens"""
        creds = None
        if TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            except Exception as e:
                logger.warning(f"Could not load cached YouTube token: {e}")

        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.secrets_file.exists():
                    raise FileNotFoundError(
                        f"YouTube OAuth credentials file not found at: {self.secrets_file}. "
                        "Download client_secret.json from Google Cloud Console or use the 1-Click Export Pack."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.secrets_file), SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for next run
            TOKEN_FILE.write_text(creds.to_json())

        return build("youtube", "v3", credentials=creds)

    def publish_short(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[list] = None,
        privacy: str = "public",
        publish_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uploads 1080x1920 MP4 video to YouTube Shorts with resumable upload.
        Supports public, unlisted, private, or scheduled publishing.
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Ensure #Shorts is present in title for vertical Shorts ranking
        if "#shorts" not in title.lower():
            title = f"{title} #Shorts"

        tags = tags or ["GTA6", "Shorts", "Gaming"]
        if "Shorts" not in tags:
            tags.append("Shorts")

        status_dict: Dict[str, Any] = {
            "selfDeclaredMadeForKids": False
        }
        
        # YouTube requires scheduled videos to have privacyStatus="private" and publishAt in RFC 3339
        if privacy == "scheduled" and publish_at:
            status_dict["privacyStatus"] = "private"
            # Ensure ISO 8601 formatting ends with Z
            formatted_dt = publish_at
            if not formatted_dt.endswith("Z") and "+" not in formatted_dt:
                formatted_dt = f"{formatted_dt}Z"
            status_dict["publishAt"] = formatted_dt
            logger.info(f"Scheduling {video_path.name} to publish at {formatted_dt}...")
        else:
            status_dict["privacyStatus"] = privacy if privacy in ["public", "private", "unlisted"] else "public"
            logger.info(f"Uploading {video_path.name} to YouTube Shorts [{status_dict['privacyStatus']}]...")

        youtube = self._get_authenticated_service()

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags,
                "categoryId": "20"  # Gaming Category
            },
            "status": status_dict
        }

        media = MediaFileUpload(
            str(video_path),
            chunksize=1024 * 1024 * 4,  # 4MB chunks
            resumable=True,
            mimetype="video/mp4"
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"YouTube Upload Progress: {int(status.progress() * 100)}%")

        video_id = response.get("id")
        short_url = f"https://youtube.com/shorts/{video_id}"
        logger.info(f"YouTube Short published successfully: {short_url}")

        return {
            "platform": "youtube",
            "video_id": video_id,
            "url": short_url,
            "status": "published",
            "title": title
        }

youtube_publisher = YouTubePublisher()
