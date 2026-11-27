import os
import re
import json
import time
import uuid
import shutil
import logging
import asyncio
import threading
import subprocess
from contextlib import nullcontext
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import backend.config as app_config
from backend.config import (
    HARDWARE, WORKSPACE_DIR, BASE_DIR, TEMP_DIR, DOWNLOADS_DIR, PROXIES_DIR, RENDERS_DIR, ASSETS_DIR,
)
from backend.schemas import (
    CreateJobRequest, UpdateClipRequest, SettingsUpdateRequest,
    HardwareStatusResponse, JobProgressUpdate, JobStatus, OperatingMode,
    CropMode, CaptionStyle, LongVideoStrategy, VideoFormat, ResetPipelineRequest, ResetPipelineResponse,
    YouTubePublishRequest, YouTubeAuthStatusResponse,
    FacebookPublishRequest, FacebookStatusResponse,
    ComparisonFormat, ComparisonGame, ComparisonQuest, ComparisonQuestRequest, ComparisonRenderRequest,
    SocialMetadata, YouTubeMetadata, InstagramMetadata, FacebookMetadata
)
from backend.services.ingest import ingest_service
from backend.services.gemini_director import gemini_director
from backend.services.explainer import ExplainerService
from backend.services.creator_masker import audit_creator_overlays
from backend.services.ingest import parse_time_str
from backend.services.video_cropper import video_cropper
from backend.services.audio_processor import audio_processor
from backend.services.captioner import captioner_service
from backend.services import comparison_board, ranked_highlight, footage_library
from backend.services.comparison import ComparisonTimeline, commentary_passages
from backend.services.comparison_motion import COMPARISON_ASSETS, spoken_logo_frames, write_logo_motion
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

# Configure CORS (restrict to local Studio origins)
# TODO(security): add explicit origin allowlist entries if deployed behind a reverse proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

# Mount workspace directory for direct video/audio/asset streaming in frontend
app.mount("/workspace", StaticFiles(directory=str(WORKSPACE_DIR)), name="workspace")

# In-memory Job & WebSocket Connection State
JOBS_DB: Dict[str, Dict[str, Any]] = {}
ACTIVE_TASKS: Dict[str, asyncio.Task] = {}
JOBS_CACHE_FILE = WORKSPACE_DIR / "jobs_db.json"
COMPARISONS_DB: List[Dict[str, Any]] = []
COMPARISONS_CACHE_FILE = WORKSPACE_DIR / "comparisons_db.json"
_JOBS_DB_LOCK = threading.Lock()


def save_jobs_db():
    with _JOBS_DB_LOCK:
        try:
            tmp_file = JOBS_CACHE_FILE.with_suffix(".json.tmp")
            tmp_file.write_text(json.dumps(JOBS_DB, indent=2, default=str), encoding="utf-8")
            os.replace(tmp_file, JOBS_CACHE_FILE)
        except Exception as e:
            logger.warning(f"Could not persist JOBS_DB: {e}")


