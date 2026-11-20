# ⚡ Stream-Clipper — AI-Powered Short-Form Studio

> **Transform raw multi-hour gaming livestreams & walkthroughs into viral, high-retention 9:16 Shorts, Reels, and TikToks in minutes.**  
> Powered by **Gemini Vision**, **Neural TTS**, **VideoToolbox / NVENC Hardware Encoding**, and **Audio Energy Peak Detection**.

---

## 🌟 Key Features

### 1. 🎬 3-Tier Viral Visual Architecture (No 3x Crop)
- **Top Zone:** Dynamic glassmorphic **Topic Headline Card** with neon border & emoji tags (*"🔥 GTA 6 • NEW MISSION: THEY JUST GOT ARRESTED?! 🚨"*), capturing the 70%+ of viewers who scroll on mute.
- **Center Zone:** Full, uncropped 16:9 landscape gameplay centered in a 9:16 frame with cinematic 30px Gaussian blurred background fill. 100% field-of-view preserved.
- **Bottom Zone:** Kinetic word-level animated subtitles anchored in the lower blurred margin (`Y=1700`) with zero overlap on game characters.

### 2. 🛡️ AI-Supervised Watermark & Facecam Masker
- Automatically scans video frames using **Gemini Vision** to detect persistent third-party channel watermarks, creator handles, and streamer webcams.
- Dynamically burns an authentic **`[ GTA VI • 4K 60FPS ]`** metallic/neon glassmorphism badge directly over the detected corner (`bottom_right`, `bottom_left`, `top_right`, or `top_left`) with 0ms extra render delay.

### 3. 🎯 Multi-Hour VOD Ingestion (1h–3h+ Solved)
- **⚡ Sequential Segment Hopper:** Processes a focused 20-minute chapter with a 1-click button to immediately jump and harvest the next chapter from the locally cached video (0s re-download).
- **🎯 Audio Energy Peak Scanner:** Ultra-fast 4.5-second RMS energy analysis across the entire 2-hour audio stream to automatically detect the window with maximum gunfire, explosion, and combat density.
- **🤖 Full VOD Auto-Batch:** Overnight continuous queue that automatically splits multi-hour VODs into sequential chunks, rendering a library of 15–18 ready-to-post clips.

### 4. 🎙️ Dual-Layer Audio Mastering & Neural TTS
- **Opening Spoken Hook:** Genuine 24kHz neural speech powered by `gemini-3.1-flash-tts-preview` (`Puck`, `Kore`, `Charon`) for an energetic 3–5s opening hook.
- **Audible In-Game Dialogue:** Bypasses vocal stripping on walkthroughs and boosts in-game character speech by 1.5x with limiter protection.
- **Sidechain Compression:** Smoothly ducks gameplay audio under the spoken hook by -16dB, then lets gameplay sound take over.
- **Broadcast Loudness:** Mastered to YouTube Shorts / Reels standard **-14 LUFS** (`loudnorm=I=-14:LRA=11:TP=-1.5`).

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10+
- Node.js 18+ and `pnpm` (or `npm`)
- `ffmpeg` installed with hardware acceleration support (`videotoolbox` on macOS / `nvenc` on NVIDIA)
- Google Cloud ADC credentials or `GEMINI_API_KEY`

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/rajchauhan-devx/Stream-Clipper.git
cd Stream-Clipper

# Create Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Install frontend dependencies
cd frontend
pnpm install
cd ..
```

### 2. Environment Setup
Copy the example environment file:
```bash
cp .env.example .env
```
Ensure either `GEMINI_API_KEY` is set in `.env` or Google Cloud ADC (`gcloud auth application-default login`) is configured.

### 3. Launch Studio
Run the unified single-command launcher:
```bash
python3 start.py
```
- **Studio Web UI:** [http://localhost:5173](http://localhost:5173)
- **FastAPI Backend Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🛠️ Tech Stack

- **Backend:** FastAPI, Python 3.11, Uvicorn, WebSockets
- **AI Brain:** Google Gemini 2.5 Flash (Vision & Planning), Gemini 3.1 Flash TTS (Neural Voices)
- **Video Engine:** FFmpeg (VideoToolbox / NVENC Hardware Acceleration), OpenCV, PIL, faster-whisper
- **Frontend:** React 18, Vite, TypeScript, Tailwind CSS, Lucide Icons

---

## 📄 License
MIT License. Built for creators and short-form video editors.
