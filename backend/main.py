import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import os
import shutil
from backend.config import (
    HARDWARE, WORKSPACE_DIR, BASE_DIR, TEMP_DIR, DOWNLOADS_DIR, PROXIES_DIR, RENDERS_DIR,
    GEMINI_API_KEY, META_ACCESS_TOKEN, META_PAGE_ID, INSTAGRAM_ACCOUNT_ID,
    DIRECTOR_MODEL, TTS_MODEL, IMAGE_MODEL
)
from backend.schemas import (
    CreateJobRequest, UpdateClipRequest, SettingsUpdateRequest,
    HardwareStatusResponse, JobProgressUpdate, JobStatus, OperatingMode,
    CropMode, CaptionStyle, LongVideoStrategy, ResetPipelineRequest, ResetPipelineResponse,
    YouTubePublishRequest, YouTubeAuthStatusResponse,
    FacebookPublishRequest, FacebookStatusResponse
)
from backend.services.ingest import ingest_service
from backend.services.gemini_director import gemini_director
from backend.services.video_cropper import video_cropper
from backend.services.audio_processor import audio_processor
from backend.services.captioner import captioner_service
from backend.services.renderer import video_renderer
from backend.services.publishers.youtube_pub import youtube_publisher
from backend.services.publishers.meta_pub import meta_publisher

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("gta6-studio")