def load_jobs_db():
    global JOBS_DB
    with _JOBS_DB_LOCK:
        if JOBS_CACHE_FILE.exists():
            try:
                loaded = json.loads(JOBS_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    JOBS_DB.update(loaded)
                    logger.info(f"Loaded {len(loaded)} job(s) from {JOBS_CACHE_FILE}")
            except Exception as e:
                logger.warning(f"Could not load JOBS_DB from cache: {e}")


def save_comparisons_db():
    with _JOBS_DB_LOCK:
        try:
            tmp_file = COMPARISONS_CACHE_FILE.with_suffix(".json.tmp")
            tmp_file.write_text(json.dumps(COMPARISONS_DB, indent=2, default=str), encoding="utf-8")
            os.replace(tmp_file, COMPARISONS_CACHE_FILE)
        except Exception as e:
            logger.warning(f"Could not persist COMPARISONS_DB: {e}")


def load_comparisons_db():
    global COMPARISONS_DB
    with _JOBS_DB_LOCK:
        if COMPARISONS_CACHE_FILE.exists():
            try:
                loaded = json.loads(COMPARISONS_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    COMPARISONS_DB.clear()
                    COMPARISONS_DB.extend(loaded)
                    logger.info(f"Loaded {len(loaded)} comparison render(s) from {COMPARISONS_CACHE_FILE}")
            except Exception as e:
                logger.warning(f"Could not load COMPARISONS_DB: {e}")


load_jobs_db()
load_comparisons_db()


def _safe_id(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value or ""):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return value


def _extract_audio_or_silence(
    source_video: Path,
    output_wav: Path,
    duration_sec: float,
    start_sec: Optional[float] = None,
) -> None:
    """Extracts PCM audio from source_video, or generates matching silence if source lacks audio."""
    cmd = ["ffmpeg", "-y"]
    if start_sec is not None:
        cmd.extend(["-ss", str(start_sec)])
    cmd.extend(["-t", str(max(0.5, float(duration_sec))), "-i", str(source_video)])
    cmd.extend(["-vn", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(output_wav)])
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode == 0 and output_wav.exists() and output_wav.stat().st_size > 128:
        return

    logger.warning(f"No audio track extracted from {source_video.name}; generating silent audio track.")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", str(max(0.5, float(duration_sec))),
        "-c:a", "pcm_s16le",
        str(output_wav),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def clean_workspace_files(job_id: str = None, delete_all: bool = True) -> int:
    """Safely removes video downloads, proxies, renders, assets, and temp files, returning bytes freed."""
    freed_bytes = 0
    target_dirs = [DOWNLOADS_DIR, PROXIES_DIR, RENDERS_DIR, ASSETS_DIR, TEMP_DIR]

    for folder in target_dirs:
        if not folder.exists():
            continue
        try:
            for item in list(folder.iterdir()):
                if item.name == ".gitkeep":
                    continue
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
                                    if f == ".gitkeep":
                                        continue
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
            stale: List[WebSocket] = []
            for connection in list(self.active_connections[job_id]):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to send WS message (dropping dead socket): {e}")
                    stale.append(connection)
            for dead in stale:
                self.disconnect(job_id, dead)

manager = ConnectionManager()

def _detect_game_branding(job: Dict[str, Any], clip: Optional[Dict[str, Any]] = None) -> tuple[str, str]:
    """Determines display tag prefix ('GTA 5' / 'GTA 6' / 'GAMING') and badge label ('GTA V' / 'GTA VI' / 'GAMING')."""
    meta_title = str((job.get("metadata") or {}).get("title") or "")
    url_hint = str((job.get("request") or {}).get("url_or_path") or "")
    hook_hint = str((clip or {}).get("hook_text") or "")
    combined = f"{meta_title} {url_hint}".lower()

    if any(k in combined for k in ("gta 5", "gta v", "grand theft auto v", "oylsmbxtvm4")):
        return "GTA 5", "GTA V"
    if any(k in combined for k in ("gta 6", "gta vi", "grand theft auto vi", "vice city", "169zzvpxvvm")):
        return "GTA 6", "GTA VI"

    lower_all = f"{combined} {hook_hint}".lower()
    if any(k in lower_all for k in ("los santos", "franklin", "trevor", "michael", "lamar", "vagos", "simeon", "gta 5", "gta v")):
        return "GTA 5", "GTA V"
    if any(k in lower_all for k in ("vice city", "lucia", "jason", "leonida", "gta 6", "gta vi")):
        return "GTA 6", "GTA VI"
    return "GAMING", "GAMING"


def _resolve_watermark_settings(clip: Dict[str, Any], enable_watermark_masker: bool) -> tuple[Optional[str], bool, str]:
    """
    Returns (watermark_corner, mask_webcam, webcam_corner).
    Clean gameplay frames without third-party logos or webcams must NOT be blurred or badged.
    Always preserves the detected webcam_corner hint for FACECAM_SPLIT even when masker is off.
    """
    wm_info = clip.get("watermark_info") or {}
    if isinstance(wm_info, dict):
        detected = bool(wm_info.get("detected", False))
        label = str(wm_info.get("label") or "")
        corner_obj = wm_info.get("corner", "none")
    else:
        detected = bool(getattr(wm_info, "detected", False))
        label = str(getattr(wm_info, "label", "") or "")
        corner_obj = getattr(wm_info, "corner", "none")

    corner_raw = getattr(corner_obj, "value", str(corner_obj)) if corner_obj is not None else "none"
    corner_val = str(corner_raw).split(".")[-1].strip().lower()
    detected_corner = corner_val if corner_val not in ("none", "null", "") else "top_right"

    if not enable_watermark_masker:
        return None, False, detected_corner

    if not detected or corner_val in ("none", "null", ""):
        return None, False, detected_corner

    # Older reviews may detect an overlay without transcribing a label. Never treat that as clean.
    is_webcam = not label.strip() or any(tok in label.lower() for tok in ("webcam", "facecam", "cam", "streamer"))
    return corner_val, is_webcam, corner_val


def _probe_audio_duration(audio_path: Path) -> float:
    """Returns audio file duration in seconds via ffprobe, or 0.0 on failure."""
    if not audio_path or not audio_path.exists():
        return 0.0
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            text=True,
        ).strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0


def _synchronize_voice_and_render_span(
    voice_path: Path,
    beats_list: List[Dict[str, Any]],
    clip_dur: float,
    start_time: float,
    cut_start_sec: float,
    use_raw_offset: bool,
    max_source_dur: float,
    norm_voice_out: Path,
) -> tuple[Path, List[Dict[str, Any]], float]:
    """
    Prevents TTS narration from being chopped off by extending final beat / clip duration
    safely within `max_source_dur` and applying gentle FFmpeg atempo (<=1.28x) if needed.
    """
    render_beats = [dict(b) for b in (beats_list or [])]
    new_clip_dur = float(clip_dur)
    voice_dur = _probe_audio_duration(voice_path)
    if voice_dur <= 0.0:
        return voice_path, render_beats, new_clip_dur

    planned_dur = sum(float(b.get("duration", 8.0)) for b in render_beats) if len(render_beats) > 1 else new_clip_dur
    if voice_dur <= (planned_dur - 0.6):
        return voice_path, render_beats, new_clip_dur

    needed = max(0.0, (voice_dur + 1.1) - planned_dur)
    if needed > 0.0:
        if len(render_beats) > 1:
            last = render_beats[-1]
            b_start = float(last.get("start_time", 0.0))
            b_dur = float(last.get("duration", 8.0))
            act_start = (cut_start_sec + b_start) if use_raw_offset else b_start
            max_add = max(0.0, (max_source_dur - (act_start + b_dur) - 0.3)) if max_source_dur > 0 else 10.0
            add_sec = min(10.0, needed, max_add)
            if add_sec > 0.1:
                last["duration"] = round(b_dur + add_sec, 2)
        else:
            max_add = max(0.0, (max_source_dur - (start_time + new_clip_dur) - 0.3)) if max_source_dur > 0 else 10.0
            add_sec = min(10.0, needed, max_add)
            if add_sec > 0.1:
                new_clip_dur = round(new_clip_dur + add_sec, 2)

    actual_dur = sum(float(b.get("duration", 8.0)) for b in render_beats) if len(render_beats) > 1 else new_clip_dur
    if voice_dur > (actual_dur - 0.5) and actual_dur >= 3.0:
        rate = min(1.28, max(1.02, (voice_dur + 0.6) / actual_dur))
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(voice_path),
                    "-filter:a", f"atempo={rate:.4f}",
                    "-c:a", "pcm_s16le", "-ar", "48000",
                    str(norm_voice_out),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if norm_voice_out.exists() and norm_voice_out.stat().st_size > 1000:
                logger.info(
                    f"Synchronized voice ({voice_dur:.2f}s -> {voice_dur / rate:.2f}s @ {rate:.2f}x) "
                    f"to fit {actual_dur:.2f}s video without cutoffs."
                )
                return norm_voice_out, render_beats, new_clip_dur
        except Exception as ex:
            logger.warning(f"Voice atempo normalization skipped ({ex})")

    return voice_path, render_beats, new_clip_dur


# ------------------------------------------------------------------------------
# Clip Rendering Pipeline (Shared between Auto-Pilot and Manual Studio)
# ------------------------------------------------------------------------------
async def render_single_clip(job_id: str, clip_idx: int, total_clips: int = 1, progress_callback: Optional[Any] = None):
    job = JOBS_DB[job_id]
    clip = job["clips"][clip_idx]
    clip_id = clip["clip_id"]
    req = job["request"]
    clip_num = clip_idx + 1

    ranked = clip.get("clip_type") == "ranked_highlight"
    if not ranked:
        english_service = ExplainerService(gemini_director)
        migrated_english = await asyncio.to_thread(english_service.ensure_english_narration, clip)
        legacy_explainer_voice = clip.get("video_format") == VideoFormat.EXPLAINER and not str(
            clip.get("voice_path", "")
        ).endswith("_continuous_voice.wav")
        if migrated_english or legacy_explainer_voice or not clip.get("voice_path"):
            if clip.get("video_format") == VideoFormat.EXPLAINER:
                voice = await asyncio.to_thread(english_service.synthesize_narration, clip, job_id)
            else:
                voice = await asyncio.to_thread(
                    gemini_director.synthesize_voiceover, clip["commentary_script"], job_id, clip_id,
                    voice_name=clip.get("tts_voice", "Charon"), pacing=req.get("voiceover_pacing", "full_commentary"),
                    require_speech=True,
                )
            clip["voice_path"] = str(voice)
    req["target_language"] = "english"

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

    # 1. Video & Audio Framing (Multi-Beat Story Montage or Single Continuous Moment)
    crop_mode = CropMode(clip.get("crop_mode") or req.get("crop_mode") or "center_zoom")
    cropped_path = TEMP_DIR / f"{job_id}_{clip_id}_cropped.mp4"
    seg_audio = TEMP_DIR / f"{job_id}_{clip_id}_gameplay_raw.wav"
    watermark_corner, mask_webcam, webcam_corner = _resolve_watermark_settings(
        clip, bool(req.get("enable_watermark_masker", True))
    )
    beats_list = clip.get("beats") or []
    raw_dur = float(job["metadata"].get("duration", 0.0))
    use_raw_offset = bool(raw_path and raw_path.exists())
    max_source_dur = raw_dur if (use_raw_offset and raw_dur > 0) else cut_dur_sec
    norm_voice_tmp = TEMP_DIR / f"{job_id}_{clip_id}_voice_sync.wav"
    if ranked:
        sync_voice_path = None
    elif clip.get("video_format") == VideoFormat.EXPLAINER:
        if not clip.get("verification_passed"):
            raise ValueError("This explanation has not passed scene verification.")
        # Continuous commentary is already fitted to the montage. Never append unverified footage.
        sync_voice_path = Path(clip["voice_path"])
    else:
        sync_voice_path, beats_list, clip_dur = await asyncio.to_thread(
            _synchronize_voice_and_render_span,
            Path(clip["voice_path"]),
            beats_list,
            clip_dur,
            start_time,
            cut_start_sec,
            use_raw_offset,
            max_source_dur,
            norm_voice_tmp,
        )

    selected_windows = []
    if len(beats_list) > 1:
        for beat in beats_list:
            act_start = float(beat.get("start_time", 0.0)) + (cut_start_sec if use_raw_offset else 0.0)
            b_dur = float(beat.get("duration", 8.0))
            if max_source_dur > 0:
                b_dur = max(2.0, min(b_dur, max_source_dur - 1.0))
                if act_start >= max_source_dur - 1.0:
                    act_start = max(0.0, max_source_dur - b_dur - 0.5)
                elif act_start + b_dur > max_source_dur:
                    b_dur = max(2.0, max_source_dur - act_start - 0.25)
            selected_windows.append((act_start, b_dur))
    else:
        selected_windows = [(start_time, clip_dur)]

    # Saved footage keeps original source coordinates, including when a draft mixes several videos.
    beat_sources = [source_path] * len(selected_windows)
    for idx, beat in enumerate(beats_list):
        if beat.get("source_asset"):
            beat_sources[idx] = comparison_board.asset_path(beat["source_asset"])
            selected_windows[idx] = (beat["start_time"], beat["duration"])
    if len(selected_windows) == 1:
        source_path = beat_sources[0]
        start_time, clip_dur = selected_windows[0]
    regions_by_source = {}
    creator_regions = []
    if req.get("enable_watermark_masker", True):
        if progress_callback:
            progress_callback(f"Clip {clip_num}/{total_clips}: Checking all scenes for creator cameras and branding...")
        for path in dict.fromkeys(beat_sources):
            windows = [window for path_here, window in zip(beat_sources, selected_windows) if path == path_here]
            audit = await asyncio.to_thread(audit_creator_overlays, gemini_director, path, windows)
            regions_by_source[path] = audit.regions
            clip["watermark_info"] = audit.model_dump(mode="json")
        creator_regions = regions_by_source.get(source_path, [])
        if any(regions_by_source.values()) and crop_mode == CropMode.FACECAM_SPLIT:
            crop_mode = CropMode.CENTER_ZOOM
        save_jobs_db()
        # Source-coordinate masks replace decorative badges and label-dependent blur.
        watermark_corner, mask_webcam = None, False

    if len(beats_list) > 1:
        # Multi-Beat Story Montage Pipeline
        if progress_callback:
            progress_callback(f"Clip {clip_num}/{total_clips}: Assembling {len(beats_list)}-beat story montage ({crop_mode.value})...")
        logger.info(f"Assembling multi-beat story montage for {clip_id} with {len(beats_list)} beats...")

        beat_v_paths = []
        beat_a_paths = []
        import subprocess

        for b_idx, (act_start, b_dur) in enumerate(selected_windows):
            b_cropped = TEMP_DIR / f"{job_id}_{clip_id}_beat_{b_idx}_cropped.mp4"
            b_audio = TEMP_DIR / f"{job_id}_{clip_id}_beat_{b_idx}_audio.wav"

            rank_args = {}
            if ranked:
                beat = beats_list[b_idx]
                art = TEMP_DIR / f"{job_id}_{clip_id}_rank_{b_idx}_%d.png"
                game = clip.get("ranking_game", clip["hook_text"]).removeprefix("Ranking Funniest ").removesuffix(" Moments")
                plates = [Path(str(art) % frame) for frame in (0, 1)]
                for frame, plate in enumerate(plates):
                    await asyncio.to_thread(ranked_highlight.artwork, beats_list, b_idx, game, plate, reveal=bool(frame),
                                            title=clip["hook_text"] if clip.get("ranking_title") else "")
                rank_args = {"rank_overlay": art, "rank_wide": beat.get("wide", False), "focus_x": beat.get("focus_x", 0.5)}
            if clip.get("library_ids"):
                rank_args["output_fps"] = 60
            await asyncio.to_thread(
                video_cropper.crop_to_vertical,
                raw_video_path=beat_sources[b_idx],
                start_time=act_start,
                duration=b_dur,
                output_cropped_path=b_cropped,
                mode=crop_mode,
                mask_webcam=mask_webcam,
                webcam_corner=webcam_corner,
                creator_regions=regions_by_source.get(beat_sources[b_idx], creator_regions),
                **rank_args,
            )
            if ranked:
                for plate in plates:
                    plate.unlink(missing_ok=True)
            beat_v_paths.append(b_cropped)

            await asyncio.to_thread(
                _extract_audio_or_silence,
                beat_sources[b_idx],
                b_audio,
                b_dur,
                act_start,
            )
            beat_a_paths.append(b_audio)

        # Concat video beats
        v_list_file = TEMP_DIR / f"{job_id}_{clip_id}_v_concat.txt"
        v_list_file.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in beat_v_paths), encoding="utf-8")
        v_concat_res = subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(v_list_file),
            "-c", "copy",
            str(cropped_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if v_concat_res.returncode != 0 or not cropped_path.exists():
            raise RuntimeError(f"Failed to concatenate beat videos: {v_concat_res.stderr[:200]}")

        # Concat audio beats
        a_list_file = TEMP_DIR / f"{job_id}_{clip_id}_a_concat.txt"
        a_list_file.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in beat_a_paths), encoding="utf-8")
        a_concat_res = subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(a_list_file),
            "-c:a", "pcm_s16le", "-ar", "48000",
            str(seg_audio)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if a_concat_res.returncode != 0 or not seg_audio.exists():
            raise RuntimeError(f"Failed to concatenate beat audio: {a_concat_res.stderr[:200]}")

        # Cleanup intermediate beat files
        v_list_file.unlink(missing_ok=True)
        a_list_file.unlink(missing_ok=True)
        for p in beat_v_paths:
            p.unlink(missing_ok=True)
        for p in beat_a_paths:
            p.unlink(missing_ok=True)

    else:
        # Standard Single Continuous Moment
        if progress_callback:
            progress_callback(f"Clip {clip_num}/{total_clips}: Applying 16:9 landscape framing ({crop_mode.value})...")
        await asyncio.to_thread(
            video_cropper.crop_to_vertical,
            raw_video_path=source_path,
            start_time=start_time,
            duration=clip_dur,
            output_cropped_path=cropped_path,
            mode=crop_mode,
            mask_webcam=mask_webcam,
            webcam_corner=webcam_corner,
            creator_regions=creator_regions,
        )

        # 2. Extract Gameplay Audio Segment (or silent fallback)
        await asyncio.to_thread(
            _extract_audio_or_silence,
            source_path,
            seg_audio,
            clip_dur,
            start_time,
        )

    # 3. Strip Copyright Radio or Streamer Mic Voice via Demucs AI
    should_strip_voice = (
        req.get("strip_streamer_voice", True)
        or (not ranked and req.get("voiceover_pacing") == "full_commentary")
        or (req.get("copyright_guard", True) and clip.get("has_copyrighted_music", False))
    )
    if should_strip_voice:
        if progress_callback:
            progress_callback(f"Clip {clip_num}/{total_clips}: Demucs isolating SFX & removing streamer/radio voice...")
        clean_audio = TEMP_DIR / f"{job_id}_{clip_id}_clean_audio.wav"
        await asyncio.to_thread(audio_processor.strip_copyright_radio, seg_audio, clean_audio)
        seg_audio = clean_audio

    mixed_audio_path = TEMP_DIR / f"{job_id}_{clip_id}_mixed.wav"
    ass_path = None
    if ranked:
        await asyncio.to_thread(ranked_highlight.mix_sound, seg_audio, beats_list, mixed_audio_path, float(req.get("game_volume_boost", 1.5)))
    else:
        # 4. Duck and Mix Gameplay Audio under TTS Voiceover
        if progress_callback:
            progress_callback(f"Clip {clip_num}/{total_clips}: Mixing sidechain ducked audio (-16dB)...")
        voice_path = sync_voice_path
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
        target_lang = str(req.get("target_language", "english"))
        await asyncio.to_thread(
            captioner_service.generate_ass_subtitles,
            voice_path,
            ass_path,
            style=caption_style,
            target_language=target_lang,
            initial_prompt=str(clip.get("commentary_script") or ""),
        )

    # 6. Final Hardware Burn-in Render (M4 VideoToolbox / RTX 3050 NVENC)
    if progress_callback:
        progress_callback(f"Clip {clip_num}/{total_clips}: M4 hardware rendering final 1080x1920 60fps MP4...")
    overlay_path = None  # Callout rectangle blue box overlay disabled/removed

    tag_prefix, badge_label = _detect_game_branding(job, clip)

    # Generate attractive Top Topic Headline Banner if enabled
    topic_banner_path = None
    if not ranked and req.get("enable_topic_header", True):
        hook_text = clip.get("hook_text") or clip.get("hook_summary") or f"{tag_prefix} GAMEPLAY"
        hook_upper = hook_text.upper()
        if any(w in hook_upper for w in ["SECRET", "MYTH", "VAULT", "CARTEL", "LOST", "MYSTERY"]):
            cat_tag = f"{tag_prefix} • SECRET LORE"
        elif any(w in hook_upper for w in ["STUNT", "ESCAPE", "PURSUIT", "GETAWAY", "INSANE", "IMPOSSIBLE"]):
            cat_tag = f"{tag_prefix} • VIRAL MOMENT"
        elif any(w in hook_upper for w in ["DETAIL", "MISSED", "EASTER"]):
            cat_tag = f"{tag_prefix} • EASTER EGG"
        elif any(w in hook_upper for w in ["HEIST", "MISSION", "CONTRACT", "CHAPTER"]):
            cat_tag = f"{tag_prefix} • HEIST MISSION"
        else:
            cat_tag = f"{tag_prefix} • VIRAL REEL"

        topic_banner_path = await asyncio.to_thread(
            video_renderer.generate_topic_banner,
            hook_text=hook_text,
            job_id=job_id,
            clip_id=clip_id,
            category_tag=cat_tag
        )

    banner_y = 602 if crop_mode == CropMode.FACECAM_SPLIT else (140 if crop_mode == CropMode.ACTION_TRACK else 260)
    final_mp4 = await asyncio.to_thread(
        video_renderer.render_final_clip,
        cropped_video_path=cropped_path,
        mixed_audio_path=mixed_audio_path,
        ass_subtitles_path=ass_path,
        overlay_png_path=overlay_path,
        job_id=job_id,
        clip_id=clip_id,
        watermark_corner=watermark_corner,
        topic_banner_path=topic_banner_path,
        badge_label=badge_label,
        topic_banner_y=banner_y,
    )
    if norm_voice_tmp.exists():
        norm_voice_tmp.unlink(missing_ok=True)

    clip["rendered_video_path"] = str(final_mp4)
    clip["preview_url"] = f"/workspace/renders/{final_mp4.name}?v={int(time.time())}"
    if clip.get("library_ids"):
        clip["used_library_ids"] = list(clip["library_ids"])
    clip["status"] = "rendered"
    save_jobs_db()

