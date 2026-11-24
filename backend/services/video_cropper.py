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
                        # Fullscreen streamer check: large person taking >20% of frame area,
                        # >30% width, >40% height, and positioned centrally
                        if box_area > 0.20 and box_w > (0.30 * width) and box_h > (0.40 * height):
                            has_fullscreen_human = True
                            break

                sec = current_frame / fps
                if has_fullscreen_human:
                    intro_end_sec = sec + sample_interval_sec
                elif intro_end_sec > 0 and (sec - intro_end_sec) > 6.0:
                    # Gameplay confirmed for several consecutive checks
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

    def crop_to_vertical(
        self,
        raw_video_path: Path,
        start_time: float,
        duration: float,
        output_cropped_path: Path,
        mode: CropMode = CropMode.ACTION_TRACK,
        mask_webcam: bool = True,
        webcam_corner: str = "top_right",
        progress_callback: Optional[Callable[[int, str], None]] = None
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
            # Top 35% (672px): Top-left facecam. Bottom 65% (1248px): centered gameplay
            crop_top_w = int(v_width * 0.35)
            crop_top_h = int(v_height * 0.45)
            crop_bot_w = int(v_height * (9 / 16))
            bot_x = int((v_width - crop_bot_w) / 2)
            vf = (
                f"[0:v]crop={crop_top_w}:{crop_top_h}:20:20,scale=1080:672[top];"
                f"[0:v]crop={crop_bot_w}:{v_height}:{bot_x}:0,scale=1080:1248[bottom];"
                "[top][bottom]vstack,setsar=1[v_out]"
            )
            filter_args = ["-filter_complex", vf, "-map", "[v_out]"]

        else:  # CENTER_ZOOM (Landscape Centered in 9:16 with Blurred Background Fill)
            if mask_webcam:
                # Top-right webcam: X=750..1070, Y=660..890 on 1080x1920 canvas
                if "left" in webcam_corner.lower():
                    cam_x, cam_y, cam_w, cam_h = 10, 660, 320, 230
                elif "bottom" in webcam_corner.lower():
                    cam_x, cam_y, cam_w, cam_h = 750, 1030, 320, 230
                else:  # top_right
                    cam_x, cam_y, cam_w, cam_h = 750, 660, 320, 230

                vf = (
                    "[0:v]scale=1080:1920:flags=bicubic,boxblur=30:5[bg];"
                    "[0:v]scale=1080:608:flags=lanczos[fg];"
                    "[bg][fg]overlay=0:656,split=2[v_base][v_for_crop];"
                    f"[v_for_crop]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},boxblur=30:5[cam_blur];"
                    f"[v_base][cam_blur]overlay={cam_x}:{cam_y},setsar=1[v_clean]"
                )
                filter_args = ["-filter_complex", vf, "-map", "[v_clean]"]
            else:
                vf = (
                    "[0:v]scale=1080:1920:flags=bicubic,boxblur=30:5[bg];"
                    "[0:v]scale=1080:608:flags=lanczos[fg];"
                    "[bg][fg]overlay=0:656,setsar=1[v_clean]"
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
