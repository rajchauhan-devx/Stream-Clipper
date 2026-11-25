import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import requests

import backend.config as app_config

logger = logging.getLogger("gta6-studio.publisher.meta")

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

class MetaPublisher:
    def __init__(self):
        self.access_token = app_config.META_ACCESS_TOKEN
        self.page_id = app_config.META_PAGE_ID
        self.ig_account_id = app_config.INSTAGRAM_ACCOUNT_ID
        self.tunnel_url = app_config.PUBLIC_TUNNEL_URL

    def reload_config(self) -> None:
        self.access_token = app_config.META_ACCESS_TOKEN
        self.page_id = app_config.META_PAGE_ID
        self.ig_account_id = app_config.INSTAGRAM_ACCOUNT_ID
        self.tunnel_url = app_config.PUBLIC_TUNNEL_URL

    def _ensure_credentials(self, platform_name: str):
        token = app_config.META_ACCESS_TOKEN or self.access_token or os.getenv("META_ACCESS_TOKEN")
        if not token:
            raise ValueError(
                f"Meta Access Token not configured for {platform_name}. "
                "Set META_ACCESS_TOKEN in Settings or use the 1-Click Export Pack."
            )
        return token

    # --------------------------------------------------------------------------
    # 1. Facebook Reels (3-Step Ruploadd Flow)
    # --------------------------------------------------------------------------
    def publish_facebook_reel(
        self,
        video_path: Path,
        caption: str,
        hashtags: Optional[list] = None,
        video_state: str = "PUBLISHED",
        scheduled_publish_time: Optional[int] = None,
        custom_page_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Publishes 9:16 vertical video to Facebook Reels using the 3-step Ruploadd Graph API.
        Supports instant publishing, scheduling, or saving as draft.
        """
        token = self._ensure_credentials("Facebook Reels")
        page_id = custom_page_id or self.page_id or os.getenv("META_PAGE_ID")
        if not page_id:
            raise ValueError("META_PAGE_ID not set. Please configure in Settings or enter Page ID.")

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        full_description = caption
        if hashtags:
            clean_tags = ["#" + t.lstrip("#") for t in hashtags]
            full_description += "\n\n" + " ".join(clean_tags)

        logger.info(f"Initiating Facebook Reels upload ({video_state}) for {video_path.name} to page {page_id}...")

        # Step 1: Start Upload Phase
        init_url = f"{GRAPH_BASE}/{page_id}/video_reels"
        init_res = requests.post(init_url, data={
            "upload_phase": "start",
            "access_token": token
        }, timeout=30)
        if init_res.status_code != 200:
            raise RuntimeError(f"FB Reels Init Failed: {init_res.text}")

        init_data = init_res.json()
        video_id = init_data.get("video_id")
        upload_url = init_data.get("upload_url")

        # Step 2: Binary Video Upload to rupload.facebook.com
        file_size = video_path.stat().st_size
        with open(video_path, "rb") as f:
            headers = {
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(file_size)
            }
            upload_res = requests.post(upload_url, data=f, headers=headers, timeout=300)
            if upload_res.status_code not in [200, 201]:
                raise RuntimeError(f"FB Reels Binary Upload Failed: {upload_res.text}")

        # Step 3: Finish Upload & Publish / Schedule / Draft
        finish_payload: Dict[str, Any] = {
            "upload_phase": "finish",
            "access_token": token,
            "video_id": video_id,
            "description": full_description
        }

        if video_state == "SCHEDULED" and scheduled_publish_time:
            finish_payload["video_state"] = "SCHEDULED"
            finish_payload["scheduled_publish_time"] = int(scheduled_publish_time)
            logger.info(f"Scheduling Facebook Reel for epoch {scheduled_publish_time}...")
        elif video_state == "DRAFT":
            finish_payload["video_state"] = "DRAFT"
        else:
            finish_payload["video_state"] = "PUBLISHED"

        finish_res = requests.post(init_url, data=finish_payload, timeout=30)
        if finish_res.status_code != 200:
            raise RuntimeError(f"FB Reels Finish Failed: {finish_res.text}")

        reel_url = f"https://www.facebook.com/reel/{video_id}"
        logger.info(f"Facebook Reel processed successfully: {reel_url} [{video_state}]")

        return {
            "platform": "facebook",
            "video_id": video_id,
            "url": reel_url,
            "status": video_state.lower(),
            "caption": caption
        }

    # --------------------------------------------------------------------------
    # 2. Instagram Reels (Container URL Pull Flow)
    # --------------------------------------------------------------------------
    def publish_instagram_reel(
        self,
        video_path: Path,
        caption: str,
        hashtags: Optional[list] = None,
        public_video_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Publishes 9:16 vertical video to Instagram Reels using the Media Container Flow.
        Instagram requires a public HTTPS URL from which it downloads the video.
        """
        token = self._ensure_credentials("Instagram Reels")
        ig_user_id = self.ig_account_id or os.getenv("INSTAGRAM_ACCOUNT_ID")
        if not ig_user_id:
            raise ValueError("INSTAGRAM_ACCOUNT_ID not set. Please configure in Settings.")

        # Determine public URL
        tunnel = public_video_url or self.tunnel_url or os.getenv("PUBLIC_TUNNEL_URL")
        if not tunnel:
            raise ValueError(
                "Instagram Graph API requires a public HTTPS URL to pull the video container. "
                "Configure PUBLIC_TUNNEL_URL (e.g. Cloudflare Quick Tunnel) or use the 1-Click Export Pack."
            )

        video_filename = video_path.name
        full_video_url = f"{tunnel.rstrip('/')}/workspace/renders/{video_filename}"

        full_caption = caption
        if hashtags:
            full_caption += "\n\n" + " ".join(hashtags)

        logger.info(f"Creating Instagram Reels container from {full_video_url}...")

        # Step 1: Create Container
        container_url = f"{GRAPH_BASE}/{ig_user_id}/media"
        c_res = requests.post(container_url, data={
            "media_type": "REELS",
            "video_url": full_video_url,
            "caption": full_caption[:2200],
            "access_token": token
        }, timeout=30)
        if c_res.status_code != 200:
            raise RuntimeError(f"Instagram Container Creation Failed: {c_res.text}")

        container_id = c_res.json().get("id")

        # Step 2: Poll Container Status until FINISHED
        status_url = f"{GRAPH_BASE}/{container_id}"
        max_retries = 30
        is_ready = False
        for _ in range(max_retries):
            time.sleep(3)
            s_res = requests.get(status_url, params={"fields": "status_code", "access_token": token}, timeout=30)
            if s_res.status_code == 200:
                sc = s_res.json().get("status_code")
                if sc == "FINISHED":
                    is_ready = True
                    break
                elif sc in ["ERROR", "EXPIRED"]:
                    raise RuntimeError(f"Instagram Container Error: {s_res.json()}")

        if not is_ready:
            raise TimeoutError("Timed out waiting for Instagram to process video container.")

        # Step 3: Publish Container
        publish_url = f"{GRAPH_BASE}/{ig_user_id}/media_publish"
        p_res = requests.post(publish_url, data={
            "creation_id": container_id,
            "access_token": token
        }, timeout=30)
        if p_res.status_code != 200:
            raise RuntimeError(f"Instagram Media Publish Failed: {p_res.text}")

        published_id = p_res.json().get("id")
        ig_url = f"https://www.instagram.com/reel/{published_id}/"
        logger.info(f"Instagram Reel published successfully: {ig_url}")

        return {
            "platform": "instagram",
            "media_id": published_id,
            "url": ig_url,
            "status": "published"
        }

meta_publisher = MetaPublisher()
