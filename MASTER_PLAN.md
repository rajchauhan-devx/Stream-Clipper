# GTA6 AI STUDIO — Master Plan & Architecture Blueprint

## System Architecture Overview
A modern dark-mode creator tool (similar to OpusClip / CapCut Desktop) featuring a Python FastAPI backend (local GPU/M4 video processing + Gemini AI) paired with a React + Vite + Tailwind CSS dark-mode Studio UI, launched together with a single command (`python start.py`).

### AI Brain (google-genai SDK)
- **Director / Multimodal Analysis**: `gemini-3.8-flash` for multimodal video/audio understanding, viral segment selection, scriptwriting, and JSON edit planning.
- **Voiceover Synthesis**: `gemini-3.8-flash-tts` for commentary voiceovers (24kHz WAV).
- **Overlay Generation**: `gemini-3.1-flash-image` (Nano Banana 2) for custom meme/callout PNG graphics.

### Local Hardware Engine
- **Windows (RTX 3050 6GB)**: CUDA + `h264_nvenc` (`-preset p4 -cq 20`), `faster-whisper` (`float16`), sequential VRAM cleanup.
- **macOS (Apple M4)**: Metal / MPS + `h264_videotoolbox` (`-b:v 8M -allow_sw 1`), `mlx-whisper` / `faster-whisper` CPU fallback.
- **Audio & Subtitle Processing**:
  - Demucs (`htdemucs`) for copyright GTA radio music removal.
  - FFmpeg `sidechaincompress` for automatic -16dB gameplay audio ducking under voiceovers.
  - Whisper word-level timestamps -> Styled `.ass` subtitles with active-word highlighting.
  - YOLO11n (`yolo11n.pt`) for intelligent action tracking in 9:16 vertical crop.

### Operating Modes
1. **Auto-Pilot Mode**: URL / MP4 drop -> Ingest -> Gemini Analysis -> TTS -> YOLO Crop -> Caption -> FFmpeg Render -> Multi-platform queue.
2. **Manual Studio Mode**: Step-by-step review, script editing, voice regeneration, crop mode switching (Action Track, Facecam Split, Center Zoom), caption styling, and 9:16 preview with Shorts/Reels safe-zone guides.

---

## Phased Build Roadmap

### Phase 1: Foundation, Hardware Abstraction & Project Scaffold
- `backend/requirements.txt`: `google-genai`, `fastapi`, `uvicorn`, `websockets`, `pydantic`, `yt-dlp`, `opencv-python-headless`, `ultralytics`, `faster-whisper`, `python-dotenv`, `google-api-python-client`, `google-auth-oauthlib`, `requests`.
- `backend/config.py`: Hardware auto-detection (RTX 3050 NVENC vs M4 VideoToolbox), editable model constants.
- `backend/schemas.py`: Pydantic models (`ClipBlueprint`, `DirectorPlan`, `SocialMetadata`).
- `start.py`: Unified launcher starting FastAPI (port 8000) and React Vite (port 5173).

### Phase 2: Video Ingest & Gemini AI Director Engine
- `backend/services/ingest.py`: `yt-dlp` local 1080p fetch + FFmpeg 480p @ 1 FPS proxy generator (`scale=-2:480,fps=1`).
- `backend/services/gemini_director.py`: Multimodal proxy upload, structured JSON planning via `response_schema=DirectorPlan`, `gemini-3.8-flash-tts` voiceover synthesis, `gemini-3.1-flash-image` meme overlay generation, automatic remote file cleanup.

### Phase 3: Local Video Engine (Hardware-Accelerated & VRAM-Safe)
- `backend/services/audio_processor.py`: Demucs vocal/SFX separation to strip copyrighted radio + FFmpeg sidechain ducking (-16dB).
- `backend/services/video_cropper.py`: 16:9 to 9:16 conversion (Action Track with YOLO11n, Facecam Split 35/65, Center Zoom with blurred background).
- `backend/services/captioner.py`: Word-level whisper timestamps -> styled `.ass` subtitles.
- `backend/services/renderer.py`: Hardware-accelerated FFmpeg burn-in render (1080x1920 60fps MP4).

### Phase 4: Dual-Mode Studio UI
- `backend/main.py`: FastAPI REST + WebSocket endpoints for live progress, script/crop editing, re-generation, and file serving.
- `frontend/` (React + Vite + Tailwind CSS + Lucide Icons):
  - Dark-mode Studio UI (#0B0D12 base, #141821 cards, #6366F1 indigo, #10B981 emerald accents).
  - 4 Views: New Project (Dashboard), AI Studio (Manual Review with 9:16 player & safe zones), Upload Hub, Settings.

### Phase 5: Multi-Platform Upload Hub
- `backend/services/publishers/youtube_pub.py`: YouTube Data API v3 resumable upload with `#Shorts`.
- `backend/services/publishers/meta_pub.py`: Facebook Reels (rupload graph flow) & Instagram Reels (container flow with public URL tunnel support).
- `frontend/src/pages/UploadHub.tsx`: 3-column publishing card layout + 1-Click Export Pack.
