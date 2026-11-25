"""Local neural reconstruction of creator overlays before video layout/compositing."""

import hashlib
import json
import logging
import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import requests
import torch

from backend.config import HARDWARE, WORKSPACE_DIR

logger = logging.getLogger("gta6-studio.inpainting")
MODEL_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
MODEL_SHA256 = "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"


class CreatorInpainter:
    def __init__(self):
        self.model = None
        self.device = None
        self.lock = threading.Lock()

    def _load_model(self):
        if self.model is not None:
            return
        model_path = WORKSPACE_DIR / "models" / "big-lama.pt"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        if not model_path.exists():
            logger.info("Downloading neural background reconstruction model (197 MB)...")
            partial = model_path.with_suffix(".download")
            try:
                with requests.get(MODEL_URL, stream=True, timeout=(20, 60)) as response:
                    response.raise_for_status()
                    with partial.open("wb") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            handle.write(chunk)
                partial.replace(model_path)
            finally:
                partial.unlink(missing_ok=True)
        with model_path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != MODEL_SHA256:
            raise RuntimeError("Background reconstruction model checksum failed. Replace workspace/models/big-lama.pt.")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
        self.model = torch.jit.load(str(model_path), map_location=self.device).eval()
        logger.info("Neural background reconstruction ready on %s", self.device)

    def _predict_rgb(self, frames: list[np.ndarray], mask: np.ndarray) -> list[np.ndarray]:
        with self.lock:
            self._load_model()
            images = np.stack([cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames])
            # Never feed the hidden face or lettering to the reconstruction model.
            images[:, mask > 0] = 0
            tensor = torch.from_numpy(images.transpose(0, 3, 1, 2).copy()).float().div(255).to(self.device)
            masks = torch.from_numpy((mask > 0).astype(np.float32)).unsqueeze(0).unsqueeze(0).repeat(len(frames), 1, 1, 1).to(self.device)
            with torch.inference_mode():
                result = self.model(tensor, masks).permute(0, 2, 3, 1).cpu().numpy()
            if not np.isfinite(result).all():
                raise RuntimeError("Neural background reconstruction returned invalid pixels.")
            return [np.clip(item * 255, 0, 255).astype(np.uint8) for item in result]

    def reconstruct_segment(
        self, source: Path, start: float, duration: float, rectangles: list[tuple[int, int, int, int]],
        output: Path, progress: Callable[[int, str], None] | None = None,
    ) -> Path:
        info = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,r_frame_rate", "-of", "json", str(source),
        ]))["streams"][0]
        width, height = int(info["width"]), int(info["height"])
        fps = Fraction(info["r_frame_rate"])
        full_mask = np.zeros((height, width), dtype=np.uint8)
        for x, y, w, h in rectangles:
            full_mask[y:y+h, x:x+w] = 255
        # Model sees the entire scene; only the marked pixels are replaced at full output resolution.
        small_width = 512
        small_height = max(8, round(height * small_width / width / 8) * 8)
        small_mask = cv2.resize(full_mask, (small_width, small_height), interpolation=cv2.INTER_NEAREST)
        small_mask = cv2.dilate(small_mask, np.ones((3, 3), np.uint8))
        alpha = (full_mask.astype(np.float32) / 255)[..., None]
        reader = subprocess.Popen([
            "ffmpeg", "-v", "error", "-ss", str(start), "-t", str(duration), "-i", str(source),
            "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        log_path = output.with_suffix(".ffmpeg.log")
        output.parent.mkdir(parents=True, exist_ok=True)
        partial_output = output.with_name(output.stem + ".partial.mp4")
        frame_bytes = width * height * 3
        # Reconstruct at up to 30 FPS; preserve every original gameplay frame outside the mask.
        stride = max(1, round(float(fps) / 30))
        count = 0
        next_log = 0
        expected = duration * float(fps)
        try:
            with log_path.open("wb") as encoder_log:
                writer = subprocess.Popen([
                    "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                    "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an",
                    "-c:v", HARDWARE.ffmpeg_codec, *HARDWARE.encoder_args, str(partial_output),
                ], stdin=subprocess.PIPE, stderr=encoder_log)
                try:
                    exhausted = False
                    previous_fill = None
                    while not exhausted:
                        batch, sample_indices, samples = [], [], []
                        for _ in range(8 * stride):
                            data = reader.stdout.read(frame_bytes)
                            if not data:
                                exhausted = True
                                break
                            if len(data) != frame_bytes:
                                raise RuntimeError("Incomplete source frame during background reconstruction.")
                            frame = np.frombuffer(data, np.uint8).reshape(height, width, 3)
                            if (count + len(batch)) % stride == 0:
                                sample_indices.append(len(batch))
                                samples.append(cv2.resize(frame, (small_width, small_height), interpolation=cv2.INTER_AREA))
                            batch.append(frame)
                        if not batch:
                            break
                        predictions = dict(zip(sample_indices, self._predict_rgb(samples, small_mask)))
                        for idx, frame in enumerate(batch):
                            if idx in predictions:
                                previous_fill = cv2.resize(cv2.cvtColor(predictions[idx], cv2.COLOR_RGB2BGR), (width, height), interpolation=cv2.INTER_CUBIC)
                            if previous_fill is None:
                                raise RuntimeError("No generated background was available for the first video frame.")
                            clean = np.clip(frame * (1-alpha) + previous_fill * alpha, 0, 255).astype(np.uint8)
                            writer.stdin.write(clean.tobytes())
                            count += 1
                        if progress:
                            progress(min(99, round(count / max(1, duration * float(fps)) * 100)), "AI reconstructing gameplay behind creator overlays...")
                        if count >= next_log:
                            logger.info("AI reconstructing %s: %.0f%%", output.name, count / max(1, expected) * 100)
                            next_log = count + max(1, round(float(fps) * 2))
                    writer.stdin.close()
                    if writer.wait() != 0:
                        raise RuntimeError("AI reconstruction encoder failed: " + log_path.read_text()[-1000:])
                finally:
                    if writer.stdin and not writer.stdin.closed:
                        writer.stdin.close()
                    if writer.poll() is None:
                        writer.terminate()
                        try:
                            writer.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            writer.kill()
                            writer.wait()
            if reader.wait() != 0 or not count:
                raise RuntimeError("Source decoding failed during AI background reconstruction.")
            if abs(count - expected) > 2:
                raise RuntimeError(f"AI reconstruction frame count mismatch: {count} vs {expected:.1f}.")
            partial_output.replace(output)
            return output
        except Exception:
            partial_output.unlink(missing_ok=True)
            raise
        finally:
            if reader.stdout:
                reader.stdout.close()
            if reader.poll() is None:
                reader.terminate()
                try:
                    reader.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    reader.kill()
                    reader.wait()


creator_inpainter = CreatorInpainter()
