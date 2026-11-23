import os
import platform
import shutil
from pathlib import Path
from typing import Dict, List, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base project directories
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
WORKSPACE_DIR = BASE_DIR / "workspace"
DOWNLOADS_DIR = WORKSPACE_DIR / "downloads"
PROXIES_DIR = WORKSPACE_DIR / "proxies"
RENDERS_DIR = WORKSPACE_DIR / "renders"
ASSETS_DIR = WORKSPACE_DIR / "assets"
TEMP_DIR = WORKSPACE_DIR / "temp"

# Ensure all workspace directories exist
for folder in [WORKSPACE_DIR, DOWNLOADS_DIR, PROXIES_DIR, RENDERS_DIR, ASSETS_DIR, TEMP_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------------------
# Editable Model IDs (Centralized AI Brain Config)
# ------------------------------------------------------------------------------
DIRECTOR_MODEL = os.getenv("DIRECTOR_MODEL", "gemini-2.5-flash")
TTS_MODEL = os.getenv("TTS_MODEL", "gemini-2.5-flash-tts")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-3.1-flash-image")

# ------------------------------------------------------------------------------
# API Credentials
# ------------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", str(BASE_DIR / "client_secret.json"))
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_PAGE_ID = os.getenv("META_PAGE_ID", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
PUBLIC_TUNNEL_URL = os.getenv("PUBLIC_TUNNEL_URL", "")  # Used for Instagram URL container pull if needed

# ------------------------------------------------------------------------------
# Cross-Platform Hardware Engine Detection
# ------------------------------------------------------------------------------
class HardwareEngine:
    def __init__(self):
        self.os_type = platform.system()
        self.machine = platform.machine()
        self.device_name = "Unknown Device"
        self.accelerator = "CPU"
        self.vram_gb = 0.0
        self.ffmpeg_codec = "libx264"
        self.encoder_args: List[str] = ["-preset", "fast", "-crf", "22", "-profile:v", "high", "-level", "4.2", "-g", "60", "-bf", "2", "-flags", "+cgop"]
        self.whisper_backend = "faster-whisper"
        self.compute_type = "int8"
        self.is_apple_silicon = False
        self.is_cuda = False
        self._detect_hardware()

    def _detect_hardware(self):
        # 1. Check for CUDA (Windows / Linux with NVIDIA RTX 3050 or similar)
        try:
            import torch
            if torch.cuda.is_available():
                self.is_cuda = True
                self.accelerator = "CUDA"
                gpu_name = torch.cuda.get_device_name(0)
                self.device_name = gpu_name
                # Calculate VRAM in GB
                total_vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                self.vram_gb = round(total_vram, 2)

                # Configure NVENC hardware encoder (YouTube Shorts / Reels high compatibility)
                self.ffmpeg_codec = "h264_nvenc"
                self.encoder_args = ["-preset", "p4", "-cq", "20", "-profile:v", "high", "-level", "4.2", "-g", "60", "-bf", "2", "-flags", "+cgop"]
                self.whisper_backend = "faster-whisper"
                self.compute_type = "float16" if self.vram_gb >= 4.0 else "int8"
                return
        except Exception:
            pass

        # 2. Check for macOS Apple Silicon (M1/M2/M3/M4)
        if self.os_type == "Darwin":
            self.device_name = f"Apple Silicon ({self.machine})"
            self.accelerator = "Metal / Apple Silicon"
            self.is_apple_silicon = True
            
            # Check for VideoToolbox support in FFmpeg
            ffmpeg_path = shutil.which("ffmpeg")
            has_videotoolbox = True  # Default on modern macOS with Homebrew ffmpeg
            
            if has_videotoolbox:
                self.ffmpeg_codec = "h264_videotoolbox"
                # M4 optimized VideoToolbox parameters
                self.encoder_args = ["-b:v", "8M", "-allow_sw", "1"]
            else:
                self.ffmpeg_codec = "libx264"
                self.encoder_args = ["-preset", "fast", "-crf", "22"]

            # Prefer mlx-whisper on Apple Silicon if available, fallback to faster-whisper
            try:
                import mlx_whisper  # type: ignore
                self.whisper_backend = "mlx-whisper"
            except ImportError:
                self.whisper_backend = "faster-whisper"
            
            self.compute_type = "float32"
            return

        # 3. CPU Fallback (Linux / Windows without CUDA)
        self.device_name = f"Generic CPU ({self.machine})"
        self.accelerator = "CPU"
        self.ffmpeg_codec = "libx264"
        self.encoder_args = ["-preset", "fast", "-crf", "22"]
        self.whisper_backend = "faster-whisper"
        self.compute_type = "int8"

    def get_status_badge(self) -> Dict[str, Any]:
        """Returns hardware badge and encoder information for Studio UI"""
        badge_label = "🟢 CPU Active"
        if self.is_cuda:
            badge_label = f"🟢 {self.device_name} ({self.vram_gb}GB VRAM, NVENC Active)"
        elif self.is_apple_silicon:
            badge_label = f"🟢 Apple M-Series (VideoToolbox Active)"

        return {
            "os": self.os_type,
            "architecture": self.machine,
            "device_name": self.device_name,
            "accelerator": self.accelerator,
            "vram_gb": self.vram_gb,
            "ffmpeg_codec": self.ffmpeg_codec,
            "encoder_args": self.encoder_args,
            "whisper_backend": self.whisper_backend,
            "compute_type": self.compute_type,
            "badge_label": badge_label,
            "models": {
                "director": DIRECTOR_MODEL,
                "tts": TTS_MODEL,
                "image": IMAGE_MODEL,
            }
        }

# Global hardware instance
HARDWARE = HardwareEngine()
