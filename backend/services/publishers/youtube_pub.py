import os
import logging
import threading
import webbrowser
import wsgiref.simple_server
from pathlib import Path
from typing import Dict, Any, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import (
    InstalledAppFlow,
    _RedirectWSGIApp,
    _ExclusiveWSGIServer,
    _WSGIRequestHandler
)
from google.auth.transport.requests import Request

import backend.config as app_config
from backend.config import BASE_DIR

logger = logging.getLogger("gta6-studio.publisher.youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/userinfo.profile"
]
TOKEN_FILE = BASE_DIR / "youtube_token.json"

class YouTubePublisher:
    def __init__(self):
        self.secrets_file = Path(app_config.YOUTUBE_CLIENT_SECRETS_FILE)
        self._cached_channel_info: Optional[Dict[str, Any]] = None
        self._active_auth_server = None
        self._active_auth_thread = None
        self._current_auth_url: Optional[str] = None

    def reload_config(self) -> None:
        self.secrets_file = Path(app_config.YOUTUBE_CLIENT_SECRETS_FILE)
        self._cached_channel_info = None

    def get_credentials(self) -> Optional[Credentials]:
        """Loads and validates existing credentials without blocking for user interaction"""
        if not TOKEN_FILE.exists():
            return None
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                except Exception as ref_err:
                    logger.warning(f"Could not refresh YouTube token: {ref_err}")
                    return None
            if creds and creds.valid:
                return creds
        except Exception as e:
            logger.warning(f"Error loading cached credentials: {e}")
        return None

    def start_auth_flow(self) -> str:
        """Starts the local redirect server in a background thread and returns the Google Auth URL immediately"""
        if not self.secrets_file.exists():
            raise FileNotFoundError(
                f"YouTube OAuth credentials file not found at: {self.secrets_file}. "
                "Please configure client_secret.json first."
            )

        # Close any previous listening server
        if self._active_auth_server:
            try:
                self._active_auth_server.server_close()
            except Exception:
                pass
            self._active_auth_server = None

        flow = InstalledAppFlow.from_client_secrets_file(str(self.secrets_file), SCOPES)
        success_message = "YouTube authorization successful! You can now close this tab and return to Stream-Clipper."
        wsgi_app = _RedirectWSGIApp(success_message)
        local_server = wsgiref.simple_server.make_server(
            "localhost",
            0,
            wsgi_app,
            server_class=_ExclusiveWSGIServer,
            handler_class=_WSGIRequestHandler,
        )
        self._active_auth_server = local_server
        flow.redirect_uri = f"http://localhost:{local_server.server_port}/"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        self._current_auth_url = auth_url

        def _run_server():
            try:
                logger.info(f"YouTube OAuth listener waiting on port {local_server.server_port}...")
                local_server.timeout = 300  # 5 minutes
                local_server.handle_request()
                if wsgi_app.last_request_uri:
                    auth_resp = (
                        wsgi_app.last_request_uri.replace("http://", "https://", 1)
                        if wsgi_app.last_request_uri.startswith("http://")
                        else wsgi_app.last_request_uri
                    )
                    flow.fetch_token(authorization_response=auth_resp)
                    TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")
                    self._cached_channel_info = None
                    self.get_channel_info(force_refresh=True)
                    logger.info("YouTube OAuth authentication succeeded!")
            except Exception as e:
                logger.warning(f"OAuth redirect handling error or timeout: {e}")
            finally:
                try:
                    local_server.server_close()
                except Exception:
                    pass
                if self._active_auth_server == local_server:
                    self._active_auth_server = None

        th = threading.Thread(target=_run_server, daemon=True)
        self._active_auth_thread = th
        th.start()

        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

        return auth_url

    def authenticate_interactive(self) -> Dict[str, Any]:
        """Runs the OAuth flow and returns connection status or auth URL"""
        auth_url = self.start_auth_flow()
        return {
            "status": "pending",
            "auth_url": auth_url,
            "message": "Auth server started. Open auth_url to authorize channel."
        }

    def get_channel_info(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Fetches channel profile details: title, thumbnail avatar URL, handle/customUrl"""
        if self._cached_channel_info and not force_refresh:
            return self._cached_channel_info

        creds = self.get_credentials()
        if not creds:
            return None

        # 1. Try YouTube Data API v3 channels.list(mine=True, part='snippet,statistics')
        try:
            youtube = build("youtube", "v3", credentials=creds)
            res = youtube.channels().list(part="snippet,statistics", mine=True).execute()
            items = res.get("items", [])
            if items:
                snippet = items[0].get("snippet", {})
                stats = items[0].get("statistics", {})
                thumbs = snippet.get("thumbnails", {})
                avatar_url = (
                    thumbs.get("high", {}).get("url")
                    or thumbs.get("medium", {}).get("url")
                    or thumbs.get("default", {}).get("url")
                )
                info = {
                    "channel_id": items[0].get("id"),
                    "channel_title": snippet.get("title"),
                    "channel_handle": snippet.get("customUrl"),
                    "channel_avatar": avatar_url,
                    "subscriber_count": stats.get("subscriberCount"),
                }
                self._cached_channel_info = info
                return info
        except Exception as yt_err:
            logger.warning(f"Failed to fetch YouTube channel details: {yt_err}")

        # 2. Fallback to Google OAuth2 UserInfo
        try:
            oauth2 = build("oauth2", "v2", credentials=creds)
            uinfo = oauth2.userinfo().get().execute()
            info = {
                "channel_id": uinfo.get("id"),
                "channel_title": uinfo.get("name"),
                "channel_handle": uinfo.get("email"),
                "channel_avatar": uinfo.get("picture"),
                "subscriber_count": None,
            }
            self._cached_channel_info = info
            return info
        except Exception as oauth_err:
            logger.warning(f"Failed to fetch Google userinfo fallback: {oauth_err}")

        return None

    def disconnect(self) -> Dict[str, Any]:
        """Clears stored tokens and resets cached channel info"""
        self._cached_channel_info = None
        if TOKEN_FILE.exists():
            try:
                TOKEN_FILE.unlink()
            except Exception as e:
                logger.warning(f"Error removing token file: {e}")
        return {"status": "disconnected", "message": "YouTube disconnected successfully."}

    def _get_authenticated_service(self):
        """Authenticates with YouTube Data API v3 using OAuth2 tokens"""
        creds = self.get_credentials()
        if not creds:
            if not self.secrets_file.exists():
                raise FileNotFoundError(
                    f"YouTube OAuth credentials file not found at: {self.secrets_file}. "
                    "Download client_secret.json from Google Cloud Console or configure it in settings."
                )
            self.authenticate_interactive()
            creds = self.get_credentials()
            if not creds:
                raise RuntimeError("Failed to authenticate YouTube service. Please connect your channel.")

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
