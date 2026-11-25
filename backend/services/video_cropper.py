import os
import gc
import math
import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import cv2
import numpy as np

from backend.config import TEMP_DIR, HARDWARE
from backend.schemas import CropMode, CreatorOverlayRegion
from backend.services.creator_inpainter import creator_inpainter

logger = logging.getLogger("gta6-studio.cropper")


def creator_mask_rectangles(regions: List[CreatorOverlayRegion], width: int, height: int) -> List[Tuple[int, int, int, int]]:
    """Source-coordinate reconstruction masks, including camera borders and antialiasing."""
    rectangles = []
    for item in regions:
        region = CreatorOverlayRegion.model_validate(item)
        x = max(0, math.floor(region.x * width) - 8)
        y = max(0, math.floor(region.y * height) - 8)
        right = min(width, math.ceil((region.x + region.width) * width) + 8)
        bottom = min(height, math.ceil((region.y + region.height) * height) + 8)
        if "cam" in region.kind:
            # Corner cameras reach the source edge. Close small localization gaps so
            # the outer camera strip cannot survive behind a seemingly complete cover.
            if region.x <= .05:
                x = 0
            if region.y <= .05:
                y = 0
            if region.x + region.width >= .95:
                right = width
            if region.y + region.height >= .95:
                bottom = height
        rectangles.append((x, y, right-x, bottom-y))
    return rectangles