# ------------------------------------------------------------------------------
# Asynchronous Job Execution Pipeline
# ------------------------------------------------------------------------------
async def execute_job_pipeline(job_id: str, library_source: dict | None = None):
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
        if library_source is not None:
            meta = dict(library_source)
        else:
            await send_progress(5, "Connecting to YouTube stream via yt-dlp...", JobStatus.INGESTING)
            meta = await asyncio.to_thread(
                ingest_service.download_or_link_video,
                url_or_path=req.url_or_path,
                job_id=job_id,
                progress_callback=lambda p, m: sync_cb(p, m, JobStatus.INGESTING)
            )
        job["metadata"] = meta
        raw_path = meta["raw_path"]

        if req.video_format == VideoFormat.EXPLAINER:
            # Explainer timestamps are absolute in the original source, across all scan windows.
            meta.update({
                "cut_path": raw_path, "is_cut": False, "cut_start_sec": 0.0,
                "cut_duration_sec": meta.get("duration", 0.0), "has_more_segments": False,
                "scan_start_sec": parse_time_str(req.cut_start_time), "video_format": "explainer",
            })
            await send_progress(28, "Explainer: scanning the source for complete stories and interesting topics...", JobStatus.ANALYZING)
            plan = await asyncio.to_thread(
                ExplainerService(gemini_director).analyze,
                source=Path(raw_path), source_title=meta.get("title", "Gameplay"),
                clip_count=req.clip_count, clip_length_range=req.clip_length_range,
                target_language=req.target_language.value, voice=req.tts_voice,
                topic=req.explainer_topic, scan_start=meta["scan_start_sec"],
                window_seconds=(req.cut_duration_mins or 10.0) * 60,
                progress_callback=lambda p, m: sync_cb(p, m, JobStatus.ANALYZING),
                main_story=library_source is not None,
            )
            meta["selection_summary"] = plan.overall_analysis
            job["metadata"] = meta
        else:
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

            plan = await asyncio.to_thread(
                ranked_highlight.analyze, gemini_director, Path(raw_path), meta.get("title", "Gameplay"),
                meta["cut_start_sec"], meta["cut_duration_sec"], req.clip_count, req.clip_length_range,
                req.enable_closeup_verify, lambda p, m: sync_cb(p, m, JobStatus.ANALYZING),
            )
        job["plan"] = plan.model_dump()
        job["clips"] = [c.model_dump() for c in plan.clips]
        job["candidate_pool"] = [c.model_dump() for c in getattr(plan, "candidate_pool", [])]

        # Enforce explicit user preset choices from CreateJobRequest over schema defaults
        req_crop = getattr(req.crop_mode, "value", str(req.crop_mode)) if getattr(req, "crop_mode", None) else None
        req_caption = getattr(req.caption_style, "value", str(req.caption_style)) if getattr(req, "caption_style", None) else None
        req_pacing = getattr(req.voiceover_pacing, "value", str(req.voiceover_pacing)) if getattr(req, "voiceover_pacing", None) else None
        for clip_dict in job["clips"] + job["candidate_pool"]:
            clip_dict["narration_language"] = "english"
            if req_crop:
                clip_dict["crop_mode"] = req_crop
            if req_caption:
                clip_dict["caption_style"] = req_caption
            if req_pacing:
                clip_dict["voiceover_pacing"] = req_pacing
            if getattr(req, "tts_voice", None):
                clip_dict["tts_voice"] = req.tts_voice

        if req.video_format == VideoFormat.EXPLAINER:
            await send_progress(70, "Generating full commentary aligned to verified scenes...", JobStatus.VOICING)
            for clip in job["clips"]:
                voice_path = await asyncio.to_thread(ExplainerService(gemini_director).synthesize_narration, clip, job_id)
                clip["voice_path"] = str(voice_path)
                clip["overlay_path"] = None

        # Step 5: Check Operating Mode (Manual Topic Selection vs Autonomous Batch Render)
        total_clips = len(job["clips"])
        is_manual_review = (getattr(req, "mode", OperatingMode.AUTO_PILOT) in (OperatingMode.MANUAL_STUDIO, "manual_studio"))
        if is_manual_review:
            logger.info(f"Job {job_id} is in MANUAL_STUDIO mode. {total_clips} topics extracted for user review.")
            await send_progress(
                100,
                f"Discovered {total_clips} verified explanations. Review and select which ones to render in Studio." if req.video_format == VideoFormat.EXPLAINER else f"Discovered {total_clips} ranked compilations. Review the moments and render in Studio.",
                JobStatus.COMPLETED,
                {"clips": job["clips"], "plan": job["plan"], "metadata": job.get("metadata", {})}
            )
            return

        # Autonomous AI Render of All Clips with Hardware Acceleration
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
    gemini_key = app_config.GEMINI_API_KEY
    return {
        "has_gemini_key": bool(gemini_key) or gemini_director.is_adc,
        "auth_mode": gemini_director.auth_mode,
        "is_adc": gemini_director.is_adc,
        "adc_project": gemini_director.project_id,
        "gemini_api_key_masked": "Google Cloud ADC Active" if gemini_director.is_adc else (f"...{gemini_key[-4:]}" if len(gemini_key) > 4 else "Not Set"),
        "has_meta_token": bool(app_config.META_ACCESS_TOKEN),
        "has_meta_page_id": bool(app_config.META_PAGE_ID),
        "has_instagram_account": bool(app_config.INSTAGRAM_ACCOUNT_ID),
        "director_model": app_config.DIRECTOR_MODEL,
        "tts_model": app_config.TTS_MODEL,
        "image_model": app_config.IMAGE_MODEL,
        "hardware": HARDWARE.get_status_badge()
    }


