import os
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable

from backend.config import RENDERS_DIR, ASSETS_DIR, HARDWARE

logger = logging.getLogger("gta6-studio.renderer")

def _get_font(font_names, size: int):
    from PIL import ImageFont
    if isinstance(font_names, str):
        font_names = [font_names]
    for name in font_names:
        candidates = [
            name,
            f"C:/Windows/Fonts/{name}",
            f"/System/Library/Fonts/Supplemental/{name}",
            f"/System/Library/Fonts/{name}",
            f"/usr/share/fonts/truetype/{name}",
        ]
        for c in candidates:
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()

class VideoRenderer:
    def __init__(self):
        self.renders_dir = RENDERS_DIR
        self.assets_dir = ASSETS_DIR

    def _ensure_badge_png(self) -> Path:
        """Generates or loads sleek GTA VI Vice City metallic glassmorphism corner badge"""
        badge_path = self.assets_dir / "gta6_badge.png"
        if badge_path.exists():
            return badge_path
        try:
            from PIL import Image, ImageDraw
            w, h = 240, 52
            badge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(badge)
            draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=(18, 16, 28, 240), outline=(238, 77, 160, 200), width=2)
            draw.line([14, 10, 14, h - 10], fill=(238, 77, 160, 255), width=3)
            font = _get_font(["impact.ttf", "Impact.ttf", "Arial Bold.ttf", "arialbd.ttf"], 26)
            font_sub = _get_font(["arialbd.ttf", "Arial Bold.ttf", "arial.ttf"], 13)
            draw.text((26, 11), "GTA VI", fill=(255, 255, 255), font=font)
            draw.text((115, 17), "• 4K 60FPS", fill=(0, 255, 230), font=font_sub)
            badge.save(str(badge_path))
        except Exception as e:
            logger.warning(f"Could not generate badge PNG: {e}")
        return badge_path

    def generate_topic_banner(
        self,
        hook_text: str,
        job_id: str,
        clip_id: str,
        category_tag: str = "GTA 6 • NEW MISSION"
    ) -> Path:
        """
        Creates an attractive glassmorphic topic headline card for the top blurred zone (880x140).
        """
        banner_path = self.assets_dir / f"{job_id}_{clip_id}_topic_banner.png"
        try:
            from PIL import Image, ImageDraw
            w, h = 880, 140
            banner = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(banner)

            # Frosted glass card with Vice City neon magenta outline
            draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=20, fill=(12, 10, 22, 225), outline=(238, 77, 160, 220), width=3)

            # Category pill tag
            tag_text = f"🔥 {category_tag.upper()}" if not category_tag.startswith("🔥") else category_tag.upper()
            font_tag = _get_font(["arialbd.ttf", "Arial Bold.ttf", "arial.ttf"], 13)

            tag_bbox = draw.textbbox((0, 0), tag_text, font=font_tag)
            tag_w = (tag_bbox[2] - tag_bbox[0]) + 24
            draw.rounded_rectangle([30, 14, 30 + tag_w, 42], radius=6, fill=(238, 77, 160, 50), outline=(238, 77, 160, 180), width=1)
            draw.text((42, 20), tag_text, fill=(255, 120, 200), font=font_tag)

            # Main headline text (clean, uppercase, trimmed if needed)
            headline = hook_text.strip().upper()
            if not any(headline.endswith(p) for p in ("!", "?", ".", "🔥", "🚨")):
                headline += " 🚨"

            # Dynamically choose font size so text never overflows 880px
            font_size = 44
            if len(headline) > 34:
                font_size = 32
            elif len(headline) > 28:
                font_size = 38

            font_main = _get_font(["impact.ttf", "Impact.ttf", "arialbd.ttf"], font_size)

            draw.text((32, 54 + (44 - font_size) // 2), headline, fill=(255, 255, 255), font=font_main)
            banner.save(str(banner_path))
            logger.info(f"Generated top topic banner for {clip_id}: {banner_path}")
        except Exception as e:
            logger.warning(f"Could not generate topic banner: {e}")
        return banner_path

    def render_final_clip(
        self,
        cropped_video_path: Path,
        mixed_audio_path: Path,
        ass_subtitles_path: Optional[Path],
        overlay_png_path: Optional[Path],
        job_id: str,
        clip_id: str,
        watermark_corner: Optional[str] = None,
        topic_banner_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Executes hardware-accelerated (VideoToolbox / NVENC) final burn-in render,
        compositing 9:16 vertical video, callout PNG sticker, ducked audio,
        and styled ASS captions into a 1080x1920 60fps MP4.
        """
        if progress_callback:
            progress_callback(60, f"Hardware rendering final 9:16 vertical short ({clip_id})...")

        final_mp4_path = self.renders_dir / f"{job_id}_{clip_id}_final.mp4"
        logger.info(f"Rendering final short short to {final_mp4_path} using {HARDWARE.ffmpeg_codec}...")

        codec = HARDWARE.ffmpeg_codec
        encoder_args = HARDWARE.encoder_args

        # Build compositing filtergraph
        # Inputs:
        # [0:v] = 9:16 cropped video
        # [1:a] = mixed audio
        # Optional: overlay png and ass subtitles
        inputs = ["-i", str(cropped_video_path), "-i", str(mixed_audio_path)]
        v_stream = "0:v"

        filter_chain = []

        # 0.5. Top Topic Headline Banner (centered in top blurred area at Y=260)
        if topic_banner_path and topic_banner_path.exists():
            inputs.extend(["-i", str(topic_banner_path)])
            banner_idx = len(inputs) // 2 - 1
            filter_chain.append(f"[{v_stream}][{banner_idx}:v]overlay=(W-w)/2:260[v_head]")
            v_stream = "v_head"
            logger.info("Overlaid top topic headline banner at (W-w)/2:260")

        # 1. Callout PNG overlay sticker has been removed per user requirement
        # (prevents temporary blue box popup during 0s-3.5s at the start of clips)

        # 1.5. Dynamic AI Watermark / Creator Tag Masker Badge
        if watermark_corner and str(watermark_corner).lower() not in ("none", "null", ""):
            badge_png = self._ensure_badge_png()
            if badge_png.exists():
                inputs.extend(["-i", str(badge_png)])
                badge_idx = len(inputs) // 2 - 1
                corner_key = str(watermark_corner).lower()
                # Canvas 1080x1920 with centered 16:9 gameplay (Y=656..1264)
                if "bottom_right" in corner_key or corner_key == "br":
                    pos_expr = "W-w-20:1264-h-14"
                elif "bottom_left" in corner_key or corner_key == "bl":
                    pos_expr = "20:1264-h-14"
                elif "top_right" in corner_key or corner_key == "tr":
                    pos_expr = "W-w-20:656+14"
                elif "top_left" in corner_key or corner_key == "tl":
                    pos_expr = "20:656+14"
                else:
                    pos_expr = "W-w-20:1264-h-14"

                filter_chain.append(f"[{v_stream}][{badge_idx}:v]overlay={pos_expr}[v_badged]")
                v_stream = "v_badged"
                logger.info(f"Burned AI watermark concealment badge over corner '{corner_key}' at overlay={pos_expr}")

        # 2. Burn-in styled ASS subtitles
        if ass_subtitles_path and ass_subtitles_path.exists():
            # Escape path for FFmpeg filter
            escaped_ass = str(ass_subtitles_path).replace("\\", "/").replace(":", "\\:")
            filter_chain.append(f"[{v_stream}]ass='{escaped_ass}'[v_out]")
            v_stream = "v_out"

        # 3. Master audio to YouTube Shorts / Reels -14 LUFS standard
        filter_chain.append("[1:a]loudnorm=I=-14:LRA=11:TP=-1.5[a_master]")

        # Assemble full command
        cmd = ["ffmpeg", "-y", *inputs]

        if filter_chain:
            full_filter = ";".join(filter_chain)
            cmd.extend(["-filter_complex", full_filter, "-map", f"[{v_stream}]", "-map", "[a_master]"])
        else:
            cmd.extend(["-map", "0:v", "-map", "1:a"])

        cmd.extend([
            "-c:v", codec,
            *encoder_args,
            "-fps_mode", "cfr",
            "-r", "60",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-pix_fmt", "yuv420p",
            "-brand", "mp42",
            "-use_editlist", "0",
            "-movflags", "+faststart",
            str(final_mp4_path)
        ])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.warning(f"Hardware burn-in failed ({result.stderr[:200]}). Falling back to CPU libx264.")
            # Fallback CPU command
            cpu_cmd = ["ffmpeg", "-y", *inputs]
            if filter_chain:
                cpu_cmd.extend(["-filter_complex", full_filter, "-map", f"[{v_stream}]", "-map", "[a_master]"])
            else:
                cpu_cmd.extend(["-map", "0:v", "-map", "1:a"])
            cpu_cmd.extend([
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-profile:v", "high",
                "-level", "4.2",
                "-g", "60",
                "-bf", "2",
                "-flags", "+cgop",
                "-fps_mode", "cfr",
                "-r", "60",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-colorspace", "bt709",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-pix_fmt", "yuv420p",
                "-brand", "mp42",
                "-use_editlist", "0",
                "-movflags", "+faststart",
                str(final_mp4_path)
            ])
            subprocess.run(cpu_cmd, check=True)

        logger.info(f"Final clip rendered successfully: {final_mp4_path} ({final_mp4_path.stat().st_size / (1024*1024):.2f} MB)")
        return final_mp4_path

video_renderer = VideoRenderer()