class VideoCropper:
    def __init__(self):
        self.temp_dir = TEMP_DIR
        self._yolo_model = None

    def _get_yolo(self):
        """Lazy load YOLO model to keep initial startup instantaneous"""
        if self._yolo_model is None:
            from ultralytics import YOLO
            # Lightweight YOLO11 nano (<500MB memory footprint)
            self._yolo_model = YOLO("yolo11n.pt")
        return self._yolo_model

    def _get_video_metadata(self, video_path: Path) -> dict:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return {"width": 1920, "height": 1080}
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return {"width": w if w > 0 else 1920, "height": h if h > 0 else 1080}

    def calculate_action_track_x(
        self,
        video_segment_path: Path,
        sample_interval: int = 5
    ) -> int:
        """
        Samples frames from video segment, runs YOLO to track people, cars,
        and action centers, and returns an exponentially smoothed crop X coordinate.
        """
        cap = cv2.VideoCapture(str(video_segment_path))
        if not cap.isOpened():
            return (1920 - 608) // 2  # Default center

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        crop_w = int(height * (9 / 16))  # 608 for 1080p
        max_x = width - crop_w

        centers: List[float] = []
        frame_idx = 0

        try:
            model = self._get_yolo()
            # Action classes: person (0), car (2), motorcycle (3), airplane (4), bus (5), truck (7)
            action_classes = [0, 2, 3, 4, 5, 7]

            while cap.isOpened() and frame_idx < 150:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % sample_interval == 0:
                    results = model(frame, classes=action_classes, verbose=False)
                    if results and len(results[0].boxes) > 0:
                        boxes = results[0].boxes.xywh.cpu().numpy()
                        # Exclude corner streamer webcams from gameplay centering
                        gameplay_boxes = [
                            b for b in boxes
                            if not ((b[0] > 0.72 * width or b[0] < 0.28 * width) and (b[1] < 0.35 * height or b[1] > 0.65 * height))
                        ]
                        target_boxes = gameplay_boxes if gameplay_boxes else boxes
                        # Sort by area (w * h)
                        largest_box = max(target_boxes, key=lambda b: b[2] * b[3])
                        centers.append(float(largest_box[0]))
                    else:
                        centers.append(width / 2.0)

                frame_idx += 1
        except Exception as e:
            logger.warning(f"YOLO action tracking warning ({e}). Using center default.")
            centers.append(width / 2.0)
        finally:
            cap.release()
            # Cleanup
            if HARDWARE.is_cuda:
                import torch
                torch.cuda.empty_cache()
            gc.collect()

        if not centers:
            return max_x // 2

        # Calculate median of detected centers for stable framing
        median_center = float(np.median(centers))
        # Center the crop window on the action center
        crop_x = int(median_center - (crop_w / 2))
        # Clamp within valid bounds [0, max_x]
        return max(0, min(crop_x, max_x))

    def detect_streamer_fullscreen_intro(
        self,
        video_path: Path,
        max_scan_sec: float = 120.0,
        sample_interval_sec: float = 2.0
    ) -> float:
        """
        Scans opening minutes of video using YOLO to detect if streamer is
        occupying full screen (talking head/intro) instead of playing game.
        Returns the timestamp (seconds) where pure gameplay begins.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return 0.0

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        total_duration = total_frames / fps if fps > 0 else 0.0

        scan_duration = min(total_duration, max_scan_sec)
        if scan_duration < 10.0:
            cap.release()
            return 0.0

        intro_end_sec = 0.0
        step_frames = max(1, int(fps * sample_interval_sec))

        try:
            model = self._get_yolo()
            current_frame = 0
            max_frame = int(scan_duration * fps)

            consecutive_hits = 0
            while current_frame < max_frame:
                cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                ret, frame = cap.read()
                if not ret:
                    break

                results = model(frame, classes=[0], verbose=False)
                has_fullscreen_human = False

                if results and len(results[0].boxes) > 0:
                    boxes = results[0].boxes.xywh.cpu().numpy()
                    for b in boxes:
                        box_w, box_h = b[2], b[3]
                        box_area = (box_w * box_h) / (width * height)
                        # Strict webcam talking-head threshold (>42% frame area & >55% height)
                        # avoids false-positives on 3rd-person gameplay protagonists (~20-30% area).
                        if box_area > 0.42 and box_w > (0.40 * width) and box_h > (0.55 * height):
                            has_fullscreen_human = True
                            break

                sec = current_frame / fps
                if has_fullscreen_human:
                    consecutive_hits += 1
                    # Genuine streamer intros start in the opening ~16s and hold for >=6s (3+ hits)
                    if consecutive_hits >= 3 and (sec - (consecutive_hits - 1) * sample_interval_sec) <= 16.0:
                        intro_end_sec = sec + sample_interval_sec
                else:
                    consecutive_hits = 0
                    if intro_end_sec > 0 and (sec - intro_end_sec) > 6.0:
                        # Gameplay confirmed for several consecutive checks
                        break
                    if sec > 16.0 and intro_end_sec == 0.0:
                        # No opening streamer intro found; avoid false-positives on later cutscene close-ups
                        break

                current_frame += step_frames

        except Exception as e:
            logger.warning(f"Error checking streamer intro: {e}")
        finally:
            cap.release()
            if HARDWARE.is_cuda:
                import torch
                torch.cuda.empty_cache()
            gc.collect()

        if intro_end_sec > 0:
            logger.info(f"YOLO detected full-screen streamer intro ending at {intro_end_sec:.1f}s.")
        return intro_end_sec

    def _detect_facecam_crop_box(
        self,
        raw_video_path: Path,
        start_time: float,
        duration: float,
        webcam_corner: str,
        v_width: int,
        v_height: int,
    ) -> tuple[int, int, int, int]:
        """
        Finds the tight 1080:672 crop rectangle (w, h, x, y) enclosing the corner webcam
        via YOLO person detection so zero background gameplay leaks into FACECAM_SPLIT.
        """
        ratio = 1080.0 / 672.0
        corner_lc = str(webcam_corner or "top_right").lower()
        cw = max(2, min(v_width & ~1, int(v_width * 0.18) & ~1))
        ch = max(2, min(v_height & ~1, int(round(cw / ratio)) & ~1))
        pad_x = max(2, int(v_width * 0.014))
        pad_y = max(2, int(v_height * 0.085))
        tx = max(0, v_width - cw - pad_x) if "right" in corner_lc else min(pad_x, max(0, v_width - cw))
        ty = max(0, v_height - ch - pad_y) if "bottom" in corner_lc else min(pad_y, max(0, v_height - ch))

        try:
            cap = cv2.VideoCapture(str(raw_video_path))
            if cap.isOpened():
                sample_ms = max(0.0, (float(start_time) + min(2.0, max(0.2, float(duration) * 0.35))) * 1000.0)
                cap.set(cv2.CAP_PROP_POS_MSEC, sample_ms)
                ok, frame = cap.read()
                cap.release()
                if ok and frame is not None and v_width >= 640 and v_height >= 360:
                    rx1 = int(v_width * 0.65) if "right" in corner_lc else 0
                    rx2 = v_width if "right" in corner_lc else int(v_width * 0.35)
                    ry1 = int(v_height * 0.62) if "bottom" in corner_lc else 0
                    ry2 = v_height if "bottom" in corner_lc else int(v_height * 0.38)
                    roi = frame[ry1:ry2, rx1:rx2]
                    model = self._get_yolo()
                    res = model.predict(roi, classes=[0], conf=0.25, verbose=False)
                    if res and len(res[0].boxes) > 0:
                        best = max(res[0].boxes, key=lambda b: float(b.conf[0]))
                        bx1, by1, bx2, by2 = best.xyxy[0].tolist()
                        px1, py1, px2, py2 = rx1 + bx1, ry1 + by1, rx1 + bx2, ry1 + by2
                        pw, ph = max(20.0, px2 - px1), max(20.0, py2 - py1)
                        cx = (px1 + px2) / 2.0
                        cw = max(
                            int(v_width * 0.155),
                            min(int(v_width * 0.205), int(pw * 1.24)),
                        ) & ~1
                        cw = max(2, min(v_width & ~1, cw))
                        ch = max(2, min(v_height & ~1, int(round(cw / ratio)) & ~1))
                        tx_raw = int(round(cx - cw / 2.0))
                        tx = max(pad_x, min(tx_raw, max(0, v_width - cw - pad_x)))
                        ty_raw = int(round(py1 - ph * 0.08))
                        ty = max(4, min(ty_raw, max(0, v_height - ch - 4)))
                        logger.info(
                            f"YOLO locked FACECAM_SPLIT box for corner='{corner_lc}': "
                            f"{cw}x{ch}@{tx & ~1},{ty & ~1}"
                        )
        except Exception as ex:
            logger.warning(f"YOLO facecam lock skipped ({ex}); using corner fallback.")

        return cw & ~1, ch & ~1, (tx & ~1), (ty & ~1)

    def crop_to_vertical(
        self,
        raw_video_path: Path,
        start_time: float,
        duration: float,
        output_cropped_path: Path,
        mode: CropMode = CropMode.ACTION_TRACK,
        mask_webcam: bool = True,
        webcam_corner: str = "top_right",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        creator_regions: Optional[List[CreatorOverlayRegion]] = None,
    ) -> Path:
        """
        Converts 16:9 gameplay to 1080x1920 (9:16) vertical using:
        - action_track: YOLO-guided panning that isolates gameplay and completely crops out streamer webcams
        - facecam_split: Top 35% streamer facecam / Bottom 65% gameplay
        - center_zoom: Cinematic center crop with blurred background fill & frosted webcam concealment
        """
        if progress_callback:
            progress_callback(30, f"Applying 9:16 vertical crop ({mode.value})...")

        logger.info(f"Cropping video segment: {raw_video_path} [{start_time}s -> +{duration}s] Mode: {mode}")

        # Codec arguments based on hardware
        codec = HARDWARE.ffmpeg_codec
        encoder_args = HARDWARE.encoder_args

        # Get exact source dimensions
        meta = self._get_video_metadata(raw_video_path)
        v_width = meta.get("width", 1920)
        v_height = meta.get("height", 1080)

        regions = list(creator_regions or [])
        if mask_webcam and not regions:
            # Compatibility for direct callers with only an old corner hint.
            corner = webcam_corner.lower()
            regions = [CreatorOverlayRegion(
                kind="facecam", x=0 if "left" in corner else .66,
                y=.58 if "bottom" in corner else 0, width=.34, height=.42,
            )]
        rectangles = creator_mask_rectangles(regions, v_width, v_height)
        reconstructed_path = None
        if rectangles:
            stat = raw_video_path.stat()
            signature = json.dumps([str(raw_video_path.resolve()), stat.st_size, stat.st_mtime_ns,
                                    start_time, duration, rectangles, "lama512-30fps-v1"])
            key = hashlib.sha256(signature.encode()).hexdigest()[:24]
            cache_dir = self.temp_dir / "creator_inpaint_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            reconstructed_path = cache_dir / f"{key}.mp4"
            if not reconstructed_path.exists() or reconstructed_path.stat().st_size < 1000:
                creator_inpainter.reconstruct_segment(
                    raw_video_path, start_time, duration, rectangles, reconstructed_path, progress_callback,
                )
            raw_video_path = reconstructed_path
            start_time = 0.0
        # A dedicated facecam panel would enlarge the hidden camera. Use gameplay framing instead.
        if rectangles and mode == CropMode.FACECAM_SPLIT:
            mode = CropMode.CENTER_ZOOM

        filter_args = []

        if mode == CropMode.ACTION_TRACK:
            # Extract temporary segment to sample with YOLO
            temp_segment = self.temp_dir / f"sample_{output_cropped_path.stem}.mp4"
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(min(duration, 10.0)),
                "-i", str(raw_video_path),
                "-c", "copy",
                str(temp_segment)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            crop_x = self.calculate_action_track_x(temp_segment)
            temp_segment.unlink(missing_ok=True)

            # Dynamic 9:16 crop calculation based on actual video dimensions
            crop_w = int(v_height * (9 / 16))
            crop_w = crop_w - (crop_w % 2)
            crop_x = max(0, min(crop_x, v_width - crop_w))
            crop_x = crop_x - (crop_x % 2)

            vf = f"crop={crop_w}:{v_height}:{crop_x}:0,scale=1080:1920:flags=lanczos,setsar=1"
            filter_args = ["-vf", vf]

        elif mode == CropMode.FACECAM_SPLIT:
            # Top 35% (672px): YOLO-locked streamer facecam (1080:672 = 1.607:1) so zero background leaks.
            # Bottom 65% (1248px): 1080:1248 aspect-matched gameplay so full height & wider FOV remain intact.
            crop_top_w, crop_top_h, top_x, top_y = self._detect_facecam_crop_box(
                raw_video_path=raw_video_path,
                start_time=start_time,
                duration=duration,
                webcam_corner=webcam_corner,
                v_width=v_width,
                v_height=v_height,
            )
            crop_bot_w = max(2, min(v_width & ~1, int(v_height * (1080.0 / 1248.0)) & ~1))
            bot_x = max(0, (int((v_width - crop_bot_w) / 2)) & ~1)
            vf = (
                f"[0:v]crop={crop_top_w}:{crop_top_h}:{top_x}:{top_y},"
                "scale=1080:672:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:672[top];"
                f"[0:v]crop={crop_bot_w}:{v_height}:{bot_x}:0,"
                "scale=1080:1248:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1248[bottom];"
                "[top][bottom]vstack,setsar=1[v_out]"
            )
            filter_args = ["-filter_complex", vf, "-map", "[v_out]"]

        else:  # CENTER_ZOOM (Landscape Centered in 9:16 with Blurred Background Fill)
            source_chain = "[0:v]split=2[bg_in][fg_in];"
            vf = (
                source_chain
                + "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase:flags=bicubic,crop=1080:1920,boxblur=30:5[bg];"
                + "[fg_in]scale=1080:608:force_original_aspect_ratio=decrease:flags=lanczos,pad=1080:608:(ow-iw)/2:(oh-ih)/2[fg];"
                + "[bg][fg]overlay=0:656,setsar=1[v_clean]"
            )
            filter_args = ["-filter_complex", vf, "-map", "[v_clean]"]

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", str(raw_video_path),
            *filter_args,
            "-c:v", codec,
            *encoder_args,
            "-an",  # Audio will be handled by audio_processor and renderer
            str(output_cropped_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0 or not output_cropped_path.exists() or output_cropped_path.stat().st_size < 1000:
            if rectangles:
                raise RuntimeError(f"Protected crop failed; refusing an unmasked fallback: {result.stderr[-1000:]}")
            logger.warning(f"FFmpeg crop failed or produced empty file: {result.stderr[:200] if result else ''}. Falling back to center crop.")
            # Fallback to simple center crop if complex filter fails
            fallback_cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", str(raw_video_path),
                "-vf", "crop=in_h*9/16:in_h,scale=1080:1920",
                "-c:v", codec,
                *encoder_args,
                "-an",
                str(output_cropped_path)
            ]
            subprocess.run(fallback_cmd, check=True)

        return output_cropped_path

video_cropper = VideoCropper()