# Initialize FastAPI App
app = FastAPI(
    title="GTA6 AI Studio API",
    description="High-performance backend for AI-directed GTA 6 short-form video generation",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount workspace directory for direct video/audio/asset streaming in frontend
app.mount("/workspace", StaticFiles(directory=str(WORKSPACE_DIR)), name="workspace")

# In-memory Job & WebSocket Connection State
JOBS_DB: Dict[str, Dict[str, Any]] = {}
ACTIVE_TASKS: Dict[str, asyncio.Task] = {}
JOBS_CACHE_FILE = WORKSPACE_DIR / "jobs_db.json"

def save_jobs_db():
    try:
        JOBS_CACHE_FILE.write_text(json.dumps(JOBS_DB, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not persist JOBS_DB: {e}")

def load_jobs_db():
    global JOBS_DB
    if JOBS_CACHE_FILE.exists():
        try:
            loaded = json.loads(JOBS_CACHE_FILE.read_text(encoding="utf-8"))
            JOBS_DB.update(loaded)
            logger.info(f"Loaded {len(loaded)} job(s) from {JOBS_CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Could not load JOBS_DB from cache: {e}")

load_jobs_db()

def clean_workspace_files(job_id: str = None, delete_all: bool = True) -> int:
    """Safely removes video downloads, proxies, demucs audio, and temp files, returning bytes freed."""
    freed_bytes = 0
    target_dirs = [DOWNLOADS_DIR, PROXIES_DIR, TEMP_DIR]

    for folder in target_dirs:
        if not folder.exists():
            continue
        try:
            for item in list(folder.iterdir()):
                try:
                    if item.is_file():
                        if delete_all or (job_id and job_id in item.name):
                            size = item.stat().st_size
                            item.unlink(missing_ok=True)
                            freed_bytes += size
                    elif item.is_dir():
                        if delete_all or (job_id and job_id in item.name):
                            for root, dirs, files in os.walk(item, topdown=False):
                                for f in files:
                                    fp = Path(root) / f
                                    try:
                                        size = fp.stat().st_size
                                        fp.unlink(missing_ok=True)
                                        freed_bytes += size
                                    except Exception:
                                        pass
                                for d in dirs:
                                    try:
                                        shutil.rmtree(Path(root) / d, ignore_errors=True)
                                    except Exception:
                                        pass
                            shutil.rmtree(item, ignore_errors=True)
                except Exception as ex:
                    logger.warning(f"Could not remove {item}: {ex}")
        except Exception as e:
            logger.warning(f"Error accessing directory {folder}: {e}")

    return freed_bytes

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)
        logger.info(f"WebSocket client connected to job: {job_id}")

    def disconnect(self, job_id: str, websocket: WebSocket):
        if job_id in self.active_connections:
            if websocket in self.active_connections[job_id]:
                self.active_connections[job_id].remove(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]
        logger.info(f"WebSocket client disconnected from job: {job_id}")

    async def broadcast(self, job_id: str, message: Dict[str, Any]):
        if job_id in self.active_connections:
            for connection in self.active_connections[job_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send WS message: {e}")

manager = ConnectionManager()

# ------------------------------------------------------------------------------
# Clip Rendering Pipeline (Shared between Auto-Pilot and Manual Studio)
# ------------------------------------------------------------------------------
async def render_single_clip(job_id: str, clip_idx: int, total_clips: int = 1, progress_callback: Optional[Any] = None):
    job = JOBS_DB[job_id]
    clip = job["clips"][clip_idx]
    clip_id = clip["clip_id"]
    req = job["request"]
    clip_num = clip_idx + 1

    raw_path_str = job["metadata"].get("raw_path")
    cut_path_str = job["metadata"].get("cut_path")
    cut_start_sec = float(job["metadata"].get("cut_start_sec", 0.0))
    cut_dur_sec = float(job["metadata"].get("cut_duration_sec", 0.0))

    raw_path = Path(raw_path_str) if raw_path_str else None
    cut_path = Path(cut_path_str) if cut_path_str else None

    clip_start = float(clip["start_time"])
    clip_dur = float(clip["duration"])

    # Determine optimal video source and safe seeking timestamp
    if raw_path and raw_path.exists():
        source_path = raw_path
        start_time = cut_start_sec + clip_start
        raw_dur = float(job["metadata"].get("duration", 0.0))
        if raw_dur > 0 and (start_time + clip_dur) > raw_dur:
            start_time = max(0.0, raw_dur - clip_dur - 1.0)
    elif cut_path and cut_path.exists():
        source_path = cut_path
        start_time = clip_start
        if cut_dur_sec > 0 and (start_time + clip_dur) > cut_dur_sec:
            start_time = max(0.0, cut_dur_sec - clip_dur - 1.0)
    else:
        source_path = Path(raw_path_str or cut_path_str)
        start_time = clip_start

    # 1. 9:16 Vertical Video Crop
    if progress_callback:
        progress_callback(f"Clip {clip_num}/{total_clips}: Cropping 9:16 vertical action framing...")
    cropped_path = TEMP_DIR / f"{job_id}_{clip_id}_cropped.mp4"
    crop_mode = CropMode(clip.get("crop_mode") or req.get("crop_mode") or "center_zoom")
    await asyncio.to_thread(
        video_cropper.crop_to_vertical,
        raw_video_path=source_path,
        start_time=start_time,
        duration=clip_dur,
        output_cropped_path=cropped_path,
        mode=crop_mode
    )

    # 2. Extract Gameplay Audio Segment
    seg_audio = TEMP_DIR / f"{job_id}_{clip_id}_gameplay_raw.wav"
    import subprocess
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-t", str(clip_dur),
        "-i", str(source_path),
        "-vn", "-c:a", "pcm_s16le", "-ar", "48000",
        str(seg_audio)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. Strip Copyright Radio or Streamer Mic Voice if enabled
    if req.get("strip_streamer_voice", False) or (req.get("copyright_guard", True) and clip.get("has_copyrighted_music", False)):
        if progress_callback:
            progress_callback(f"Clip {clip_num}/{total_clips}: Demucs isolating SFX & removing streamer/radio audio...")
        clean_audio = TEMP_DIR / f"{job_id}_{clip_id}_clean_audio.wav"
        await asyncio.to_thread(audio_processor.strip_copyright_radio, seg_audio, clean_audio)
        seg_audio = clean_audio

    # 4. Duck and Mix Gameplay Audio under TTS Voiceover
    if progress_callback:
        progress_callback(f"Clip {clip_num}/{total_clips}: Mixing sidechain ducked audio (-16dB)...")
    voice_path = Path(clip["voice_path"])
    mixed_audio_path = TEMP_DIR / f"{job_id}_{clip_id}_mixed.wav"
    game_boost = float(req.get("game_volume_boost", 1.5))
    await asyncio.to_thread(
        audio_processor.duck_and_mix_audio,
        seg_audio,
        voice_path,
        mixed_audio_path,
        -16.0,
        game_boost
    )

    # 5. Generate Word-Level ASS Subtitles
    if progress_callback:
        progress_callback(f"Clip {clip_num}/{total_clips}: Aligning word-level animated subtitles...")
    ass_path = TEMP_DIR / f"{job_id}_{clip_id}_captions.ass"
    caption_style = CaptionStyle(clip.get("caption_style", "hormozi_yellow"))
    await asyncio.to_thread(captioner_service.generate_ass_subtitles, voice_path, ass_path, style=caption_style)

    # 6. Final Hardware Burn-in Render (M4 VideoToolbox / RTX 3050 NVENC)
    if progress_callback:
        progress_callback(f"Clip {clip_num}/{total_clips}: M4 hardware rendering final 1080x1920 60fps MP4...")
    overlay_path = None  # Callout rectangle blue box overlay disabled/removed

    # Determine dynamic watermark concealment corner via AI supervision
    watermark_corner = None
    if req.get("enable_watermark_masker", True):
        wm_info = clip.get("watermark_info") or {}
        if isinstance(wm_info, dict) and wm_info.get("detected"):
            watermark_corner = wm_info.get("corner", "bottom_right")
        elif hasattr(wm_info, "detected") and wm_info.detected:
            watermark_corner = getattr(wm_info.corner, "value", str(wm_info.corner))

        # Auto-detect if from MKIceAndFire walkthrough or previously detected tag
        if not watermark_corner and req.get("enable_watermark_masker", True):
            meta_title = str((job.get("metadata") or {}).get("title", "")).lower()
            url_str = str(req.get("url_or_path", ""))
            if "mkiceandfire" in meta_title or "-d_wt4gxmnw" in url_str.lower():
                watermark_corner = "bottom_right"

    # Generate attractive Top Topic Headline Banner if enabled
    topic_banner_path = None
    if req.get("enable_topic_header", True):
        hook_text = clip.get("hook_text") or clip.get("hook_summary") or "GTA 6 GAMEPLAY"
        topic_banner_path = await asyncio.to_thread(
            video_renderer.generate_topic_banner,
            hook_text=hook_text,
            job_id=job_id,
            clip_id=clip_id,
            category_tag="GTA 6 • NEW MISSION"
        )

    final_mp4 = await asyncio.to_thread(
        video_renderer.render_final_clip,
        cropped_video_path=cropped_path,
        mixed_audio_path=mixed_audio_path,
        ass_subtitles_path=ass_path,
        overlay_png_path=overlay_path,
        job_id=job_id,
        clip_id=clip_id,
        watermark_corner=watermark_corner,
        topic_banner_path=topic_banner_path
    )

    clip["rendered_video_path"] = str(final_mp4)
    clip["preview_url"] = f"/workspace/renders/{final_mp4.name}"
    clip["status"] = "rendered"
    save_jobs_db()

# ------------------------------------------------------------------------------
# Asynchronous Job Execution Pipeline
# ------------------------------------------------------------------------------
async def execute_job_pipeline(job_id: str):
    """Orchestrates Phase 2 & Phase 3 End-to-End Pipeline"""
    if job_id not in JOBS_DB:
        return

    job = JOBS_DB[job_id]
    req: CreateJobRequest = CreateJobRequest(**job["request"])
    loop = asyncio.get_running_loop()

    async def send_progress(pct: int, message: str, status_val: JobStatus = JobStatus.INGESTING, data: Any = None):
        job["progress_pct"] = pct
        job["step"] = message
        job["status"] = status_val
        if data:
            job.update(data)
        save_jobs_db()
        await manager.broadcast(job_id, {
            "event": "progress",
            "job_id": job_id,
            "status": status_val,
            "progress_pct": pct,
            "message": message,
            "data": data
        })

    def sync_cb(pct: int, message: str, status_val: JobStatus = JobStatus.INGESTING):
        try:
            asyncio.run_coroutine_threadsafe(send_progress(pct, message, status_val), loop)
        except Exception:
            pass

    try:
        # Step 1: Ingest Raw Video
        await send_progress(5, "Connecting to YouTube stream via yt-dlp...", JobStatus.INGESTING)
        meta = await asyncio.to_thread(
            ingest_service.download_or_link_video,
            url_or_path=req.url_or_path,
            job_id=job_id,
            progress_callback=lambda p, m: sync_cb(p, m, JobStatus.INGESTING)
        )
        job["metadata"] = meta
        raw_path = meta["raw_path"]

        # Step 1.5: Fast Video Cutter (Trims long livestreams into a focused segment for AI Vision)
        cut_start = getattr(req, "cut_start_time", "00:00:00")
        cut_dur = getattr(req, "cut_duration_mins", 20.0)
        auto_cut = getattr(req, "auto_cut_long_videos", True)
        strategy = getattr(req, "long_video_strategy", LongVideoStrategy.SEGMENT_HOPPER)

        # Strategy 1: Audio Energy Peak Scanner
        if strategy in (LongVideoStrategy.ENERGY_PEAKS, "energy_peaks"):
            await send_progress(28, "Audio Energy Peak Scanner: Analyzing 2-hour audio for combat action peaks...", JobStatus.INGESTING)
            peak_start_sec = await asyncio.to_thread(
                ingest_service.find_peak_action_window,
                raw_video_path=raw_path,
                search_duration_sec=7200.0,
                window_duration_mins=cut_dur,
                progress_callback=lambda p, m: sync_cb(p, m, JobStatus.INGESTING)
            )
            if peak_start_sec > 0:
                h = int(peak_start_sec // 3600)
                m = int((peak_start_sec % 3600) // 60)
                s = int(peak_start_sec % 60)
                cut_start = f"{h:02d}:{m:02d}:{s:02d}"
                logger.info(f"Targeting AI Director to peak action window at {cut_start} ({peak_start_sec:.1f}s)")

        await send_progress(30, f"Checking duration & cutting segment starting at {cut_start} for AI Vision...", JobStatus.INGESTING)
        cut_result = await asyncio.to_thread(
            ingest_service.cut_video_segment,
            raw_video_path=raw_path,
            job_id=job_id,
            start_time_str=cut_start,
            duration_mins=cut_dur,
            auto_cut_long=auto_cut,
            progress_callback=lambda p, m: sync_cb(p, m, JobStatus.INGESTING)
        )
        cut_path = cut_result["cut_path"]
        meta["cut_path"] = cut_path
        meta["is_cut"] = cut_result.get("is_cut", False)
        meta["cut_start_sec"] = cut_result.get("start_sec", 0.0)
        meta["cut_duration_sec"] = cut_result.get("duration_sec", meta.get("duration", 60.0))

        # Calculate next chapter timestamp for the Segment Hopper
        next_sec = meta["cut_start_sec"] + meta["cut_duration_sec"]
        total_raw_dur = meta.get("duration", 0.0)
        if next_sec < total_raw_dur:
            nh = int(next_sec // 3600)
            nm = int((next_sec % 3600) // 60)
            ns = int(next_sec % 60)
            meta["next_segment_start"] = f"{nh:02d}:{nm:02d}:{ns:02d}"
            meta["has_more_segments"] = True
        else:
            meta["has_more_segments"] = False

        job["metadata"] = meta

        # Step 2: Build 480p @ 1 FPS Lightweight Proxy (from cut video segment)
        await send_progress(32, "Generating 480p @ 1 FPS proxy for Gemini Vision...", JobStatus.INGESTING)
        proxy_path = await asyncio.to_thread(
            ingest_service.create_lightweight_proxy,
            raw_video_path=cut_path,
            job_id=job_id,
            progress_callback=lambda p, m: sync_cb(p, m, JobStatus.INGESTING)
        )
        job["proxy_path"] = str(proxy_path)

        # Step 3: Multimodal Analysis via Gemini Director
        await send_progress(52, "Gemini Vision analyzing gameplay moments & virality...", JobStatus.ANALYZING)
        plan = await asyncio.to_thread(
            gemini_director.analyze_gameplay_and_plan,
            proxy_path=proxy_path,
            source_title=meta.get("title", f"GTA6_{job_id}"),
            target_language=req.target_language.value,
            clip_count=req.clip_count,
            clip_length_range=req.clip_length_range,
            voiceover_pacing=req.voiceover_pacing.value if hasattr(req, "voiceover_pacing") else "hook_only",
            progress_callback=lambda p, m: sync_cb(p, m, JobStatus.ANALYZING)
        )
        job["plan"] = plan.model_dump()
        job["clips"] = [c.model_dump() for c in plan.clips]

        # Step 4: Synthesize Voiceovers & Callout Graphics
        enable_overlays = getattr(req, "enable_callout_overlay", False)
        await send_progress(70, "Generating spoken hook voiceovers...", JobStatus.VOICING)
        for i, clip in enumerate(job["clips"]):
            clip_id = clip["clip_id"]
            voice_path = await asyncio.to_thread(
                gemini_director.synthesize_voiceover,
                script=clip["commentary_script"],
                job_id=job_id,
                clip_id=clip_id,
                voice_name=clip.get("tts_voice", "Puck")
            )
            clip["voice_path"] = str(voice_path)

            # Keep overlay_path null to prevent callout rectangle box popups
            clip["overlay_path"] = None

        # Step 5: Autonomous AI Render of All Clips with Hardware Acceleration
        total_clips = len(job["clips"])
        for idx in range(total_clips):
            clip_num = idx + 1
            base_pct = 75 + int((idx / total_clips) * 22)
            await send_progress(
                base_pct,
                f"Autonomous AI rendering Clip {clip_num}/{total_clips} (9:16 {HARDWARE.ffmpeg_codec})...",
                JobStatus.RENDERING
            )
            await render_single_clip(
                job_id, idx, total_clips,
                progress_callback=lambda m: sync_cb(base_pct, m, JobStatus.RENDERING)
            )

        await send_progress(
            100,
            f"All {total_clips} clips rendered successfully in 1080x1920 60fps!",
            JobStatus.COMPLETED,
            {"clips": job["clips"], "plan": job["plan"], "metadata": job.get("metadata", {})}
        )

    except asyncio.CancelledError:
        logger.info(f"Pipeline job {job_id} cancelled by user.")
        job["status"] = JobStatus.CANCELLED
        job["step"] = "Pipeline stopped and reset by user"
        await manager.broadcast(job_id, {
            "event": "job_cancelled",
            "job_id": job_id,
            "status": JobStatus.CANCELLED,
            "message": "Pipeline cancelled and reset."
        })
        raise
    except Exception as e:
        logger.error(f"Pipeline error for job {job_id}: {e}", exc_info=True)
        job["status"] = JobStatus.FAILED
        job["error"] = str(e)
        await manager.broadcast(job_id, {
            "event": "error",
            "job_id": job_id,
            "status": JobStatus.FAILED,
            "message": f"Error: {e}"
        })
    finally:
        ACTIVE_TASKS.pop(job_id, None)

# ------------------------------------------------------------------------------
# REST API Endpoints
# ------------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    return {
        "status": "online",
        "service": "GTA6 AI Studio Backend",
        "version": "1.0.0",
        "hardware_badge": HARDWARE.get_status_badge()["badge_label"]
    }

@app.get("/api/hardware", response_model=HardwareStatusResponse)
async def get_hardware():
    return HARDWARE.get_status_badge()

@app.get("/api/settings")
async def get_settings():
    return {
        "has_gemini_key": bool(GEMINI_API_KEY) or gemini_director.is_adc,
        "auth_mode": gemini_director.auth_mode,
        "is_adc": gemini_director.is_adc,
        "adc_project": gemini_director.project_id,
        "gemini_api_key_masked": "Google Cloud ADC Active" if gemini_director.is_adc else (f"...{GEMINI_API_KEY[-4:]}" if len(GEMINI_API_KEY) > 4 else "Not Set"),
        "has_meta_token": bool(META_ACCESS_TOKEN),
        "has_meta_page_id": bool(META_PAGE_ID),
        "has_instagram_account": bool(INSTAGRAM_ACCOUNT_ID),
        "director_model": DIRECTOR_MODEL,
        "tts_model": TTS_MODEL,
        "image_model": IMAGE_MODEL,
        "hardware": HARDWARE.get_status_badge()
    }

@app.post("/api/settings")
async def update_settings(payload: SettingsUpdateRequest):
    env_file = BASE_DIR / ".env"
    existing_lines = []
    if env_file.exists():
        existing_lines = env_file.read_text().splitlines()

    env_dict = {}
    for line in existing_lines:
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_dict[k.strip()] = v.strip()

    if payload.gemini_api_key:
        env_dict["GEMINI_API_KEY"] = payload.gemini_api_key
    if payload.meta_access_token:
        env_dict["META_ACCESS_TOKEN"] = payload.meta_access_token
    if payload.meta_page_id:
        env_dict["META_PAGE_ID"] = payload.meta_page_id
    if payload.instagram_account_id:
        env_dict["INSTAGRAM_ACCOUNT_ID"] = payload.instagram_account_id
    if payload.public_tunnel_url:
        env_dict["PUBLIC_TUNNEL_URL"] = payload.public_tunnel_url
    if payload.director_model:
        env_dict["DIRECTOR_MODEL"] = payload.director_model
    if payload.tts_model:
        env_dict["TTS_MODEL"] = payload.tts_model
    if payload.image_model:
        env_dict["IMAGE_MODEL"] = payload.image_model

    new_content = "\n".join([f"{k}={v}" for k, v in env_dict.items()]) + "\n"
    env_file.write_text(new_content)
    return {"status": "success", "message": "Settings updated successfully"}

@app.post("/api/jobs")
async def create_job(request: CreateJobRequest):
    import uuid
    job_id = f"job_{uuid.uuid4().hex[:8]}"

    job_entry = {
        "job_id": job_id,
        "request": request.model_dump(),
        "status": JobStatus.PENDING,
        "progress_pct": 0,
        "step": "Initialized",
        "error": None,
        "plan": None,
        "clips": []
    }
    JOBS_DB[job_id] = job_entry
    save_jobs_db()
    logger.info(f"Created new job: {job_id} [Mode: {request.mode}]")

    task = asyncio.create_task(execute_job_pipeline(job_id))
    ACTIVE_TASKS[job_id] = task

    return {
        "job_id": job_id,
        "status": JobStatus.PENDING,
        "message": f"Job {job_id} launched in background."
    }

@app.post("/api/pipeline/reset", response_model=ResetPipelineResponse)
async def reset_pipeline(payload: Optional[ResetPipelineRequest] = None):
    """
    Stops any active pipeline processes, cancels background tasks, and
    permanently deletes all downloaded raw videos, proxies, and temporary files.
    """
    req_job_id = payload.job_id if payload else None
    delete_all = payload.delete_all if payload else True

    logger.info(f"Received reset request (job_id={req_job_id}, delete_all={delete_all})")

    # 1. Cancel active asyncio tasks
    cancelled_jobs = []
    for jid, task in list(ACTIVE_TASKS.items()):
        if delete_all or jid == req_job_id:
            if not task.done():
                task.cancel()
            ACTIVE_TASKS.pop(jid, None)
            cancelled_jobs.append(jid)

    # 2. Terminate any running ffmpeg or yt-dlp child processes
    try:
        import subprocess
        subprocess.run(["pkill", "-9", "-f", "ffmpeg"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "yt-dlp"], capture_output=True)
        logger.info("Terminated active ffmpeg and yt-dlp processes.")
    except Exception as e:
        logger.warning(f"Error terminating child processes: {e}")

    # 3. Clean files from downloads, proxies, and temp folders
    freed_bytes = clean_workspace_files(job_id=req_job_id, delete_all=delete_all)
    freed_mb = round(freed_bytes / (1024 * 1024), 2)

    # 4. Broadcast cancellation to WebSocket clients and update job states
    target_ids = cancelled_jobs if not delete_all else list(JOBS_DB.keys())
    for jid in target_ids:
        if jid in JOBS_DB:
            JOBS_DB[jid]["status"] = JobStatus.CANCELLED
            JOBS_DB[jid]["progress_pct"] = 0
            JOBS_DB[jid]["step"] = "Pipeline stopped and reset by user"
            await manager.broadcast(jid, {
                "event": "job_cancelled",
                "job_id": jid,
                "status": JobStatus.CANCELLED,
                "message": f"Pipeline stopped. Freed {freed_mb} MB disk space."
            })

    if delete_all:
        JOBS_DB.clear()

    msg = f"Pipeline stopped and reset. All downloads wiped, freed {freed_mb} MB disk space."
    logger.info(msg)
    return ResetPipelineResponse(
        status="success",
        message=msg,
        freed_mb=freed_mb
    )

@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancels a specific job and wipes its associated downloads and artifacts."""
    return await reset_pipeline(ResetPipelineRequest(job_id=job_id, delete_all=False))

@app.get("/api/jobs")
async def list_all_jobs():
    load_jobs_db()
    return list(JOBS_DB.values())

@app.get("/api/jobs/latest")
async def get_latest_job():
    load_jobs_db()
    if not JOBS_DB:
        return None
    return list(JOBS_DB.values())[-1]

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in JOBS_DB:
        load_jobs_db()
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JOBS_DB[job_id]

@app.patch("/api/jobs/{job_id}/clips/{clip_id}")
async def update_clip(job_id: str, clip_id: str, payload: UpdateClipRequest):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")

    job = JOBS_DB[job_id]
    clips = job.get("clips", [])
    target_clip = next((c for c in clips if c.get("clip_id") == clip_id), None)

    if not target_clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found in job {job_id}")

    update_data = payload.model_dump(exclude_unset=True)
    target_clip.update(update_data)

    await manager.broadcast(job_id, {
        "event": "clip_updated",
        "clip_id": clip_id,
        "updated_fields": update_data
    })

    return {"status": "success", "clip": target_clip}

@app.post("/api/jobs/{job_id}/clips/{clip_id}/regenerate-voice")
async def regenerate_voice(job_id: str, clip_id: str):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS_DB[job_id]
    clips = job.get("clips", [])
    target_clip = next((c for c in clips if c.get("clip_id") == clip_id), None)
    if not target_clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    voice_path = gemini_director.synthesize_voiceover(
        script=target_clip["commentary_script"],
        job_id=job_id,
        clip_id=clip_id,
        voice_name=target_clip.get("tts_voice", "Puck")
    )
    target_clip["voice_path"] = str(voice_path)
    return {"status": "success", "voice_path": str(voice_path)}

@app.post("/api/jobs/{job_id}/clips/{clip_id}/render")
async def render_clip_endpoint(job_id: str, clip_id: str, background_tasks: BackgroundTasks):
    """Triggers Phase 3 hardware render for a specific clip in Manual Studio"""
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS_DB[job_id]
    clips = job.get("clips", [])
    clip_idx = next((i for i, c in enumerate(clips) if c.get("clip_id") == clip_id), None)
    if clip_idx is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    async def run_render():
        clips[clip_idx]["status"] = "rendering"
        await manager.broadcast(job_id, {"event": "clip_rendering", "clip_id": clip_id})
        await render_single_clip(job_id, clip_idx)
        await manager.broadcast(job_id, {
            "event": "clip_rendered",
            "clip_id": clip_id,
            "preview_url": clips[clip_idx]["preview_url"]
        })

    background_tasks.add_task(run_render)
    return {"status": "success", "message": f"Rendering clip {clip_id} initiated."}

@app.get("/api/jobs/{job_id}/clips/{clip_id}/download")
async def download_clip_endpoint(job_id: str, clip_id: str):
    """Directly downloads rendered MP4 with Content-Disposition attachment header"""
    final_file = RENDERS_DIR / f"{job_id}_{clip_id}_final.mp4"
    if not final_file.exists():
        raise HTTPException(status_code=404, detail="Rendered clip not found on disk")
    return FileResponse(
        path=str(final_file),
        media_type="video/mp4",
        filename=f"GTA6_{clip_id}_Short.mp4"
    )

@app.get("/api/youtube/status", response_model=YouTubeAuthStatusResponse)
async def get_youtube_status():
    from backend.services.publishers.youtube_pub import TOKEN_FILE
    from backend.config import YOUTUBE_CLIENT_SECRETS_FILE
    secrets_path = Path(YOUTUBE_CLIENT_SECRETS_FILE)
    return {
        "has_token": TOKEN_FILE.exists(),
        "has_client_secret": secrets_path.exists(),
        "client_secrets_path": str(secrets_path),
        "channel_title": None
    }

@app.post("/api/youtube/client-secret")
async def save_client_secret(payload: Dict[str, Any]):
    from backend.config import YOUTUBE_CLIENT_SECRETS_FILE
    secrets_path = Path(YOUTUBE_CLIENT_SECRETS_FILE)
    if "content" in payload:
        secrets_path.write_text(payload["content"], encoding="utf-8")
        return {"status": "success", "message": f"Saved client_secret.json to {secrets_path}"}
    raise HTTPException(status_code=400, detail="Missing 'content' in payload")

@app.post("/api/jobs/{job_id}/clips/{clip_id}/publish/youtube")
async def publish_youtube(job_id: str, clip_id: str, payload: Optional[YouTubePublishRequest] = None):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS_DB[job_id]
    clip = next((c for c in job.get("clips", []) if c.get("clip_id") == clip_id), None)
    if not clip or not clip.get("rendered_video_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before publishing.")

    sm = clip.get("social_metadata", {}).get("youtube", {})
    title = (payload.title if payload and payload.title else sm.get("title")) or f"GTA 6 Viral Moment #{clip_id}"
    description = (payload.description if payload and payload.description else sm.get("description")) or "Viral GTA 6 Moment #Shorts"
    tags = (payload.tags if payload and payload.tags is not None else sm.get("tags")) or ["Shorts", "GTA6"]
    privacy = (payload.privacy if payload and payload.privacy else sm.get("privacy")) or "public"
    publish_at = payload.publish_at if payload else None

    try:
        res = youtube_publisher.publish_short(
            video_path=Path(clip["rendered_video_path"]),
            title=title,
            description=description,
            tags=tags,
            privacy=privacy,
            publish_at=publish_at
        )
        return res
    except Exception as e:
        logger.error(f"YouTube publishing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/facebook/status", response_model=FacebookStatusResponse)
async def get_facebook_status():
    from backend.config import META_ACCESS_TOKEN, META_PAGE_ID
    token = META_ACCESS_TOKEN or os.getenv("META_ACCESS_TOKEN", "")
    page_id = META_PAGE_ID or os.getenv("META_PAGE_ID", "")
    return {
        "has_token": bool(token),
        "has_page_id": bool(page_id),
        "page_id": page_id or None
    }

@app.post("/api/jobs/{job_id}/clips/{clip_id}/publish/facebook")
async def publish_facebook(job_id: str, clip_id: str, payload: Optional[FacebookPublishRequest] = None):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS_DB[job_id]
    clip = next((c for c in job.get("clips", []) if c.get("clip_id") == clip_id), None)
    if not clip or not clip.get("rendered_video_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before publishing.")

    sm = clip.get("social_metadata", {}).get("facebook", {})
    caption = (payload.caption if payload and payload.caption else sm.get("caption")) or "GTA 6 Gameplay Reel!"
    hashtags = (payload.hashtags if payload and payload.hashtags is not None else sm.get("hashtags")) or ["#GTA6", "#GamingReels"]
    video_state = (payload.video_state if payload and payload.video_state else "PUBLISHED")
    scheduled_publish_time = payload.scheduled_publish_time if payload else None
    page_id = payload.page_id if payload and payload.page_id else None

    try:
        res = meta_publisher.publish_facebook_reel(
            video_path=Path(clip["rendered_video_path"]),
            caption=caption,
            hashtags=hashtags,
            video_state=video_state,
            scheduled_publish_time=scheduled_publish_time,
            custom_page_id=page_id
        )
        return res
    except Exception as e:
        logger.error(f"Facebook publishing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/{job_id}/clips/{clip_id}/publish/instagram")
async def publish_instagram(job_id: str, clip_id: str):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS_DB[job_id]
    clip = next((c for c in job.get("clips", []) if c.get("clip_id") == clip_id), None)
    if not clip or not clip.get("rendered_video_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before publishing.")

    sm = clip.get("social_metadata", {}).get("instagram", {})
    try:
        res = meta_publisher.publish_instagram_reel(
            video_path=Path(clip["rendered_video_path"]),
            caption=sm.get("caption", "GTA 6 Insane Reel!"),
            hashtags=sm.get("hashtags", ["#gta6", "#gaming", "#reels"])
        )
        return res
    except Exception as e:
        logger.error(f"Instagram publishing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs/{job_id}/clips/{clip_id}/export-pack")
async def get_export_pack(job_id: str, clip_id: str):
    if job_id not in JOBS_DB:
        raise HTTPException(status_code=404, detail="Job not found")
    job = JOBS_DB[job_id]
    clip = next((c for c in job.get("clips", []) if c.get("clip_id") == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    sm = clip.get("social_metadata", {})
    return {
        "job_id": job_id,
        "clip_id": clip_id,
        "rendered_video_path": clip.get("rendered_video_path"),
        "preview_url": clip.get("preview_url"),
        "youtube": sm.get("youtube"),
        "instagram": sm.get("instagram"),
        "facebook": sm.get("facebook")
    }

# ------------------------------------------------------------------------------
# Real-Time WebSocket Progress Pipeline
# ------------------------------------------------------------------------------

@app.websocket("/ws/progress/{job_id}")
async def websocket_progress_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        if job_id not in JOBS_DB:
            load_jobs_db()
        if job_id in JOBS_DB:
            await websocket.send_json({
                "event": "state_snapshot",
                "job": JOBS_DB[job_id]
            })

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                logger.info(f"Received WS message for {job_id}: {msg}")
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(job_id, websocket)