def _sanitize_env_value(val: str) -> str:
    if any(ch in val for ch in ("\r", "\n", "\x00")):
        raise HTTPException(status_code=400, detail="Settings values cannot contain newlines or control characters.")
    return val.strip()


@app.post("/api/settings")
async def update_settings(payload: SettingsUpdateRequest):
    env_file = BASE_DIR / ".env"
    existing_lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []

    updates: Dict[str, str] = {}
    if payload.gemini_api_key:
        updates["GEMINI_API_KEY"] = _sanitize_env_value(payload.gemini_api_key)
    if payload.meta_access_token:
        updates["META_ACCESS_TOKEN"] = _sanitize_env_value(payload.meta_access_token)
    if payload.meta_page_id:
        updates["META_PAGE_ID"] = _sanitize_env_value(payload.meta_page_id)
    if payload.instagram_account_id:
        updates["INSTAGRAM_ACCOUNT_ID"] = _sanitize_env_value(payload.instagram_account_id)
    if payload.public_tunnel_url:
        updates["PUBLIC_TUNNEL_URL"] = _sanitize_env_value(payload.public_tunnel_url)
    if payload.director_model:
        updates["DIRECTOR_MODEL"] = _sanitize_env_value(payload.director_model)
    if payload.tts_model:
        updates["TTS_MODEL"] = _sanitize_env_value(payload.tts_model)
    if payload.image_model:
        updates["IMAGE_MODEL"] = _sanitize_env_value(payload.image_model)

    new_lines: List[str] = []
    seen_keys: set[str] = set()
    for line in existing_lines:
        stripped = line.strip()
        if "=" in line and not stripped.startswith("#"):
            k, _ = line.split("=", 1)
            key = k.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in seen_keys:
            new_lines.append(f"{key}={val}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    app_config.reload_runtime_config()
    gemini_director.reload_client()
    meta_publisher.reload_config()
    youtube_publisher.reload_config()

    return {"status": "success", "message": "Settings updated and applied successfully"}

@app.post("/api/jobs")
async def create_job(request: CreateJobRequest):
    return queue_job(request)


def queue_job(request: CreateJobRequest, library_source: dict | None = None):
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

    task = asyncio.create_task(execute_job_pipeline(job_id, library_source))
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

    with footage_library.resetting_catalogue() if delete_all else nullcontext():
        # 2. Terminate only ffmpeg/yt-dlp child processes belonging to this workspace/job
        try:
            import sys
            target_needle = req_job_id if (not delete_all and req_job_id) else str(WORKSPACE_DIR)
            if sys.platform == "win32":
                ps_filter = target_needle.replace("'", "''")
                ps_cmd = (
                    f"Get-CimInstance Win32_Process | Where-Object {{ "
                    f"($_.Name -eq 'ffmpeg.exe' -or $_.Name -eq 'yt-dlp.exe') -and "
                    f"$_.CommandLine -like '*{ps_filter}*' }} | "
                    f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
                )
                subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)
            else:
                pgrep_res = subprocess.run(["pgrep", "-af", "ffmpeg|yt-dlp"], capture_output=True, text=True)
                for line in (pgrep_res.stdout or "").splitlines():
                    parts = line.split(None, 1)
                    if len(parts) == 2 and target_needle in parts[1]:
                        try:
                            os.kill(int(parts[0]), 9)
                        except ProcessLookupError:
                            pass
            logger.info(f"Terminated scoped child processes matching '{target_needle}'.")
        except Exception as e:
            logger.warning(f"Error terminating child processes: {e}")

        # 3. Clean files from downloads, proxies, renders, assets, and temp folders
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
        save_jobs_db()
        COMPARISONS_DB.clear()
        save_comparisons_db()

    msg = f"Complete workspace reset successful. All downloads, proxies, renders, and assets deleted. Freed {freed_mb} MB disk space."
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
    return list(JOBS_DB.values())

