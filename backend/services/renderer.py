import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable

from backend.config import RENDERS_DIR, ASSETS_DIR, HARDWARE
from backend.services.comparison import FPS, ComparisonTimeline
from backend.services.comparison_motion import COMPARISON_ASSETS, panel_logo_overlay, pop_audio_filters

logger = logging.getLogger("gta6-studio.renderer")

def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Two-level escaping for file paths passed to FFmpeg libass filter options."""
    s = str(path).replace("\\", "/")
    # Level 2 (filter option parser)
    s = s.replace("'", "\\'").replace(":", "\\:")
    # Level 1 (filtergraph parser)
    for ch in ("\\", "'", ":", "[", "]", ",", ";", " "):
        s = s.replace(ch, f"\\{ch}")
    return s


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

    @staticmethod
    def _strip_emojis(text: str) -> str:
        """Removes color emojis and non-glyph pictographs that render as tofu boxes in Pillow TTF fonts."""
        import re
        cleaned = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe00-\ufe0f\u200d]+", " ", str(text or ""))
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

    def _ensure_badge_png(self, game_label: str = "GTA VI") -> Path:
        """Generates or loads sleek metallic glassmorphism corner badge for detected game"""
        import re
        clean_label = self._strip_emojis(game_label).upper() or "GTA VI"
        safe_key = re.sub(r"[^a-z0-9]+", "_", clean_label.lower()).strip("_") or "gta_vi"
        badge_path = self.assets_dir / f"badge_cover_{safe_key}.png"
        if badge_path.exists():
            return badge_path
        try:
            from PIL import Image, ImageDraw
            font = _get_font(["impact.ttf", "Impact.ttf", "Arial Bold.ttf", "arialbd.ttf"], 26)
            font_sub = _get_font(["arialbd.ttf", "Arial Bold.ttf", "arial.ttf"], 13)
            tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            lbl_box = tmp_draw.textbbox((0, 0), clean_label, font=font)
            sub_text = "• 4K 60FPS"
            sub_box = tmp_draw.textbbox((0, 0), sub_text, font=font_sub)
            lbl_w = lbl_box[2] - lbl_box[0]
            sub_w = sub_box[2] - sub_box[0]
            w = max(230, 26 + lbl_w + 14 + sub_w + 20)
            h = 52
            badge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(badge)
            draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=12, fill=(18, 16, 28, 240), outline=(238, 77, 160, 200), width=2)
            draw.line([14, 10, 14, h - 10], fill=(238, 77, 160, 255), width=3)
            draw.text((26, 11), clean_label, fill=(255, 255, 255), font=font)
            draw.text((26 + lbl_w + 14, 17), sub_text, fill=(0, 255, 230), font=font_sub)
            badge.save(str(badge_path))
        except Exception as e:
            logger.warning(f"Could not generate badge PNG: {e}")
        return badge_path

    def write_comparison_title(self, title: str, path: Path) -> None:
        """Draw the fixed race graphic, with the last word accented on black."""
        from PIL import Image, ImageDraw

        headline = " ".join(self._strip_emojis(title).upper().split())
        game = r"GTA\s*(?:VI|IV|V|[456]|FOUR|FIVE|SIX)"
        matchup = rf"{game}\s+(?:VS\.?|VERSUS)\s+{game}"
        # The panel logos already identify the games. Keep the topic and punctuation.
        topic = re.sub(rf"\s+(?:IN\s+)?{matchup}([?!.]?)$", r"\1", headline)
        topic = re.sub(rf"^{matchup}\s*[•:|–—-]\s*", "", topic)
        words = (topic or "GAME COMPARISON").split()
        lead, accent = " ".join(words[:-1]), words[-1]
        if not lead:
            lead, accent = accent, ""

        fonts = ["DIN Condensed Bold.ttf", "Impact.ttf", "DejaVuSansCondensed-Bold.ttf", "DejaVuSans-Bold.ttf"]
        accent_width = min(345, max(212, round(_get_font(fonts, 73).getlength(accent[:80])) + 38))
        split = 756 - accent_width if accent else 728
        tile = Image.new("RGBA", (808, 87))
        draw = ImageDraw.Draw(tile)
        draw.rectangle((0, 0, 755, 86), fill="#14171b")
        draw.rectangle((0, 0, split - 1, 86), fill="#ddfb47")
        for left, right in ((763, 773), (783, 788)):
            draw.rectangle((left, 0, right, 86), fill="#ddfb47")

        for text, x, limit, size, fill in (
            (lead, 17, split - 34, 66, "#151719"),
            (accent, split + 19, 756 - split - 32, 73, "#ffffff"),
        ):
            if not text:
                continue
            # Only shorten text when it would otherwise collide at the smallest size.
            if len(text) > 160:
                text = text[:159].rstrip() + "…"
            font = _get_font(fonts, size)
            while size > 36 and font.getlength(text) > limit:
                size -= 2
                font = _get_font(fonts, size)
            y = 44
            if x == 17 and font.getlength(text) > limit and " " in text:
                # A longer question gets two lines inside the same plate.
                font = _get_font(fonts, 33)
                first_line = ""
                for word in text.split():
                    candidate = f"{first_line} {word}".strip()
                    if font.getlength(candidate) > limit:
                        break
                    first_line = candidate
                if first_line:
                    draw.text((x, 23), first_line, font=font, anchor="lm", fill=fill)
                    text = text[len(first_line):].lstrip()
                    y = 61
            if font.getlength(text) > limit:
                prefix = text
                while prefix and font.getlength(prefix + "…") > limit:
                    prefix = prefix[:-1]
                text = prefix.rstrip() + "…"
            draw.text((x, y), text, font=font, anchor="lm", fill=fill)
        # Shear text and stripes together, keeping both angled ends on the canvas.
        tile.transform(tile.size, Image.Transform.AFFINE, (1, 0.1944, -17, 0, 1, 0),
                       resample=Image.Resampling.BICUBIC).save(path)

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

            # Category pill tag (strip emojis cleanly so Pillow TTF fonts never render tofu boxes)
            tag_text = self._strip_emojis(category_tag).upper() or "GAMEPLAY • HIGHLIGHT"
            font_tag = _get_font(["arialbd.ttf", "Arial Bold.ttf", "arial.ttf"], 13)

            tag_bbox = draw.textbbox((0, 0), tag_text, font=font_tag)
            tag_w = (tag_bbox[2] - tag_bbox[0]) + 24
            draw.rounded_rectangle([30, 14, 30 + tag_w, 42], radius=6, fill=(238, 77, 160, 50), outline=(238, 77, 160, 180), width=1)
            draw.text((42, 20), tag_text, fill=(255, 120, 200), font=font_tag)

            # Main headline text (clean, uppercase, fitted inside 880px card width)
            headline = self._strip_emojis(hook_text).upper() or "HIGHLIGHT MOMENT!"
            if not any(headline.endswith(p) for p in ("!", "?", ".")):
                headline += "!"

            max_text_w = w - 64
            font_size = 44
            font_main = _get_font(["impact.ttf", "Impact.ttf", "arialbd.ttf"], font_size)
            while font_size > 20:
                font_main = _get_font(["impact.ttf", "Impact.ttf", "arialbd.ttf"], font_size)
                hb = draw.textbbox((0, 0), headline, font=font_main)
                if (hb[2] - hb[0]) <= max_text_w:
                    break
                font_size -= 2

            # Truncate gracefully with ellipsis if still wider than banner at min font size
            hb = draw.textbbox((0, 0), headline, font=font_main)
            while (hb[2] - hb[0]) > max_text_w and len(headline) > 10:
                headline = headline[:-4].rstrip() + "..."
                hb = draw.textbbox((0, 0), headline, font=font_main)

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
        badge_label: str = "GTA VI",
        topic_banner_y: int = 260,
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

        # 0.5. Top Topic Headline Banner (centered in top zone cleanly without covering streamer eyes)
        if topic_banner_path and topic_banner_path.exists():
            inputs.extend(["-i", str(topic_banner_path)])
            banner_idx = len(inputs) // 2 - 1
            filter_chain.append(f"[{v_stream}][{banner_idx}:v]overlay=(W-w)/2:{int(topic_banner_y)}[v_head]")
            v_stream = "v_head"
            logger.info(f"Overlaid top topic headline banner at (W-w)/2:{int(topic_banner_y)}")

        # 1. Callout PNG overlay sticker has been removed per user requirement
        # (prevents temporary blue box popup during 0s-3.5s at the start of clips)

        # 1.5. Dynamic AI Watermark / Creator Tag Masker Badge
        corner_norm = ""
        if watermark_corner is not None:
            raw_corner = getattr(watermark_corner, "value", str(watermark_corner))
            corner_norm = str(raw_corner).split(".")[-1].strip().lower()
        if corner_norm and corner_norm not in ("none", "null", ""):
            badge_png = self._ensure_badge_png(badge_label)
            if badge_png.exists():
                inputs.extend(["-i", str(badge_png)])
                badge_idx = len(inputs) // 2 - 1
                corner_key = corner_norm
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
            escaped_ass = _escape_ffmpeg_filter_path(ass_subtitles_path)
            filter_chain.append(f"[{v_stream}]ass={escaped_ass}[v_out]")
            v_stream = "v_out"

        # 3. Master audio to YouTube Shorts / Reels -14 LUFS standard
        filter_chain.append("[1:a]loudnorm=I=-14:LRA=11:TP=-1.5[a_master]")

        # Assemble full command
        cmd = ["ffmpeg", "-y", *inputs]

        video_map = "0:v" if v_stream == "0:v" else f"[{v_stream}]"
        if filter_chain:
            full_filter = ";".join(filter_chain)
            cmd.extend(["-filter_complex", full_filter, "-map", video_map, "-map", "[a_master]"])
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
                cpu_cmd.extend(["-filter_complex", full_filter, "-map", video_map, "-map", "[a_master]"])
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

    # --------------------------------------------------------------------------
    # Comparison compositor
    # --------------------------------------------------------------------------
    def render_comparison_clip(
        self,
        base_video_path: Path,
        gta6_video_path: Path,
        mixed_audio_path: Path,
        output_path: Path,
        comparison_format: str = "shorts_split",
        base_game: str = "gta5",
        ass_subtitles_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        timeline: Optional[ComparisonTimeline] = None,
        logo_frames: tuple[int | None, int | None] = (None, None),
        logo_movies: Optional[dict[str, Path]] = None,
        slide_frame: int = 0,
        title_path: Optional[Path] = None,
    ) -> Path:
        """
        Renders side-by-side or top/bottom comparison video:
        - shorts_split: 1080x1920 (Top: Base Game, Bottom: GTA 6 with centered VS badge)
        - long_side_by_side: 1920x1080 (Left: Base Game, Right: GTA 6 with vertical center VS badge)
        """
        if progress_callback:
            progress_callback(30, f"Compositing comparison video ({comparison_format})...")

        logo_dir = COMPARISON_ASSETS
        vs_badge_path = logo_dir / "vs-silver.png"
        base_badge_path = logo_dir / {"gta4": "gta4.png", "gta5": "gta5.png"}[base_game]
        gta6_badge_path = logo_dir / "gta6.png"

        logo_movies = logo_movies or {}
        inputs = [
            "-i", str(base_video_path),
            "-i", str(gta6_video_path),
            "-i", str(vs_badge_path),
            "-i", str(logo_movies.get(base_game, base_badge_path)),
            "-i", str(logo_movies.get("gta6", gta6_badge_path)),
            "-i", str(mixed_audio_path)
        ]

        # Input indexes:
        # 0 = Base game video
        # 1 = GTA 6 video
        # 2 = VS badge PNG
        # 3 = Base game badge PNG
        # 4 = GTA 6 badge PNG
        # 5 = Mixed audio

        landscape = comparison_format == "long_side_by_side"
        panel = "960:1080" if landscape else "1080:960"
        stack = "hstack" if landscape else "vstack"
        second_logo_x = "W-w-30" if landscape else "30"
        fill_panel = f"setpts=PTS-STARTPTS,fps=60,scale={panel}:force_original_aspect_ratio=increase,crop={panel},setsar=1"
        filter_chain = timeline.video_filters() if timeline else []
        older_input, gta6_input = ("older_playback", "six_playback") if timeline else ("0:v", "1:v")
        filter_chain.extend([
            f"[{older_input}]{fill_panel}[base]",
            # Clear the top-edge HUD that would otherwise sit behind the center mark.
            f"[{gta6_input}]crop=iw:trunc(ih*0.95/2)*2:0:ih-oh,{fill_panel}[six]",
        ])
        from PIL import Image
        for panel_name, index, game, logo, end_x, end_y, frame in (
            ("base", 3, base_game, base_badge_path, "30", "30", logo_frames[0]),
            ("six", 4, "gta6", gta6_badge_path, second_logo_x, "30", logo_frames[1]),
        ):
            with Image.open(logo) as artwork:
                logo_size = artwork.size
            filter_chain.extend(panel_logo_overlay(
                panel_name, index, f"{panel_name}_labeled", end_x, end_y,
                logo_size, frame if game in logo_movies else None, slide_frame,
            ))
        filter_chain.extend([
            f"[base_labeled][six_labeled]{stack}=inputs=2:shortest=1[stacked]",
            "[stacked][2:v]overlay=(W-w)/2:(H-h)/2[v_staged]",
        ])
        v_curr = "v_staged"
        if title_path is not None:
            inputs.extend(["-i", str(title_path)])
            title_x = "(W-w)/2" if landscape else "230"
            hook_frames = timeline.hook if timeline else 3 * FPS
            fade_frames = min(15, hook_frames)
            filter_chain.extend([
                f"[6:v]format=rgba,settb=1/{FPS},loop=loop=-1:size=1:start=0,trim=end_frame={hook_frames},"
                f"setpts=N/({FPS}*TB),fade=t=out:s={hook_frames - fade_frames}:n={fade_frames}:alpha=1[title]",
                f"[{v_curr}][title]overlay={title_x}:38:eof_action=pass:enable='lt(n,{hook_frames})'[v_title]",
            ])
            v_curr = "v_title"
        if ass_subtitles_path and ass_subtitles_path.exists():
            escaped_ass = _escape_ffmpeg_filter_path(ass_subtitles_path)
            filter_chain.append(f"[{v_curr}]ass={escaped_ass}[v_subbed]")
            v_curr = "v_subbed"

        pop_filters, audio_input = pop_audio_filters(logo_frames)
        filter_chain.extend(pop_filters)
        filter_chain.append(f"{audio_input}loudnorm=I=-14:LRA=11:TP=-1.5[a_master]")

        full_filter = ";".join(filter_chain)
        codec = HARDWARE.ffmpeg_codec
        encoder_args = HARDWARE.encoder_args

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", full_filter,
            "-map", f"[{v_curr}]",
            "-map", "[a_master]",
            "-c:v", codec,
            *encoder_args,
            "-fps_mode", "cfr",
            "-r", "60",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path)
        ]

        if progress_callback:
            progress_callback(70, f"Hardware encoding comparison {output_path.name}...")

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.warning(f"Hardware comparison render failed ({res.stderr[:200]}). Falling back to CPU libx264...")
            cpu_cmd = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", full_filter,
                "-map", f"[{v_curr}]",
                "-map", "[a_master]",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "48000",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(output_path)
            ]
            subprocess.run(cpu_cmd, check=True)

        logger.info(f"Comparison video rendered successfully: {output_path}")
        return output_path

video_renderer = VideoRenderer()
