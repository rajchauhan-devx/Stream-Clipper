import os
import gc
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import cv2
import numpy as np

from backend.config import TEMP_DIR, HARDWARE
from backend.schemas import CropMode

logger = logging.getLogger("gta6-studio.cropper")

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
                        # Find highest confidence or largest action box
                        boxes = results[0].boxes.xywh.cpu().numpy()
                        # Sort by area (w * h)
                        largest_box = max(boxes, key=lambda b: b[2] * b[3])
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
        # Center the 608px crop window on the action center
        crop_x = int(median_center - (crop_w / 2))
        # Clamp within valid bounds [0, max_x]
        return max(0, min(crop_x, max_x))

    def crop_to_vertical(
        self,
        raw_video_path: Path,
        start_time: float,
        duration: float,
        output_cropped_path: Path,
        mode: CropMode = CropMode.ACTION_TRACK,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Converts 16:9 gameplay to 1080x1920 (9:16) vertical using:
        - action_track: YOLO-guided panning
        - facecam_split: Top 35% streamer facecam / Bottom 65% gameplay
        - center_zoom: Cinematic center crop with blurred background fill
        """
        if progress_callback:
            progress_callback(30, f"Applying 9:16 vertical crop ({mode.value})...")

        logger.info(f"Cropping video segment: {raw_video_path} [{start_time}s -> +{duration}s] Mode: {mode}")

        # Codec arguments based on hardware
        codec = HARDWARE.ffmpeg_codec
        encoder_args = HARDWARE.encoder_args

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

            # Crop width 608 (9/16 of 1080), height 1080, then scale to 1080x1920
            vf = f"crop=608:1080:{crop_x}:0,scale=1080:1920,setsar=1"

        elif mode == CropMode.FACECAM_SPLIT:
            # Top 35% (672px): Top-left facecam. Bottom 65% (1248px): centered gameplay
            vf = (
                "[0:v]crop=640:480:20:20,scale=1080:672[top];"
                "[0:v]crop=608:1080:656:0,scale=1080:1248[bottom];"
                "[top][bottom]vstack,setsar=1"
            )

        else:  # CENTER_ZOOM (Landscape Centered in 9:16 with Blurred Background Fill)
            # High-end cinematic blurred background + centered pristine uncropped 16:9 foreground
            # The full 16:9 gameplay is completely zoomed out, uncropped, with in-game subtitles intact
            vf = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[bg];"
                "[0:v]scale=1080:608:flags=lanczos[fg];"
                "[bg][fg]overlay=0:656,setsar=1"
            )

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", str(raw_video_path),
            "-filter_complex" if (mode != CropMode.ACTION_TRACK) else "-vf", vf,
            "-c:v", codec,
            *encoder_args,
            "-an",  # Audio will be handled by audio_processor and renderer
            str(output_cropped_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0 or not output_cropped_path.exists() or output_cropped_path.stat().st_size < 1000:
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
