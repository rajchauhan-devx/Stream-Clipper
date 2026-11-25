"""Audit exact render windows for every creator overlay, independently of story selection."""

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any
from typing import Literal

from google.genai import types
from pydantic import BaseModel

import backend.config as app_config
from backend.schemas import WatermarkInfo, WatermarkCorner, CreatorOverlayRegion
from backend.services.explainer import provider_schema


class LocalizedOverlay(BaseModel):
    kind: Literal["facecam", "channel_logo", "creator_text"]
    visible_text: str
    box_2d: list[int]


class LocalizedOverlays(BaseModel):
    regions: list[LocalizedOverlay]


def audit_creator_overlays(director: Any, source: Path, windows: list[tuple[float, float]]) -> WatermarkInfo:
    client = director._ensure_client()
    if not client:
        raise RuntimeError("Creator masking requires a working vision connection; rendering stopped before exposing overlays.")
    paths, remote_files, parts, stills = [], [], [], []
    try:
        for start, duration in windows:
            path = director.temp_dir / f"creator_audit_{uuid.uuid4().hex}.mp4"
            paths.append(path)
            # Preserve corners: timestamp burn-ins used for story review can hide small creator logos.
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(duration),
                "-i", str(source), "-vf", "fps=5,scale=-2:720", "-an",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", str(path),
            ], check=True, capture_output=True)
            part, remote, compact = director._prepare_video_part(client, path, allow_compress=False)
            if remote:
                remote_files.append(remote)
            if compact:
                paths.append(compact)
            if not isinstance(part, types.Part):
                part = types.Part.from_uri(file_uri=part.uri, mime_type=part.mime_type or "video/mp4")
            part.video_metadata = types.VideoMetadata(fps=5)
            parts.append(part)
            # High-resolution stills anchor geometry; video-only spatial estimates can be too broad.
            frame = subprocess.run([
                "ffmpeg", "-v", "error", "-ss", str(duration / 2), "-i", str(path),
                "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "-",
            ], check=True, capture_output=True)
            stills.append(types.Part.from_bytes(data=frame.stdout, mime_type="image/jpeg"))

        prompt = """Inspect ALL supplied video segments for creator overlays, including small logos.
Return watermark_info with EVERY distinct region to conceal: the FULL real streamer webcam rectangle
(face, room, border, camera labels), every separate channel logo, channel name, social handle, and
creator watermark anywhere in the picture. Inspect all four corners and the entire frame throughout.
Use normalized ORIGINAL input-frame coordinates x,y,width,height in [0,1], NOT a vertical output canvas.
The videos are followed by one full-frame still per segment. Use these clear stills to anchor exact geometry.
Do not cover an oversized quadrant: the rectangle must tightly enclose the actual overlay, not nearby gameplay.
For moving overlays return rectangles covering the union of their positions across ALL segments.
Include small initials logos even without readable text; label may be empty but geometry is required.
Do not flag in-game people, game dialogue subtitles, mission HUD, minimaps, or game UI as creator overlays.
Game/client labels such as FiveM (b2802) and game engine icons are game UI, not channel branding.
Only transcribe text actually visible inside that rectangle. Never infer a channel name from initials,
the streamer's identity, or another region. Never invent a lower-corner watermark from a top-corner logo.
For creator_text, you must be able to point to the actual readable channel letters inside that region
in the supplied images. If those letters are absent, omit that creator_text region entirely.
detected=true requires nonempty regions. detected=false requires regions=[]. No inferred clean result.
"""
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=provider_schema(WatermarkInfo.model_json_schema()),
            temperature=0, max_output_tokens=4096,
        )
        model = app_config.DIRECTOR_MODEL
        if "gemini-2.5" in model:
            config.thinking_config = types.ThinkingConfig(thinking_budget=1024)
        response = director._generate_content_with_retry(client, model, [*parts, *stills, prompt], config)
        result = WatermarkInfo.model_validate(json.loads(response.text))
        if result.detected != bool(result.regions):
            raise ValueError("Incomplete creator-overlay audit; refusing to render without mask geometry.")
        if not result.detected:
            return result

        # Spatial grounding is separate from temporal video discovery. Standard image boxes
        # avoid video-only estimates that can double camera height or invent channel text.
        config.response_schema = provider_schema(LocalizedOverlays.model_json_schema())
        localization = """Locate ONLY real streamer webcam boxes and creator/channel logos or
readable channel names in these full-frame images. Return tight bounding boxes in standard
box_2d=[ymin,xmin,ymax,xmax], integers normalized 0..1000 relative to the FULL image height/width.
Camera box includes the room and camera border, but not gameplay below it. Do not infer names
from initials. FiveM (b2802), game HUD and game characters are not creator overlays.
visible_text must be literal letters visible inside that box, otherwise empty.
Output only regions actually visible in these images. If an overlay moves between images,
return its union rectangle. Include every separate creator logo, not only the camera.
"""
        response = director._generate_content_with_retry(client, model, [*stills, localization], config)
        localized = LocalizedOverlays.model_validate(json.loads(response.text))
        regions = []
        for region in localized.regions:
            box = region.box_2d
            if len(box) != 4 or not all(0 <= coordinate <= 1000 for coordinate in box):
                raise ValueError("Invalid creator-overlay localization; rendering stopped.")
            top, left, bottom, right = box
            regions.append(CreatorOverlayRegion(
                kind=region.kind, label=region.visible_text, x=left/1000, y=top/1000,
                width=(right-left)/1000, height=(bottom-top)/1000,
            ))
        if any("cam" in r.kind for r in result.regions) and not any(r.kind == "facecam" for r in regions):
            raise ValueError("Detected camera could not be localized; refusing to expose it.")
        corner = WatermarkCorner.NONE
        if regions:
            anchor = next((r for r in regions if r.kind == "facecam"), regions[0])
            vertical = "top" if anchor.y + anchor.height/2 < .5 else "bottom"
            horizontal = "left" if anchor.x + anchor.width/2 < .5 else "right"
            corner = WatermarkCorner(f"{vertical}_{horizontal}")
        return WatermarkInfo(detected=bool(regions), corner=corner, regions=regions)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        for remote in remote_files:
            try:
                client.files.delete(name=remote.name)
            except Exception:
                pass