@app.get("/api/jobs/latest")
async def get_latest_job():
    if not JOBS_DB:
        return None
    return list(JOBS_DB.values())[-1]

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
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
    if target_clip.get("video_format") == VideoFormat.EXPLAINER:
        for field in ("start_time", "end_time", "commentary_script"):
            if field in update_data and update_data[field] != target_clip.get(field):
                raise HTTPException(status_code=400, detail="Re-extract the explanation to change verified scene boundaries or narration.")
    target_clip.update(update_data)
    save_jobs_db()

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

    if target_clip.get("clip_type") == "ranked_highlight":
        raise HTTPException(400, "Ranked highlights use gameplay audio and reveal sounds.")
    req = job.get("request") or {}
    pacing = req.get("voiceover_pacing", "full_commentary")
    await asyncio.to_thread(ExplainerService(gemini_director).ensure_english_narration, target_clip)
    req["target_language"] = "english"
    if target_clip.get("video_format") == VideoFormat.EXPLAINER:
        voice_path = await asyncio.to_thread(
            ExplainerService(gemini_director).synthesize_narration, target_clip, job_id,
        )
    else:
        voice_path = await asyncio.to_thread(
            gemini_director.synthesize_voiceover,
            script=target_clip["commentary_script"],
            job_id=job_id,
            clip_id=clip_id,
            voice_name=target_clip.get("tts_voice", "Charon"),
            pacing=pacing
        )
    target_clip["voice_path"] = str(voice_path)
    save_jobs_db()
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
        try:
            clips[clip_idx]["status"] = "rendering"
            save_jobs_db()
            await manager.broadcast(job_id, {"event": "clip_rendering", "clip_id": clip_id})
            await render_single_clip(job_id, clip_idx)
            await manager.broadcast(job_id, {
                "event": "clip_rendered",
                "clip_id": clip_id,
                "preview_url": clips[clip_idx]["preview_url"]
            })
        except Exception as e:
            logger.error(f"Error rendering clip {clip_id} in job {job_id}: {e}", exc_info=True)
            clips[clip_idx]["status"] = "error"
            save_jobs_db()
            await manager.broadcast(job_id, {
                "event": "clip_render_error",
                "clip_id": clip_id,
                "message": str(e)
            })

    background_tasks.add_task(run_render)
    return {"status": "success", "message": f"Rendering clip {clip_id} initiated."}

@app.get("/api/jobs/{job_id}/clips/{clip_id}/download")
async def download_clip_endpoint(job_id: str, clip_id: str):
    """Directly downloads rendered MP4 with Content-Disposition attachment header"""
    safe_job = _safe_id(job_id, "job_id")
    safe_clip = _safe_id(clip_id, "clip_id")
    final_file = (RENDERS_DIR / f"{safe_job}_{safe_clip}_final.mp4").resolve()
    if not final_file.is_relative_to(RENDERS_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid clip path")
    if not final_file.exists():
        raise HTTPException(status_code=404, detail="Rendered clip not found on disk")
    return FileResponse(
        path=str(final_file),
        media_type="video/mp4",
        filename=f"GTA6_{safe_clip}_Short.mp4"
    )

@app.get("/api/youtube/status", response_model=YouTubeAuthStatusResponse)
async def get_youtube_status():
    from backend.services.publishers.youtube_pub import youtube_publisher, TOKEN_FILE
    secrets_path = Path(app_config.YOUTUBE_CLIENT_SECRETS_FILE)
    
    channel_info = None
    if TOKEN_FILE.exists():
        try:
            channel_info = await asyncio.to_thread(youtube_publisher.get_channel_info)
        except Exception as e:
            logger.warning(f"Could not fetch YouTube channel info: {e}")

    return {
        "has_token": TOKEN_FILE.exists(),
        "has_client_secret": secrets_path.exists(),
        "client_secrets_path": str(secrets_path),
        "channel_title": channel_info.get("channel_title") if channel_info else None,
        "channel_avatar": channel_info.get("channel_avatar") if channel_info else None,
        "channel_handle": channel_info.get("channel_handle") if channel_info else None,
        "channel_id": channel_info.get("channel_id") if channel_info else None,
        "subscriber_count": channel_info.get("subscriber_count") if channel_info else None,
        "auth_url": youtube_publisher._current_auth_url if (not TOKEN_FILE.exists() and youtube_publisher._active_auth_server) else None,
    }

@app.post("/api/youtube/connect")
async def connect_youtube():
    from backend.services.publishers.youtube_pub import youtube_publisher, TOKEN_FILE
    if TOKEN_FILE.exists():
        info = await asyncio.to_thread(youtube_publisher.get_channel_info)
        if info:
            return {
                "status": "connected",
                "auth_url": None,
                "channel_title": info.get("channel_title"),
                "channel_avatar": info.get("channel_avatar"),
                "channel_handle": info.get("channel_handle"),
            }

    try:
        auth_url = await asyncio.to_thread(youtube_publisher.start_auth_flow)
        return {
            "status": "pending",
            "auth_url": auth_url,
            "message": "Auth listener started. Complete sign-in in browser."
        }
    except Exception as e:
        logger.error(f"YouTube authentication failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/youtube/disconnect")
async def disconnect_youtube():
    from backend.services.publishers.youtube_pub import youtube_publisher
    try:
        res = youtube_publisher.disconnect()
        return res
    except Exception as e:
        logger.error(f"YouTube disconnect failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/youtube/client-secret")
async def save_client_secret(payload: Dict[str, Any]):
    from backend.services.publishers.youtube_pub import youtube_publisher
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="Missing 'content' in payload")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in client_secret.json")
    if not isinstance(parsed, dict) or not ("installed" in parsed or "web" in parsed):
        raise HTTPException(status_code=400, detail="JSON must contain an 'installed' or 'web' OAuth client object.")

    secrets_path = Path(app_config.YOUTUBE_CLIENT_SECRETS_FILE)
    secrets_path.write_text(content, encoding="utf-8")
    youtube_publisher.reload_config()
    youtube_publisher.disconnect()
    return {"status": "success", "message": f"Saved client_secret.json to {secrets_path}"}

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
        res = await asyncio.to_thread(
            youtube_publisher.publish_short,
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
    token = app_config.META_ACCESS_TOKEN or os.getenv("META_ACCESS_TOKEN", "")
    page_id = app_config.META_PAGE_ID or os.getenv("META_PAGE_ID", "")
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
        res = await asyncio.to_thread(
            meta_publisher.publish_facebook_reel,
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
        res = await asyncio.to_thread(
            meta_publisher.publish_instagram_reel,
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
# Comparison Studio Endpoints (GTA 5/4 vs GTA 6)
# ------------------------------------------------------------------------------

app.include_router(footage_library.router)


@app.get("/api/library")
def get_library():
    result = footage_library.catalogue()
    uses = {}
    for job in list(JOBS_DB.values()):
        for clip in job.get("clips", []):
            for key in clip.get("used_library_ids", []):
                uses.setdefault(key, []).append({"title": clip["hook_text"], "url": clip["preview_url"]})
    for export in list(COMPARISONS_DB):
        if export.get("library_id"):
            uses.setdefault(export["library_id"], []).append({"title": export["hook_text"], "url": export["preview_url"]})
    for item in result["moments"]:
        item["uses"] = uses.get(item["id"], [])
    return result


def store_library_job(job):
    JOBS_DB[job["job_id"]] = job
    save_jobs_db()
    return job


@app.post("/api/library/projects")
async def build_saved_project(payload: footage_library.Lineup):
    return store_library_job(await asyncio.to_thread(footage_library.make_job, payload))


@app.post("/api/library/sources/{source_id}/story")
async def build_source_story(source_id: str):
    source = footage_library.full_story_source(source_id)
    request = CreateJobRequest(
        url_or_path=f"https://youtu.be/{source_id}", mode="manual_studio", video_format=VideoFormat.EXPLAINER,
        clip_count=1, cut_duration_mins=5,
    )
    return queue_job(request, source)


@app.post("/api/library/projects/{job_id}/{clip_id}/support")
async def insert_support(job_id: str, clip_id: str, payload: footage_library.Insert):
    job = JOBS_DB.get(job_id, {})
    clip = next((c for c in job.get("clips", []) if c["clip_id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Commentary project not found.")
    return store_library_job(await asyncio.to_thread(footage_library.with_support, job, clip, payload))


app.include_router(comparison_board.router)


@app.post("/api/comparison/render-pair")
async def render_reviewed_pair(payload: comparison_board.BoardRenderRequest):
    if payload.library_id:
        item = (await asyncio.to_thread(footage_library.selected, [payload.library_id]))[0]
        if item["asset"] != payload.gta6.asset:
            raise HTTPException(422, "Saved setup and reference source differ.")
    request = await asyncio.to_thread(comparison_board.prepare_render, payload)
    request.library_id = payload.library_id
    return await render_comparison_endpoint(request)


@app.post("/api/comparison/generate-quest", response_model=ComparisonQuest)
async def generate_comparison_quest_endpoint(payload: ComparisonQuestRequest):
    """
    Analyzes a GTA 6 clip using Gemini Vision and creates an actionable
    15-second 'Mission Quest Card' for the user to record in GTA 5 or GTA 4.
    """
    job_id = f"quest_{int(time.time())}"
    try:
        # 1. Download or link GTA 6 video
        meta = await asyncio.to_thread(
            ingest_service.download_or_link_video,
            url_or_path=payload.gta6_url_or_path,
            job_id=job_id
        )
        raw_path = meta["raw_path"]

        # 2. Cut segment for AI Vision analysis
        cut_res = await asyncio.to_thread(
            ingest_service.cut_video_segment,
            raw_video_path=raw_path,
            job_id=job_id,
            start_time_str=payload.start_time,
            duration_mins=max(0.5, payload.duration_sec / 60.0),
            auto_cut_long=True
        )
        cut_path = cut_res["cut_path"]

        # 3. Create lightweight 480p proxy
        proxy_path = await asyncio.to_thread(
            ingest_service.create_lightweight_proxy,
            raw_video_path=cut_path,
            job_id=job_id
        )

        # 4. Generate comparison quest with Gemini Vision
        quest = await asyncio.to_thread(
            gemini_director.analyze_gta6_and_generate_quest,
            proxy_path=proxy_path,
            base_game=payload.base_game.value,
            target_language=payload.target_language.value
        )
        return quest

    except Exception as e:
        logger.error(f"Error generating comparison quest: {e}", exc_info=True)
        # Return fallback quest so user is never blocked
        return gemini_director._generate_fallback_quest(payload.base_game.value, payload.target_language.value)

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB local recording ceiling


@app.post("/api/comparison/upload-recording")
async def upload_comparison_recording(file: UploadFile = File(...)):
    """Uploads the user's recorded GTA 5/4 gameplay MP4 for comparison pairing"""
    raw_name = Path((file.filename or "recording.mp4").replace("\\", "/")).name
    clean_stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).stem).strip("._") or "recording"
    ext = Path(raw_name).suffix.lower() or ".mp4"
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    safe_name = f"rec_{int(time.time())}_{uuid.uuid4().hex[:8]}_{clean_stem[:60]}{ext}"
    downloads_root = DOWNLOADS_DIR.resolve()
    dest_path = (downloads_root / safe_name).resolve()
    if not dest_path.is_relative_to(downloads_root):
        raise HTTPException(status_code=400, detail="Invalid upload filename")

    total_bytes = 0
    try:
        with open(dest_path, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Uploaded recording exceeds 2 GB limit")
                buffer.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        logger.info(f"Uploaded comparison recording to {dest_path} ({total_bytes / (1024*1024):.2f} MB)")
        return {
            "status": "success",
            "file_path": str(dest_path),
            "asset": dest_path.name,
            "filename": raw_name,
            "preview_url": f"/workspace/downloads/{dest_path.name}"
        }
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest_path.unlink(missing_ok=True)
        logger.error(f"Failed to save uploaded recording: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded recording")

@app.post("/api/comparison/render")
async def render_comparison_endpoint(payload: ComparisonRenderRequest):
    """
    Renders Top/Bottom (9:16 Shorts) or Side-by-Side (16:9 Long) comparison video
    with a centered VS mark and spoken commentary.
    """
    comp_id = f"comp_{uuid.uuid4().hex[:12]}"
    temp_files_to_clean = []

    try:
        # Helper to resolve input path (download if YouTube URL)
        async def resolve_video(url_or_path: str, tag: str) -> Path:
            if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
                m = await asyncio.to_thread(
                    ingest_service.download_or_link_video,
                    url_or_path=url_or_path,
                    job_id=f"{comp_id}_{tag}"
                )
                return Path(m["raw_path"])
            p = Path(url_or_path).expanduser().resolve()
            if not p.exists() or not p.is_file():
                raise HTTPException(status_code=400, detail=f"File not found: {url_or_path}")
            return p

        # 1. Resolve both video sources
        gta6_raw = await resolve_video(payload.gta6_url_or_path, "gta6")
        base_raw = await resolve_video(payload.base_game_url_or_path, "base")

        # Generate the spoken hook and game passages separately to get exact switch times.
        passages = commentary_passages(payload)
        script = " ".join(passages)
        voices = []
        durations = []
        for label, passage in zip(("hook", "older", "six"), passages):
            voice = await asyncio.to_thread(
                gemini_director.synthesize_voiceover,
                script=passage,
                job_id=comp_id,
                clip_id=label,
                voice_name=payload.tts_voice,
                pacing="full_commentary",
                require_speech=True,
            )
            temp_files_to_clean.append(voice)
            voices.append(voice)
            durations.append(await asyncio.to_thread(_probe_audio_duration, voice))
        if min(durations) <= 0:
            raise RuntimeError("Could not measure the comparison narration.")

        gta6_dur = max(5.0, min(60.0, payload.gta6_duration_sec))
        base_dur = max(5.0, min(60.0, payload.base_game_duration_sec))
        if durations[0] >= min(base_dur, gta6_dur):
            raise HTTPException(status_code=400, detail="Shorten the spoken hook or select longer clips.")
        timeline = ComparisonTimeline.from_durations(*durations, base_dur, gta6_dur)
        hook_words = await asyncio.to_thread(captioner_service.transcribe_words, voices[0], initial_prompt=passages[0])
        logo_frames = spoken_logo_frames(hook_words, payload.base_game.value, timeline.hook)
        slide_frame = max(timeline.hook, *(frame + 16 for frame in logo_frames if frame is not None), 0)
        logo_movies = {}
        for game, frame in zip((payload.base_game.value, "gta6"), logo_frames):
            if frame is None:
                continue
            movie = TEMP_DIR / f"{comp_id}_{game}_logo.mov"
            temp_files_to_clean.append(movie)
            await asyncio.to_thread(write_logo_motion, COMPARISON_ASSETS / f"{game}.png", movie, frame, slide_frame)
            logo_movies[game] = movie
        logger.info("Comparison %s logo pops at frames %s, slide starts at %s", comp_id, logo_frames, slide_frame)

        async def trim_clip(src_path: Path, start_str: str, dur_sec: float, tag: str) -> Path:
            out_clip = TEMP_DIR / f"{comp_id}_{tag}_trimmed.mp4"
            temp_files_to_clean.append(out_clip)
            cmd = [
                "ffmpeg", "-y",
                "-ss", start_str,
                "-i", str(src_path),
                "-t", str(dur_sec),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                str(out_clip)
            ]
            await asyncio.to_thread(subprocess.run, cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return out_clip

        gta6_trimmed = await trim_clip(gta6_raw, payload.gta6_start_time, gta6_dur, "gta6")
        base_trimmed = await trim_clip(base_raw, payload.base_game_start_time, base_dur, "base")

        # Keep each game's sound with its moving panel. Use the older game's audio during the hook.
        base_audio = TEMP_DIR / f"{comp_id}_base_audio.wav"
        gta6_audio = TEMP_DIR / f"{comp_id}_gta6_audio.wav"
        voice_path = TEMP_DIR / f"{comp_id}_narration.wav"
        gameplay = TEMP_DIR / f"{comp_id}_gameplay.wav"
        mixed_audio = TEMP_DIR / f"{comp_id}_mixed.wav"
        temp_files_to_clean.extend([base_audio, gta6_audio, voice_path, gameplay, mixed_audio])
        await asyncio.to_thread(_extract_audio_or_silence, base_trimmed, base_audio, base_dur)
        await asyncio.to_thread(_extract_audio_or_silence, gta6_trimmed, gta6_audio, gta6_dur)
        await asyncio.to_thread(timeline.assemble_audio, voices, base_audio, gta6_audio, voice_path, gameplay)
        await asyncio.to_thread(audio_processor.duck_and_mix_audio, gameplay, voice_path, mixed_audio, -16.0, 1.4)

        # 5. Generate word-level ASS subtitles
        ass_path = TEMP_DIR / f"{comp_id}_captions.ass"
        temp_files_to_clean.append(ass_path)
        is_landscape_comp = payload.format.value == "long_side_by_side"
        await asyncio.to_thread(
            captioner_service.generate_ass_subtitles,
            voice_path,
            ass_path,
            style=payload.caption_style,
            initial_prompt=script,
            play_res_x=1920 if is_landscape_comp else 1080,
            play_res_y=1080 if is_landscape_comp else 1920,
        )

        title_path = TEMP_DIR / f"{comp_id}_title.png"
        temp_files_to_clean.append(title_path)
        await asyncio.to_thread(video_renderer.write_comparison_title, payload.hook_text.strip() or passages[0], title_path)

        final_mp4 = RENDERS_DIR / f"{comp_id}_comparison_{payload.format.value}.mp4"
        await asyncio.to_thread(
            video_renderer.render_comparison_clip,
            base_video_path=base_trimmed,
            gta6_video_path=gta6_trimmed,
            mixed_audio_path=mixed_audio,
            output_path=final_mp4,
            comparison_format=payload.format.value,
            base_game=payload.base_game.value,
            ass_subtitles_path=ass_path,
            timeline=timeline,
            logo_frames=logo_frames,
            logo_movies=logo_movies,
            slide_frame=slide_frame,
            title_path=title_path,
        )

        base_tag = "GTA V" if payload.base_game.value == "gta5" else "GTA IV"
        result_payload = {
            "status": "completed",
            "comp_id": comp_id,
            "format": payload.format.value,
            "base_game": payload.base_game.value,
            "hook_text": payload.hook_text,
            "commentary_script": script,
            "rendered_video_path": str(final_mp4),
            "preview_url": f"/workspace/renders/{final_mp4.name}?v={int(time.time())}",
            "created_at": int(time.time()),
            "social_metadata": {
                "youtube": {
                    "title": f"{payload.hook_text} 🤯 #Shorts #GTA6 #{base_tag.replace(' ', '')}",
                    "description": f"Ultimate side-by-side comparison between {base_tag} and GTA 6! {script} #GTA6 #Gaming #Shorts",
                    "tags": ["GTA6", base_tag.replace(' ', ''), "Gaming", "Shorts", "Comparison", "Rockstar Games"],
                    "privacy": "public"
                },
                "instagram": {
                    "caption": f"{payload.hook_text}! Which game has better physics? 🔥 Tag your squad! #gta6 #gaming #reels #rockstargames",
                    "hashtags": ["#gta6", "#gaming", "#reels", "#rockstargames", "#gtacomparison"]
                },
                "facebook": {
                    "caption": f"{payload.hook_text}! Detailed comparison breakdown.",
                    "hashtags": ["#GTA6", "#GamingReels"]
                }
            }
        }
        if payload.library_id:
            result_payload["library_id"] = payload.library_id
        COMPARISONS_DB.append(result_payload)
        save_comparisons_db()
        return result_payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rendering comparison: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for tf in temp_files_to_clean:
            try:
                if tf and tf.exists():
                    tf.unlink(missing_ok=True)
            except Exception:
                pass

@app.get("/api/comparison/list")
async def list_comparisons():
    """Returns all saved comparison renders (newest first) for display inside the app."""
    return list(reversed(COMPARISONS_DB))


# ------------------------------------------------------------------------------
# Real-Time WebSocket Progress Pipeline
# ------------------------------------------------------------------------------

@app.websocket("/ws/progress/{job_id}")
async def websocket_progress_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
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
        pass
    except Exception as e:
        logger.debug(f"WebSocket closed for {job_id}: {e}")
    finally:
        manager.disconnect(job_id, websocket)
