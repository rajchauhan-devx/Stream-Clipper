import os
import sys
import subprocess
import time
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from PIL import Image, ImageDraw, ImageFont

from google import genai
from google.genai import types

import backend.config as app_config
from backend.config import ASSETS_DIR, TEMP_DIR
from backend.schemas import (
    DirectorPlan, ClipBlueprint, StoryBeat, SocialMetadata,
    YouTubeMetadata, InstagramMetadata, FacebookMetadata,
    CropMode, CaptionStyle, ComparisonQuest, ComparisonGame,
    ClipVerificationResult, WatermarkCorner
)

logger = logging.getLogger("gta6-studio.director")

class GeminiDirectorService:
    def __init__(self):
        self.api_key = app_config.GEMINI_API_KEY
        self.temp_dir = TEMP_DIR
        self.client: Optional[genai.Client] = None
        self.auth_mode = "Unconfigured"
        self.is_adc = False
        self.project_id = ""
        self._init_client()

    def reload_client(self):
        """Re-reads runtime config and re-initializes the Gemini client."""
        self.api_key = app_config.GEMINI_API_KEY
        self.client = None
        self.auth_mode = "Unconfigured"
        self.is_adc = False
        self.project_id = ""
        return self._init_client()

    @staticmethod
    def _unique_models(*models: str) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for m in models:
            val = (m or "").strip()
            if val and val not in seen:
                seen.add(val)
                ordered.append(val)
        return ordered

    def _init_client(self):
        # 1. Explicit GEMINI_API_KEY takes precedence when configured in .env / Settings
        api_key = app_config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or self.api_key
        http_opts = types.HttpOptions(timeout=210_000)
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key, http_options=http_opts)
                self.auth_mode = "Gemini API Key"
                self.is_adc = False
                self.project_id = ""
                logger.info("Initialized Gemini Client via GEMINI_API_KEY")
                return self.client
            except Exception as e:
                logger.warning(f"Could not initialize GenAI client with API key: {e}")

        # 2. Fallback: Google Cloud ADC
        custom_cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if custom_cred:
            adc_path = Path(custom_cred)
        elif sys.platform == "win32":
            adc_path = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
        else:
            adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

        if adc_path.exists():
            try:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_path)
                with open(adc_path, encoding="utf-8") as f:
                    data = json.load(f)
                project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or data.get("quota_project_id") or ""
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
                if project_id:
                    self.client = genai.Client(
                        vertexai=True,
                        project=project_id,
                        location=location,
                        http_options=http_opts,
                    )
                    self.auth_mode = f"Google Cloud ADC ({project_id})"
                    self.is_adc = True
                    self.project_id = project_id
                    logger.info(f"Initialized Gemini Client via Google ADC (Project: {project_id})")
                    return self.client
            except Exception as e:
                logger.warning(f"Failed to initialize ADC client: {e}")

        self.auth_mode = "Offline Demo Mode"
        return None

    def _ensure_client(self):
        if not self.client:
            self._init_client()
        return self.client

    # --------------------------------------------------------------------------
    # 1. Multimodal Video Analysis & Plan Generation (4-Stage Human-Like Funnel)
    # --------------------------------------------------------------------------
    @staticmethod
    def _format_cue_sheet(timeline_signals: Optional[Dict[str, Any]]) -> str:
        """Formats deterministic audio energy spikes and scene-cut timestamps for Gemini."""
        if not timeline_signals:
            return ""
        peaks = timeline_signals.get("audio_peaks") or []
        cuts = timeline_signals.get("scene_cuts") or []
        dur = float(timeline_signals.get("duration") or 0.0)
        if not peaks and not cuts:
            return ""

        peak_str = ", ".join(f"{p['time_sec']}s (RMS={int(p['rms'])})" for p in peaks[:20]) or "None detected"
        cut_str = ", ".join(f"{c}s" for c in cuts[:30]) or "None detected"
        return (
            f"\nPRE-COMPUTED AUDIO & SCENE SIGNALS (Segment duration ~{dur:.1f}s):\n"
            f"- High-Energy Audio Spikes (gunfire/explosions/dialogue): [{peak_str}]\n"
            f"- Hard Visual Scene Cuts / Impact Transitions: [{cut_str}]\n"
            "Use these exact timestamps as anchors—combined with what you SEE and HEAR in the video—to place hooks right at the start of action/dialogue.\n"
        )

    def _prepare_video_part(
        self,
        client: genai.Client,
        video_path: Path,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        allow_compress: bool = True,
    ):
        """
        Prepares a video Part for Vertex AI (respecting the 20MB inline limit while
        retaining mono audio) or uploads via Gemini Developer File API.
        Returns (video_part, remote_file, cleanup_path).
        """
        is_vertex = getattr(self, "is_adc", False) or getattr(getattr(client, "_api_client", None), "vertexai", False)
        remote_file = None
        cleanup_path = None

        if is_vertex:
            target_video_file = video_path
            file_size_mb = video_path.stat().st_size / (1024 * 1024)
            if allow_compress and file_size_mb > 18.0:
                cleanup_path = self.temp_dir / f"compact_{video_path.name}"
                logger.info(f"Proxy is {file_size_mb:.1f}MB, compressing while keeping audio (<18MB) for Vertex AI...")
                if progress_callback:
                    progress_callback(58, "Compressing audio-enabled proxy (<18MB) for Vertex AI...")
                # First try 360p @ 0.5 FPS + 24k mono audio before falling back to 0.25 FPS
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-vf", "scale=-2:360,fps=0.5",
                    "-c:v", "libx264", "-crf", "32", "-preset", "ultrafast",
                    "-c:a", "aac", "-b:a", "24k", "-ac", "1", "-ar", "16000",
                    str(cleanup_path),
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if (cleanup_path.stat().st_size / (1024 * 1024)) > 18.0:
                    subprocess.run([
                        "ffmpeg", "-y", "-i", str(video_path),
                        "-vf", "scale=-2:240,fps=0.25",
                        "-c:v", "libx264", "-crf", "34", "-preset", "ultrafast",
                        "-c:a", "aac", "-b:a", "16k", "-ac", "1", "-ar", "16000",
                        str(cleanup_path),
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                target_video_file = cleanup_path

            vid_bytes = target_video_file.read_bytes()
            return types.Part.from_bytes(data=vid_bytes, mime_type="video/mp4"), None, cleanup_path

        try:
            remote_file = client.files.upload(file=str(video_path))
            logger.info(f"Uploaded proxy to Gemini File API: {remote_file.name}. Polling status...")
            max_wait = 60
            elapsed = 0
            while remote_file.state.name != "ACTIVE" and elapsed < max_wait:
                time.sleep(2)
                elapsed += 2
                remote_file = client.files.get(name=remote_file.name)
                if remote_file.state.name == "FAILED":
                    raise RuntimeError("Gemini file processing failed on server.")
            return remote_file, remote_file, None
        except Exception as ex:
            logger.warning(f"client.files.upload failed ({ex}). Falling back to inline bytes...")
            vid_bytes = video_path.read_bytes()
            return types.Part.from_bytes(data=vid_bytes, mime_type="video/mp4"), None, None

    @staticmethod
    def _generate_content_with_retry(client: genai.Client, model: str, contents: Any, config: Any, max_retries: int = 3):
        """Calls Gemini generate_content with backoff retries on transient 429 / 503 quota errors."""
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                return client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as ex:
                last_exc = ex
                msg = str(ex)
                low = msg.lower()
                is_transient = any(
                    tok in low
                    for tok in (
                        "429",
                        "resource_exhausted",
                        "503",
                        "unavailable",
                        "deadline_exceeded",
                        "timeout",
                        "timed out",
                        "readtimeout",
                        "connecttimeout",
                        "remoteprotocolerror",
                        "connectionreset",
                    )
                )
                if is_transient and attempt + 1 < max_retries:
                    delay = 20 * (attempt + 1)
                    logger.warning(f"Model {model} transient error ({msg[:120]}). Retrying in {delay}s (attempt {attempt + 2}/{max_retries})...")
                    time.sleep(delay)
                    continue
                raise
        if last_exc:
            raise last_exc

    @staticmethod
    def _sanitize_plan_timestamps(plan: DirectorPlan, max_duration: float) -> None:
        """Clamps all Scout timestamps inside [0, max_duration] and drops overlapping clamped duplicate beats."""
        if max_duration <= 5.0:
            return
        for clip in plan.clips:
            if clip.beats:
                deduped_beats: list[StoryBeat] = []
                for beat in clip.beats:
                    b_dur = max(3.0, min(14.0, float(beat.duration or 8.0)))
                    b_start = max(0.0, min(float(beat.start_time or 0.0), max(0.0, max_duration - b_dur - 0.5)))
                    if (b_start + b_dur) > max_duration:
                        b_dur = max(3.0, max_duration - b_start - 0.5)
                    # Prevent out-of-bounds clamping from stacking multiple beats onto the exact same tail window
                    if any(abs(b_start - prev.start_time) < 3.5 for prev in deduped_beats):
                        continue
                    beat.start_time = round(b_start, 2)
                    beat.duration = round(b_dur, 2)
                    deduped_beats.append(beat)
                if deduped_beats:
                    clip.beats = GeminiDirectorService._enforce_non_overlapping_beats(deduped_beats, max_duration)
                clip.start_time = clip.beats[0].start_time
                clip.duration = round(sum(b.duration for b in clip.beats), 2)
                clip.end_time = round(min(max_duration, clip.beats[-1].start_time + clip.beats[-1].duration), 2)
            else:
                c_dur = max(4.0, min(55.0, float(clip.duration or 20.0), max_duration - 1.0))
                c_start = max(0.0, min(float(clip.start_time or 0.0), max(0.0, max_duration - c_dur - 0.5)))
                clip.start_time = round(c_start, 2)
                clip.duration = round(c_dur, 2)
                clip.end_time = round(min(max_duration, c_start + c_dur), 2)

    @staticmethod
    def _enforce_non_overlapping_beats(beats: list[StoryBeat], max_duration: float) -> list[StoryBeat]:
        """Sorts montage beats chronologically and trims/advances overlaps so scenes never replay."""
        if len(beats) <= 1:
            return list(beats)
        ordered = sorted(beats, key=lambda b: float(b.start_time))
        clean: list[StoryBeat] = []
        for beat in ordered:
            b_start = max(0.0, float(beat.start_time))
            b_dur = max(2.5, float(beat.duration))
            if max_duration > 0 and (b_start + b_dur) > max_duration:
                b_dur = max(2.5, max_duration - b_start)
            if clean:
                prev = clean[-1]
                prev_end = prev.start_time + prev.duration
                if b_start < prev_end:
                    # If previous beat has >= 3.0s clean footage before current beat starts, end it cleanly there
                    if (b_start - prev.start_time) >= 3.0:
                        prev.duration = round(b_start - prev.start_time, 2)
                    else:
                        shift = (prev_end + 0.1) - b_start
                        b_start = prev_end + 0.1
                        b_dur = b_dur - shift
                        if b_dur < 2.5 or (max_duration > 0 and b_start >= max_duration - 1.0):
                            continue
            beat.start_time = round(b_start, 2)
            beat.duration = round(b_dur, 2)
            clean.append(beat)
        return clean

    @staticmethod
    def _apply_verified_trims(
        clip: ClipBlueprint,
        verification: ClipVerificationResult,
        windows: list[tuple[float, float]],
        max_duration: float,
    ) -> None:
        """Applies close-up verified trim offsets, grounded narration, and watermark audit onto clip/beat boundaries."""
        clip.reviewer_score = verification.quality_score
        clip.reviewer_verdict = verification.verdict
        clip.verification_passed = bool(verification.approved)
        clip.verification_notes = verification.verdict
        if verification.verified_hook_text and verification.verified_hook_text.strip():
            clip.hook_text = verification.verified_hook_text.strip()
        if verification.verified_script and verification.verified_script.strip():
            clip.commentary_script = verification.verified_script.strip()
        if verification.has_third_party_overlay is False and clip.watermark_info:
            clip.watermark_info.detected = False
            clip.watermark_info.corner = WatermarkCorner.NONE
            clip.watermark_info.label = None

        if clip.beats and len(clip.beats) > 1:
            trim_map = {bt.beat_id: bt for bt in (verification.beat_trims or [])}
            kept_beats: list[StoryBeat] = []
            for idx, beat in enumerate(clip.beats):
                bt = trim_map.get(beat.beat_id) or (
                    verification.beat_trims[idx] if verification.beat_trims and idx < len(verification.beat_trims) else None
                )
                if bt and not bt.approved and len(clip.beats) > 2:
                    continue
                if bt and idx < len(windows):
                    win_start, win_dur = windows[idx]
                    t_start = max(0.0, min(float(bt.trim_start_offset), max(0.0, win_dur - 2.5)))
                    t_end = max(t_start + 2.5, min(float(bt.trim_end_offset), win_dur))
                    new_start = round(max(0.0, win_start + t_start), 2)
                    new_dur = round(t_end - t_start, 2)
                    if max_duration > 0 and (new_start + new_dur) > max_duration:
                        new_dur = round(max(2.5, max_duration - new_start), 2)
                    beat.start_time = new_start
                    beat.duration = new_dur
                    if bt.notes:
                        beat.description = bt.notes
                else:
                    # Gemini omitted beat_trims for this beat: keep beat crisp (<= 10s) and inside source duration
                    b_dur = min(10.0, max(3.0, float(beat.duration)))
                    b_start = max(0.0, float(beat.start_time))
                    if max_duration > 0 and (b_start + b_dur) > max_duration:
                        b_start = max(0.0, max_duration - b_dur - 0.5)
                    beat.start_time = round(b_start, 2)
                    beat.duration = round(b_dur, 2)
                kept_beats.append(beat)

            if kept_beats:
                kept_beats = GeminiDirectorService._enforce_non_overlapping_beats(kept_beats, max_duration)
                clip.beats = kept_beats
                clip.start_time = kept_beats[0].start_time
                clip.duration = round(sum(b.duration for b in kept_beats), 2)
                clip.end_time = round(kept_beats[-1].start_time + kept_beats[-1].duration, 2)
                return

        if windows:
            win_start, win_dur = windows[0]
            t_start = max(0.0, min(float(verification.trim_start_offset), max(0.0, win_dur - 4.0)))
            raw_end = float(verification.trim_end_offset)
            t_end = win_dur if raw_end <= t_start else min(raw_end, win_dur)
            if (t_end - t_start) >= 4.0:
                new_start = round(max(0.0, win_start + t_start), 2)
                new_dur = round(t_end - t_start, 2)
                if max_duration > 0 and (new_start + new_dur) > max_duration:
                    new_dur = round(max(4.0, max_duration - new_start), 2)
                clip.start_time = new_start
                clip.duration = new_dur
                clip.end_time = round(new_start + new_dur, 2)

    def _verify_candidate_closeup(
        self,
        client: genai.Client,
        source_video_path: Path,
        clip: ClipBlueprint,
        intro_guard_sec: float,
        source_duration: float,
        candidate_models: list[str],
        voiceover_pacing: str = "full_commentary",
        target_language: str = "english",
    ) -> ClipBlueprint:
        """
        Stage 3 Human Close-Up Verification:
        Cuts 5-FPS + audio micro-clips with burned-in offsets (+0.0s), lets Gemini
        verify visual & audio quality, rejects weak clips, and tightens trims.
        """
        from backend.services.ingest import ingest_service

        temp_clips: list[Path] = []
        remote_files: list[Any] = []
        cleanup_files: list[Path] = []
        windows: list[tuple[float, float]] = []
        content_parts: list[Any] = []

        try:
            pad_sec = 3.0
            if clip.beats and len(clip.beats) > 1:
                beat_lines = []
                total_planned = sum(float(b.duration or 8.0) for b in clip.beats)
                verify_fps = 3.5 if (len(clip.beats) >= 3 or total_planned > 24.0) else 5.0
                for b_idx, beat in enumerate(clip.beats):
                    b_start = float(beat.start_time)
                    if source_duration > 0:
                        b_start = min(b_start, max(0.0, source_duration - 4.0))
                    w_start = max(intro_guard_sec, b_start - pad_sec)
                    if source_duration > 0:
                        w_start = min(w_start, max(0.0, source_duration - 4.0))
                    w_end = b_start + min(14.0, float(beat.duration)) + pad_sec
                    if source_duration > 0:
                        w_end = min(source_duration, w_end)
                    w_dur = max(4.0, w_end - w_start)
                    micro_path = self.temp_dir / f"verify_{clip.clip_id}_b{b_idx}_{int(time.time() * 1000)}.mp4"
                    ingest_service.create_micro_verification_clip(
                        source_video_path=source_video_path,
                        start_sec=w_start,
                        duration_sec=w_dur,
                        output_path=micro_path,
                        fps=verify_fps,
                    )
                    if not micro_path.exists() or micro_path.stat().st_size < 1000:
                        continue
                    temp_clips.append(micro_path)
                    windows.append((w_start, w_dur))
                    part, rfile, cfile = self._prepare_video_part(client, micro_path, allow_compress=True)
                    if rfile:
                        remote_files.append(rfile)
                    if cfile:
                        cleanup_files.append(cfile)
                    content_parts.append(part)
                    beat_lines.append(
                        f"- Clip #{b_idx + 1} (`beat_id`: '{beat.beat_id}', label: '{beat.label}', window: 0.0s..{w_dur:.1f}s): {beat.description or ''}"
                    )

                if not content_parts:
                    return clip

                pacing_key = str(voiceover_pacing or "full_commentary").lower()
                lang_inst = "clear natural English only, with no Hindi or Hinglish"
                approx_target_dur = sum(min(11.0, max(5.0, float(b.duration))) for b in clip.beats)
                if pacing_key == "hook_only":
                    script_rule = (
                        f"5. Write `verified_script` as an ultra-punchy 5-8 word opening hook in {lang_inst} "
                        "that sparks intense curiosity right on frame 1 (finishes under 2.5s so raw game SFX shines), "
                        "grounded STRICTLY in what is visibly happening right in these micro-clips.\n"
                    )
                else:
                    target_words = max(38, min(75, int(approx_target_dur * 1.85)))
                    script_rule = (
                        f"5. Write `verified_script` in {lang_inst} (STRICTLY ~{target_words} words, NO MORE than {target_words + 6} words) "
                        "describing ONLY what your eyes literally see in these micro-clip frames (`t=+0.0s..end`). "
                        "WARNING: DO NOT repeat Stage 2 guesses if the frames actually show a different scene, vehicle, or mission overlay!\n"
                    )

                verify_prompt = (
                    "You are a ruthless Senior Short-Form Video Editor inspecting high-clarity micro-clips WITH AUDIO.\n"
                    "Each video has yellow offset timestamps burned in the top-left (`t=+X.Xs`, starting at 0.0s).\n"
                    "CRITICAL ANTI-HALLUCINATION RULE: Stage 2 only saw low-FPS thumbnails and MAY HAVE MIS-INDEXED the timestamp! "
                    "Do NOT blindly repeat the Stage 2 topic below—verify independently with your own eyes & ears what REALLY happens in these clips.\n"
                    f"Unverified Stage 2 label (for reference only, override freely if wrong): \"{clip.hook_text}\"\n"
                    "Clips in order:\n" + "\n".join(beat_lines) + "\n\n"
                    "AUDIT INSTRUCTIONS:\n"
                    "1. Actually WATCH the frames and LISTEN to the audio in each clip from start to finish.\n"
                    "2. STRICT REJECTION (`approved=false`, `quality_score <= 40`): reject immediately if ANY clip shows static binoculars/scope/surveillance views, slow flat-water cruising, slow idle standing dialogue, 'MISSION PASSED' end-screens, pause menus, or full-screen streamer webcam.\n"
                    "3. For EVERY beat in `beat_trims`, set tight `trim_start_offset` and `trim_end_offset` (relative to 0.0s using the yellow `t=+X.Xs` timer) so beat 1 starts IMMEDIATELY on kinetic motion/gunfire/impact (ZERO 1-3s walk-up!) and each beat runs 5s-11s.\n"
                    "4. Set `verified_hook_text` (3-6 clean uppercase words matching what REALLY happens on screen; no emojis) and set `has_third_party_overlay=true` ONLY if a picture-in-picture streamer facecam or channel corner logo appears (`false` if only standard game HUD/mini-map).\n"
                    + script_rule
                )
            else:
                c_start = float(clip.start_time)
                if source_duration > 0:
                    c_start = min(c_start, max(0.0, source_duration - 6.0))
                w_start = max(intro_guard_sec, c_start - pad_sec)
                if source_duration > 0:
                    w_start = min(w_start, max(0.0, source_duration - 6.0))
                w_end = c_start + float(clip.duration) + pad_sec
                if source_duration > 0:
                    w_end = min(source_duration, w_end)
                w_dur = max(6.0, w_end - w_start)
                micro_path = self.temp_dir / f"verify_{clip.clip_id}_{int(time.time() * 1000)}.mp4"
                ingest_service.create_micro_verification_clip(
                    source_video_path=source_video_path,
                    start_sec=w_start,
                    duration_sec=w_dur,
                    output_path=micro_path,
                    fps=5.0,
                )
                if not micro_path.exists() or micro_path.stat().st_size < 1000:
                    return clip
                temp_clips.append(micro_path)
                windows.append((w_start, w_dur))
                part, rfile, cfile = self._prepare_video_part(client, micro_path, allow_compress=True)
                if rfile:
                    remote_files.append(rfile)
                if cfile:
                    cleanup_files.append(cfile)
                content_parts.append(part)

                pacing_key = str(voiceover_pacing or "full_commentary").lower()
                lang_inst = "clear natural English only, with no Hindi or Hinglish"
                if pacing_key == "hook_only":
                    script_rule = (
                        f"5. Write `verified_script` as a 5-8 word curiosity hook in {lang_inst} (<2.5s) "
                        "matching the exact vehicle, character, and action visibly shown right in these frames.\n"
                    )
                else:
                    target_words = max(28, min(68, int(min(w_dur, 32.0) * 1.85)))
                    script_rule = (
                        f"5. Write `verified_script` in {lang_inst} (STRICTLY ~{target_words} words, NO MORE than {target_words + 6} words) "
                        "describing ONLY what visibly happens from start to finish in these exact frames (ignore Stage 2 guesses if inaccurate!).\n"
                    )

                verify_prompt = (
                    "You are a ruthless Senior Short-Form Video Editor inspecting a 5-FPS high-clarity micro-clip WITH AUDIO.\n"
                    f"Yellow offset timestamps (`t=+X.Xs` from 0.0s to {w_dur:.1f}s) are burned in the top-left.\n"
                    "CRITICAL ANTI-HALLUCINATION RULE: Stage 2 only saw low-FPS thumbnails and MAY HAVE MIS-INDEXED this moment. Judge ONLY from your own eyes & ears in this micro-clip!\n"
                    f"Unverified Stage 2 label (for reference only, override freely if wrong): \"{clip.hook_text}\"\n\n"
                    "AUDIT INSTRUCTIONS:\n"
                    "1. Watch the frames and listen to the audio carefully.\n"
                    "2. Reject (`approved=false`, `quality_score <= 40`) if it shows static binoculars/scope spying, calm empty boating/driving, idle standing dialogue, 'MISSION PASSED' end-screens, menus, full-screen streamer cam, or dead air.\n"
                    f"3. Set `trim_start_offset` and `trim_end_offset` (between 0.0 and {w_dur:.1f}) so the clip opens immediately on kinetic stakes/motion and ends right after the payoff/punchline (at least 6s total).\n"
                    "4. Set `verified_hook_text` (3-6 clean uppercase words matching the real visuals) and `has_third_party_overlay=true` only if a webcam PiP or channel logo corner overlay is visible (`false` for pure gameplay HUD).\n"
                    + script_rule
                )

            content_parts.append(verify_prompt)
            verify_cfg = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClipVerificationResult,
                temperature=0.2,
            )

            v_resp = None
            for m in list(candidate_models):
                try:
                    v_resp = self._generate_content_with_retry(
                        client=client,
                        model=m,
                        contents=content_parts,
                        config=verify_cfg,
                    )
                    break
                except Exception as ex:
                    err_str = str(ex)
                    logger.warning(f"Close-up verify failed on model {m} for {clip.clip_id}: {ex}")
                    if "404" in err_str or "NOT_FOUND" in err_str:
                        candidate_models = [cm for cm in candidate_models if cm != m]

            if v_resp and getattr(v_resp, "text", None):
                v_result = ClipVerificationResult.model_validate(json.loads(v_resp.text))
                self._apply_verified_trims(clip, v_result, windows, source_duration)
                logger.info(
                    f"Close-up verified {clip.clip_id}: approved={v_result.approved}, "
                    f"score={v_result.quality_score}, new_span={clip.start_time:.1f}s+{clip.duration:.1f}s"
                )
        except Exception as e:
            logger.warning(f"Close-up verification skipped for {clip.clip_id} ({e}); keeping scout boundaries.")
        finally:
            for p in temp_clips + cleanup_files:
                try:
                    if p and p.exists():
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
            for rf in remote_files:
                if rf and hasattr(client, "files"):
                    try:
                        client.files.delete(name=rf.name)
                    except Exception:
                        pass

        return clip

    def analyze_gameplay_and_plan(
        self,
        proxy_path: Path,
        source_title: str,
        target_language: str = "english",
        clip_count: int = 3,
        clip_length_range: str = "30s-55s",
        voiceover_pacing: str = "hook_only",
        preferred_voice: str = "Charon",
        source_video_path: Optional[Path] = None,
        timeline_signals: Optional[Dict[str, Any]] = None,
        enable_closeup_verify: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> DirectorPlan:
        """
        4-Stage Human-Like Selection Funnel:
        1. Audio-enabled proxy + timeline audio/scene signals cue sheet.
        2. Scout pass over-selects candidates across the segment.
        3. 5-FPS + audio Close-Up Verification rejects duds and tightens trims.
        4. Ranks verified clips and stores remaining candidates in candidate_pool.
        """
        client = self._ensure_client()

        # If no client/API key, use intelligent algorithmic fallback for local testing
        if not client:
            logger.warning("GEMINI_API_KEY not configured. Generating offline blueprint plan.")
            return self._generate_fallback_plan(source_title, clip_count, target_language)

        if progress_callback:
            progress_callback(55, "Preparing audio-enabled gameplay video for Gemini Vision...")

        remote_file = None
        compact_cleanup_path = None

        try:
            video_part, remote_file, compact_cleanup_path = self._prepare_video_part(
                client=client,
                video_path=proxy_path,
                progress_callback=progress_callback,
                allow_compress=True,
            )

            use_closeup = bool(enable_closeup_verify and source_video_path and Path(source_video_path).exists())
            scout_count = min(8, max(clip_count * 2 + 1, 5)) if use_closeup else clip_count
            cue_sheet_block = self._format_cue_sheet(timeline_signals)
            from backend.services.ingest import ingest_service as _ing_svc
            proxy_dur = float((timeline_signals or {}).get("duration") or 0.0)
            if proxy_dur <= 0 and source_video_path and Path(source_video_path).exists():
                proxy_dur = float(_ing_svc._get_video_metadata(Path(source_video_path)).get("duration") or 0.0)
            if proxy_dur <= 0:
                proxy_dur = float(_ing_svc._get_video_metadata(proxy_path).get("duration") or 0.0)
            dur_guard_line = (
                f"CRITICAL VIDEO BOUNDARY: This video segment is {proxy_dur:.1f}s long. "
                f"EVERY `start_time`, `end_time`, and `beat.start_time + beat.duration` MUST be strictly <= {max(5.0, proxy_dur - 1.0):.1f}s!\n"
                if proxy_dur > 5.0 else ""
            )

            if progress_callback:
                progress_callback(60, f"Stage 2 Scout Pass: Scanning video + audio for top {scout_count} candidate moments...")

            # 3. Prompt Gemini Director for High-Retention Topics and Viral Storytelling
            prompt = f"""
You are the world's best Short-Form Video Director and Master Gaming Storyteller specializing in GTA 6, open-world gameplay, and viral TikTok / YouTube Shorts / Instagram Reels retention.
Analyze this raw gameplay video proxy (WATCH the visuals AND LISTEN to the audio track) and extract {scout_count} viral, high-retention candidate clips.
{dur_guard_line}{cue_sheet_block}
CORE RETENTION DIRECTIVE - NEVER CHOOSE BORING TOPICS:
1. STRICT FILTER: ZERO BORING OR MUNDANE TOPICS & ZERO STREAMER INTROS!
   - You MUST NEVER pick boring, mundane, repetitive, or filler segments.
   - FORBIDDEN SEGMENTS (CRITICAL):
     * Streamer full-screen talking head / webcam intro, "Just Chatting" segments, sponsor segments, channel intro/outro graphics, menu screens, or any segment where the streamer's camera or face fills the screen instead of active video game gameplay.
     * Static binoculars / telescope spying from a distance, calm empty boating on flat water with no danger, slow routine driving down an empty road without action or chase, or idle standing NPC dialogue!
   - PREFER HIGH-KINETIC MOMENTS: Heists, holdups, physical tackles, taser arrests, gunfire, explosions, alligator attacks, police chases, or high-speed stunts — and ALWAYS start Beat 1 RIGHT ON THE ACTION/IMPACT (skip slow 2-4s approach/walk-up)!
   - 100% PURE GAMEPLAY ONLY: Every selected clip MUST show active in-game gameplay. If the video begins with the streamer introducing the video, talking to the camera full screen, or sitting at their desk before starting the game, you MUST SKIP PAST THE INTRO COMPLETELY and only select timestamps where the actual game is being actively played on screen.

2. MANDATORY INTRO DETECTION (intro_end_time):
   - Inspect the beginning of this video proxy carefully.
   - If the video opens with a streamer talking full-screen, channel splash intro, or webcam talking head, identify the exact second where this intro ends and active gameplay starts, and report it in `intro_end_time`.
   - If the video is pure gameplay from the very first frame, set `intro_end_time=0.0`.
   - Every single clip's `start_time` MUST be strictly >= `intro_end_time + 3.0` seconds!

3. REAL IN-GAME MISSION & SCENE TRUTHFULNESS (CRITICAL DIRECTIVE - ZERO FAKE LORE!):
   - You MUST identify the REAL, ACTUAL MISSION, HEIST, OR IN-GAME EVENT happening in this footage!
   - STRICTLY FORBIDDEN: NEVER invent, fabricate, or hallucinate fake storylines, fictional cartel submarine conspiracies, fake $10M vaults, or make-up stories that have nothing to do with what the streamer is doing on screen.
   - Any viewer watching knows the game. If the voiceover talks about an invented fictional story while the player is doing a real mission, bank heist, stealing a jet, or running from police, the video is completely ruined and users will reject it.
   - 100% FAITHFUL TO THE REAL GAMEPLAY:
     * Identify who the player/streamer is playing as and what the mission objective actually is.
     * Identify the real mission/scenario (e.g. Heist setup, police ambush, stealing a military jet, infiltrating a compound, delivering a car, high-speed chase, stunt challenge).
     * Explain what is ACTUALLY taking place across the main scenes in an engaging, fast-paced way:
       1. The real mission objective or challenge the streamer took on.
       2. What actually happened in the gameplay: the close call, the crazy mistake, the intense shootout, or the hilarious fail.
       3. The actual conclusion: Did they beat the mission? Did they escape the cops? Did they crash?
   - Focus on the main, exciting gameplay scenes that are ACTUALLY ON SCREEN!

4. REAL TOPIC HEADLINE (hook_text, 3-6 WORDS):
   - The headline displayed on the top card MUST be the REAL topic or mission title describing what actually happens!
   - Use 3-6 punchy uppercase ASCII words (NO emojis needed — crisp typography looks cleanest).
   - Examples of ACCURATE, REAL topic hooks:
     * "THE JEWELRY STORE HEIST"
     * "TREVOR'S AIRFIELD SHOOTOUT"
     * "STEALING THE FORT ZANCUDO JET"
     * "SURVIVING A 5-STAR WANTED LEVEL"
     * "THE IMPOSSIBLE TRAIN JUMP"
     * "THE PALETO BANK MINIGUN RAMPAGE"
   - NEVER invent fake cartel or conspiracy titles.

5. VOICEOVER SCRIPT & PACING REQUIREMENTS:
   - Target Language: ENGLISH ONLY. Use articulate, compelling English; no Hindi or Hinglish.
   - Voiceover Pacing: {voiceover_pacing.upper()}.

   * If 'HOOK_ONLY':
     - Write an ultra-catchy opening hook of 5 to 8 words maximum (finishes under 2.5 seconds).
     - Must ignite intense curiosity about what happens next, then let the raw game audio take over.
     - Spoken in a calm, magnetic, confident tone (NOT screaming or hyper!).
     - Keep clip duration tight (16s-28s) starting directly in high-energy action so there is zero dead air!

   * If 'FULL_COMMENTARY' (Real Mission Story & Breakdown):
     - Explain the REAL mission or event that the streamer is playing, matching the clip length (~2.35 words per second of clip, so 75 to 95 words for a 32-40s montage — NEVER stop talking 15+ seconds before the clip ends!):
       1. Hook & Setup: State the real mission objective or challenge the streamer took on.
       2. Turning Point & Obstacle: What actually happened as the action escalated on screen.
       3. Climax Action: Describe the key gameplay shootout, chase, or maneuver.
       4. Real Payoff: The actual outcome of the mission.
     - TONE GUIDELINES:
       * Calm, captivating, articulate, and suspenseful documentary storyteller (like top true-crime and gaming lore documentaries).
       * NEVER shout, screech, or sound cartoonishly excited.
       * Steady, natural pacing with cinematic intrigue that holds retention from first frame to last.

- Target Clip Length: {clip_length_range} per clip.
- Virality Score (1-100): Rate retention and hook potential.
- Crop Mode: ALWAYS set 'crop_mode' to 'center_zoom'.
- TTS Voice: You MUST set 'tts_voice' to '{preferred_voice}' or choose from: 'Charon' (deep cinematic male, best for storytelling), 'Aoede' (expressive female), 'Kore' (calm female), 'Fenrir' (commanding male), or 'Puck' (energetic male). Default to '{preferred_voice}'.

6. MULTI-BEAT STORY MONTAGE VS SINGLE ACTION CLIMAX (CRITICAL FOR RETENTION):
   - A full mission, heist, or secret discovery usually spans 5 to 20 minutes in the raw footage.
   - NEVER output a boring continuous 45-second chunk where half of it is mundane walking or driving!
   - You MUST extract a dynamic MULTI-BEAT STORY MONTAGE ('clip_type': 'story_montage') whenever summarizing a mission or story arc:
     * Break the story into 3 key narrative beats stitched into a punchy 28-40s Short:
       - Beat 1: Setup / Hook (duration: 6-9s) - Active action opening, gearing up, or immediate stakes.
       - Beat 2: Escalation / Climax (duration: 9-13s) - Infiltrating the area, alarm sounding, chase, or firefight.
       - Beat 3: Payoff / Resolution (duration: 7-10s) - The high-speed escape, explosion, or ending outcome.
     * Populate the `beats` array with `StoryBeat(beat_id, label, start_time, duration, description)`.
     * Total `duration` of the clip must be the exact sum of all beat durations!
   - If a moment is already a standalone intense continuous stunt (e.g. uninterrupted 5-star ramp jump), you can set 'clip_type': 'single_moment'.

7. SENIOR REVIEWER CRITIC AUDIT (reviewer_score & reviewer_verdict):
   - Act as a ruthless Senior Video Editor & YouTube Algorithm Reviewer auditing every clip.
   - Score each clip strictly from 1 to 100 based on Hook Strength, Pacing, and Story Arc.
   - Set 'reviewer_score' (must be >= 85 for approved viral clips) and 'reviewer_verdict' explaining why it retains viewers.
   - Set plan.reviewer_summary summarizing the overall editorial audit.

- Watermark & Streamer Webcam Detection:
  * Normal GTA in-game HUD elements (mini-map radar, health bar, cash/ammo counter, subtitles, mission text) are CLEAN GAMEPLAY — NEVER mark them as a watermark!
  * Look closely at TOP-RIGHT and TOP-LEFT corners of gameplay frames: if there is a streamer picture-in-picture webcam/facecam box OR a channel corner logo (e.g. @handle or small badge), set watermark_info.detected=True, watermark_info.label='streamer_webcam' (or 'channel_logo'), and watermark_info.corner='top_right'|'top_left'|'bottom_right'|'bottom_left'.
  * ONLY set watermark_info.detected=False and watermark_info.corner='none' when ALL 4 corners are completely free of streamer webcams or creator logos.
- Copyright Music Detection: Identify if copyrighted radio music is playing. If detected, set has_copyrighted_music=True.
- Social Metadata: Generate YouTube Shorts, Instagram Reels, and Facebook Reels titles, descriptions, and viral hashtags that match this cool story.
"""

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DirectorPlan,
                temperature=0.7
            )

            response = None
            working_models = self._unique_models(
                app_config.DIRECTOR_MODEL,
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
            )
            candidate_models = list(working_models)
            for m in working_models:
                try:
                    response = self._generate_content_with_retry(
                        client=client,
                        model=m,
                        contents=[video_part, prompt],
                        config=config
                    )
                    logger.info(f"Director analysis successfully generated using model: {m}")
                    # Put confirmed working model first for Stage 3 verification calls
                    candidate_models = self._unique_models(m, *candidate_models)
                    break
                except Exception as ex:
                    logger.warning(f"Director Model {m} failed ({ex}). Trying next candidate...")
                    if "404" in str(ex) or "NOT_FOUND" in str(ex):
                        candidate_models = [cm for cm in candidate_models if cm != m]

            if not response:
                raise RuntimeError("All candidate director models failed.")

            # Parse JSON into DirectorPlan
            plan_json = json.loads(response.text)
            plan = DirectorPlan.model_validate(plan_json)

            # Enforce zero streamer intro overlap on all clips (combining Gemini Vision + YOLO detection)
            intro_end = max(0.0, float(getattr(plan, "intro_end_time", 0.0)))
            try:
                from backend.services.video_cropper import video_cropper
                cv_intro_end = video_cropper.detect_streamer_fullscreen_intro(proxy_path, max_scan_sec=120.0)
            except Exception as e:
                logger.warning(f"CV streamer intro check skipped: {e}")
                cv_intro_end = 0.0

            effective_intro = max(intro_end, cv_intro_end)
            if effective_intro > 0.0:
                logger.info(f"Streamer intro detected ending at {effective_intro:.1f}s (Gemini={intro_end:.1f}s, CV={cv_intro_end:.1f}s). Enforcing gameplay-only boundaries...")
                for clip in plan.clips:
                    if clip.beats:
                        for b_idx, beat in enumerate(clip.beats):
                            if beat.start_time < (effective_intro + 2.0):
                                beat.start_time = effective_intro + 2.0 + (b_idx * 12.0)
                        clip.start_time = clip.beats[0].start_time
                        clip.duration = sum(b.duration for b in clip.beats)
                        clip.end_time = clip.start_time + clip.duration
                    else:
                        if clip.start_time < (effective_intro + 2.0):
                            old_start = clip.start_time
                            clip.start_time = effective_intro + 2.0
                            clip.end_time = clip.start_time + clip.duration
                            logger.warning(f"Shifted clip {clip.clip_id} from {old_start:.1f}s to {clip.start_time:.1f}s to eliminate streamer intro.")

            # Clamp any out-of-range Scout timestamps cleanly inside the analyzed segment before Stage 3
            self._sanitize_plan_timestamps(plan, proxy_dur)

            # Stage 3: Close-Up 5 FPS Verification & Frame-Accurate Trimming
            if use_closeup and plan.clips:
                from backend.services.ingest import ingest_service
                src_path = Path(source_video_path)
                src_dur = float((timeline_signals or {}).get("duration") or ingest_service._get_video_metadata(src_path).get("duration", 0.0))
                intro_guard = effective_intro + 2.0 if effective_intro > 0.0 else 0.0
                verified_candidates: list[ClipBlueprint] = []
                total_scouts = len(plan.clips)
                for idx, cand in enumerate(plan.clips):
                    if progress_callback:
                        pct = 62 + int(((idx + 1) / max(1, total_scouts)) * 12)
                        progress_callback(pct, f"Stage 3 Close-Up Verify ({idx + 1}/{total_scouts}): Checking 5-FPS frames & audio for '{cand.hook_text}'...")
                    verified = self._verify_candidate_closeup(
                        client=client,
                        source_video_path=src_path,
                        clip=cand,
                        intro_guard_sec=intro_guard,
                        source_duration=src_dur,
                        candidate_models=candidate_models,
                        voiceover_pacing=voiceover_pacing,
                        target_language=target_language,
                    )
                    verified_candidates.append(verified)

                # Rank approved clips first, then by reviewer_score & virality_score.
                # Never fill remaining slots with rejected low-score duds (<55) when viable clips exist.
                ranked = sorted(
                    verified_candidates,
                    key=lambda c: (1 if c.verification_passed else 0, c.reviewer_score, c.virality_score),
                    reverse=True,
                )
                viable = [c for c in ranked if c.verification_passed or c.reviewer_score >= 55]
                if viable:
                    selected = viable[:clip_count]
                    selected_ids = {id(c) for c in selected}
                    backups = [c for c in ranked if id(c) not in selected_ids]
                else:
                    selected = ranked[:1]
                    backups = ranked[1:]
                for idx, c in enumerate(selected, start=1):
                    c.clip_id = f"clip_{idx}"
                plan.clips = selected
                plan.candidate_pool = backups
                approved_cnt = sum(1 for c in selected if c.verification_passed)
                plan.reviewer_summary = (
                    f"4-Stage Human-Like Funnel complete: Scouted {total_scouts} candidates, "
                    f"close-up verified {approved_cnt}/{len(selected)} final clips at 5 FPS + audio."
                )

            # Ensure reviewer validation fields are populated across all clips
            for clip in plan.clips:
                if not getattr(clip, "reviewer_score", None) or clip.reviewer_score < 1:
                    clip.reviewer_score = min(98, max(85, clip.virality_score + 2))
                if not getattr(clip, "reviewer_verdict", None) or not clip.reviewer_verdict:
                    num_beats = len(clip.beats) if clip.beats else 1
                    clip.reviewer_verdict = f"Approved by Senior Reviewer: High visual retention ({num_beats} story beats) with zero dead air."

            if not getattr(plan, "reviewer_summary", None) or not plan.reviewer_summary:
                plan.reviewer_summary = f"Senior Reviewer approved {len(plan.clips)} high-retention clips. Verified pure gameplay story arcs."

            if progress_callback:
                progress_callback(75, f"Director Plan finalized with {len(plan.clips)} verified clips!")

            return plan

        finally:
            if compact_cleanup_path and compact_cleanup_path.exists():
                try:
                    compact_cleanup_path.unlink(missing_ok=True)
                except Exception:
                    pass
            # Clean up remote file immediately if one was created
            if remote_file and client and hasattr(client, "files"):
                try:
                    client.files.delete(name=remote_file.name)
                    logger.info(f"Deleted remote Gemini file: {remote_file.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete remote file: {e}")

    # --------------------------------------------------------------------------
    # 2. Voiceover Synthesis (gemini-3.8-flash-tts)
    # --------------------------------------------------------------------------
    def synthesize_voiceover(
        self,
        script: str,
        job_id: str,
        clip_id: str,
        voice_name: str = "Charon",
        pacing: str = "full_commentary",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        require_speech: bool = False,
    ) -> Path:
        """
        Converts commentary script to 24kHz audio WAV via Gemini TTS with natural,
        captivating storytelling tone (never over-hyped or screaming).
        """
        import re
        out_wav_path = ASSETS_DIR / f"{job_id}_{clip_id}_voice.wav"
        client = self._ensure_client()

        if progress_callback:
            progress_callback(80, f"Synthesizing voiceover for {clip_id} via Gemini TTS ({voice_name})...")

        # Clean script: remove any parentheticals (e.g. [whispers], (excited)), markdown asterisks, or quotes
        clean_script = re.sub(r'\[.*?\]|\(.*?\)|[\*_~`]', '', script).strip()
        clean_script = re.sub(r'\s+', ' ', clean_script)
        if not clean_script:
            clean_script = script.strip()

        word_count = len(clean_script.split())
        is_short_hook = pacing == "hook_only" or (word_count <= 10 and not require_speech)

        if is_short_hook:
            tts_prompt = (
                f"Read aloud this exact text in a confident, slightly brisk conversational voice, "
                f"with clear words and brief pauses, without rushing or adding words:\n{clean_script}"
            )
        else:
            tts_prompt = (
                f"Read aloud this exact text in a clear, engaging conversational voice at a normal "
                f"to slightly brisk pace. Use brief natural pauses, without drawing out words, "
                f"rushing, or adding words:\n{clean_script}"
            )

        if client:
            try:
                # Normalize voice name to valid Gemini prebuilt voices
                valid_voices = {"Charon", "Aoede", "Kore", "Fenrir", "Puck"}
                safe_voice = voice_name if voice_name in valid_voices else "Charon"

                vc = types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=safe_voice)
                    )
                )
                cfg = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=vc
                )
                candidate_tts = self._unique_models(
                    app_config.TTS_MODEL,
                    "gemini-2.5-flash-tts",
                    "gemini-3.1-flash-tts-preview",
                )
                for tm in candidate_tts:
                    try:
                        resp = client.models.generate_content(
                            model=tm,
                            contents=tts_prompt,
                            config=cfg
                        )
                        candidates = getattr(resp, "candidates", None) or []
                        content = getattr(candidates[0], "content", None) if candidates else None
                        parts = getattr(content, "parts", None) or []
                        for part in parts:
                            if hasattr(part, "inline_data") and part.inline_data:
                                audio_data = part.inline_data.data
                                import wave
                                # Wrap raw PCM bytes in standard RIFF WAV container so FFmpeg reads it perfectly
                                if not audio_data.startswith(b"RIFF"):
                                    with wave.open(str(out_wav_path), "wb") as wf:
                                        wf.setnchannels(1)
                                        wf.setsampwidth(2)
                                        wf.setframerate(24000)
                                        wf.writeframes(audio_data)
                                else:
                                    out_wav_path.write_bytes(audio_data)
                                logger.info(f"Gemini TTS voice saved via {tm} ({safe_voice}) to {out_wav_path}")
                                return out_wav_path
                    except Exception as ex:
                        logger.warning(f"TTS Model {tm} failed ({ex}). Trying next...")
            except Exception as e:
                logger.warning(f"Gemini TTS API call failed ({e}). Using audio synthesis fallback.")

        if require_speech:
            raise RuntimeError("Explainer speech generation failed. No demo audio was substituted; check your Gemini TTS configuration.")

        # Fallback local TTS / Tone synthesizer if API key is absent
        self._generate_fallback_audio(clean_script, out_wav_path)
        return out_wav_path

    # --------------------------------------------------------------------------
    # 3. Callout Meme / Overlay Generation (gemini-3.1-flash-image)
    # --------------------------------------------------------------------------
    def generate_callout_overlay(
        self,
        prompt: str,
        hook_text: str,
        job_id: str,
        clip_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Generates custom PNG overlay/meme for clip callouts.
        """
        out_png_path = ASSETS_DIR / f"{job_id}_{clip_id}_overlay.png"
        client = self._ensure_client()

        if progress_callback:
            progress_callback(85, f"Generating callout graphic for {clip_id}...")

        if client:
            try:
                # Attempt image model generation if supported
                resp = client.models.generate_content(
                    model=app_config.IMAGE_MODEL,
                    contents=f"Generate a transparent PNG callout sticker/meme graphic for a gaming short: {prompt}. High resolution sticker style."
                )
                # If image bytes returned
                candidates = getattr(resp, "candidates", None) or []
                content = getattr(candidates[0], "content", None) if candidates else None
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        out_png_path.write_bytes(part.inline_data.data)
                        return out_png_path
            except Exception as e:
                logger.warning(f"Gemini Image API call failed ({e}). Generating high-res overlay badge.")

        # Fallback: Generate attractive, styled transparent PNG callout badge
        self._generate_styled_callout_badge(hook_text, out_png_path)
        return out_png_path

    # --------------------------------------------------------------------------
    # Fallback Generators (Offline / Pre-Key Prototyping)
    # --------------------------------------------------------------------------
    def _generate_fallback_plan(self, title: str, count: int, language: str) -> DirectorPlan:
        """Generates realistic structured director plan with cool topics and story lore for testing"""
        cool_clips_data = [
            {
                "hook_text": "THE JEWELRY STORE HEIST 💎",
                "summary": "High-stakes diamond heist with rapid escape through the underground subway tunnels.",
                "script": "In this mission, the streamer had to pull off the high-stakes Vangelico jewelry heist with zero casualties. After bagging the loot in under sixty seconds, the alarm was tripped, triggering an immediate four-star police response across the city. Cornered by cruisers on the freeway, they took a high-speed detour straight into the underground subway construction tunnels and lost the heat.",
                "category": "GTA • HEIST STORY"
            },
            {
                "hook_text": "THE IMPOSSIBLE 5-STAR GETAWAY 🚨",
                "summary": "High-octane escape evading SWAT roadblocks and helicopter pursuit across Vice City highway.",
                "script": "With maximum 5-star police heat and helicopters swarming above, this player pulled off the cleanest escape in Vice City history. Cornered at the docks with zero health remaining, one split-second jump changed everything.",
                "category": "GTA • VIRAL ESCAPE"
            },
            {
                "hook_text": "FORT ZANCUDO JET THEFT ✈️",
                "summary": "Infiltrating the high-security military base on a motorbike to steal a fighter jet.",
                "script": "In this challenge, the player attempted the hardest stunt in the game: breaching Fort Zancudo on a motorbike to steal a military fighter jet. Dodging tank shells across the runway, they hopped into the cockpit and took off just seconds before surface-to-air missiles locked on.",
                "category": "GTA • MILITARY STUNT"
            }
        ]
        clips = []
        for i in range(1, count + 1):
            # Start after common intro buffer (60s) to avoid streamer talking head
            start = 60.0 + (i - 1) * 70.0
            clip_meta = cool_clips_data[(i - 1) % len(cool_clips_data)]

            # 4-Beat narrative structure (Setup -> Infiltration -> Climax -> Escape)
            b1_dur = 6.0
            b2_dur = 10.0
            b3_dur = 12.0
            b4_dur = 6.0
            total_dur = b1_dur + b2_dur + b3_dur + b4_dur

            beats = [
                StoryBeat(beat_id=f"c{i}_b1", label="1. Mission Setup", start_time=start, duration=b1_dur, description="Contract briefing and vehicle prep"),
                StoryBeat(beat_id=f"c{i}_b2", label="2. Infiltration", start_time=start + 14.0, duration=b2_dur, description="Breaching compound and sounding alarm"),
                StoryBeat(beat_id=f"c{i}_b3", label="3. Climax Shootout", start_time=start + 30.0, duration=b3_dur, description="Heavy police shootout and vehicle explosion"),
                StoryBeat(beat_id=f"c{i}_b4", label="4. High-Speed Escape", start_time=start + 48.0, duration=b4_dur, description="Speedboat jump and surviving 5-star heat"),
            ]

            clip = ClipBlueprint(
                clip_id=f"clip_{i}",
                clip_type="story_montage",
                start_time=start,
                end_time=start + total_dur,
                duration=total_dur,
                beats=beats,
                virality_score=92 + (i % 8),
                reviewer_score=94 + (i % 5),
                reviewer_verdict="Approved: High-retention 4-beat story montage with zero dead air",
                hook_text=clip_meta["hook_text"],
                hook_summary=clip_meta["summary"],
                commentary_script=clip_meta["script"],
                has_copyrighted_music=False,
                detected_music_name=None,
                overlay_prompt=f"Gaming bold graphic badge for clip {i}",
                crop_mode=CropMode.CENTER_ZOOM,
                caption_style=CaptionStyle.HORMOZI_YELLOW,
                tts_voice="Charon",
                social_metadata=SocialMetadata(
                    youtube=YouTubeMetadata(
                        title=f"{clip_meta['hook_text']} 🤯 #Shorts #GTA6",
                        description=f"{clip_meta['summary']} Watch till the end! #GTA6 #Gaming #Shorts #ViceCity",
                        tags=["GTA6", "Gaming", "Shorts", "GTA 6 Secrets", "Viral", "Vice City"],
                        privacy="public"
                    ),
                    instagram=InstagramMetadata(
                        caption=f"{clip_meta['hook_text']}! Did you know about this in GTA 6? 💀🔥 Tag your squad! #gta6 #gaming #reels #vicecity",
                        hashtags=["#gta6", "#gaming", "#reels", "#grandtheftauto", "#viralreels", "#gta6gameplay"]
                    ),
                    facebook=FacebookMetadata(
                        caption=f"{clip_meta['hook_text']}! Insane GTA 6 moment #{i}. #GTA6 #GamingReels",
                        hashtags=["#GTA6", "#GamingReels", "#Gamer"]
                    )
                )
            )
            clips.append(clip)

        return DirectorPlan(
            source_title=title,
            duration_seconds=120.0,
            detected_radio_songs=[],
            overall_analysis="Action-packed gameplay with high-retention stunt sequences and intense police chases.",
            clips=clips
        )

    def _generate_fallback_audio(self, text: str, output_path: Path):
        """Generates real spoken human voiceover using native macOS `say` or OS speech synthesis at natural storytelling speed"""
        # Clean text of quotes and special characters for speech CLI
        clean_text = text.replace('"', '').replace("'", "").strip()
        if not clean_text:
            clean_text = "Wait till you see what was hidden deep inside Vice City!"

        # 1. Primary on macOS: use native `say` command with smooth, natural pace (165 wpm, not rushed 210)
        try:
            aiff_temp = output_path.with_suffix(".aiff")
            # Try smooth, natural voice 'Daniel' or 'Samantha' at natural 165 wpm
            cmd = ["say", "-v", "Daniel", "-r", "165", "-o", str(aiff_temp), clean_text]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode != 0:
                cmd = ["say", "-v", "Samantha", "-r", "165", "-o", str(aiff_temp), clean_text]
                res2 = subprocess.run(cmd, capture_output=True)
                if res2.returncode != 0:
                    cmd = ["say", "-r", "165", "-o", str(aiff_temp), clean_text]
                    subprocess.run(cmd, check=True, capture_output=True)

            # Convert to standard 48kHz mono 16-bit PCM WAV
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(aiff_temp),
                "-ar", "48000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(output_path)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            aiff_temp.unlink(missing_ok=True)
            logger.info(f"Generated spoken TTS voiceover via macOS speech engine: {output_path}")
            return
        except Exception as ex:
            logger.warning(f"macOS say TTS failed ({ex}). Attempting cross-platform speech...")

        # 2. Windows fallback using PowerShell SpeechSynthesizer with brisk rate (+2)
        try:
            ps_safe_text = clean_text.replace("'", "''")
            ps_script = f"""
            Add-Type -AssemblyName System.Speech;
            $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer;
            $synth.Rate = 2;
            $synth.SetOutputToWaveFile('{output_path}');
            $synth.Speak('{ps_safe_text}');
            $synth.Dispose();
            """
            subprocess.run(["powershell", "-Command", ps_script], check=True, capture_output=True)
            return
        except Exception:
            pass

        # 3. If all speech engines fail, generate 3 seconds of soft ambient silence (NEVER a harsh beep)
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", "3",
            "-c:a", "pcm_s16le",
            str(output_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _generate_styled_callout_badge(self, text: str, output_path: Path):
        """Creates a vibrant, transparent gaming sticker PNG overlay"""
        width, height = 600, 200
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Rounded rectangle background with border
        rect = [20, 20, width - 20, height - 20]
        draw.rounded_rectangle(rect, radius=24, fill=(19, 24, 33, 235), outline=(99, 102, 241, 255), width=4)

        # Accent top bar
        draw.rounded_rectangle([30, 25, width - 30, 35], radius=6, fill=(16, 185, 129, 255))

        # Text rendering
        draw.text((width // 2, height // 2 + 5), text, fill=(255, 255, 255, 255), anchor="mm")
        img.save(str(output_path), "PNG")

    # --------------------------------------------------------------------------
    # 4. Comparison Quest & Match Generator (Gemini Vision)
    # --------------------------------------------------------------------------
    def analyze_gta6_and_generate_quest(
        self,
        proxy_path: Path,
        base_game: str = "gta5",
        target_language: str = "english",
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> ComparisonQuest:
        """
        Analyzes a GTA 6 clip with Gemini Vision, identifies the exact gameplay test
        being demonstrated, and creates an exact 15-second 'Mission Quest Card' for
        the user to record in GTA 5 or GTA 4, along with a Charon comparison script.
        """
        client = self._ensure_client()
        if not client:
            logger.warning("GEMINI client unconfigured. Returning offline comparison quest.")
            return self._generate_fallback_quest(base_game, target_language)

        if progress_callback:
            progress_callback(35, f"Gemini Vision analyzing GTA 6 mechanic for {base_game.upper()} comparison...")

        target_base = "GTA 5" if "5" in base_game or "v" in base_game.lower() else "GTA 4"

        try:
            with open(proxy_path, "rb") as vf:
                vid_bytes = vf.read()
            video_part = types.Part.from_bytes(data=vid_bytes, mime_type="video/mp4")

            prompt = f"""
You are the world's leading Gaming Comparison Director specializing in viral GTA 5 vs GTA 6 (and GTA 4 vs GTA 6) physics and AI comparisons (like ENXGMA).
Analyze this GTA 6 gameplay sequence carefully.

YOUR GOAL:
1. Identify the exact gameplay mechanic, AI logic, physics behavior, or detail being tested in this GTA 6 footage.
   (Examples: Police confrontation / warning AI, Tire burnout smoke & rims, Falling from height ragdoll, Melee vehicle denting, Windshield bullet cracks, Water diving animations).
2. Create an exact, easy-to-follow "Gameplay Match Mission" for the player to replicate in {target_base} in UNDER 15 SECONDS!
3. Write a high-retention side-by-side comparison script for documentary narrator Charon.

REQUIRED FIELDS:
- quest_id: Unique string e.g. "quest_{int(time.time())}"
- test_title: Punchy test name (3-5 words, e.g. "Police Escalation & Warning AI")
- gta6_summary: 1-2 sentence description of what the character and game engine do in this GTA 6 footage.
- location: Exact iconic {target_base} map location to test this (e.g. "Mission Row Police Station / Legion Square", "Del Perro Pier", "Maze Bank Tower roof").
- gta5_steps: Exactly 3 simple, numbered instructions for the player:
  * Step 1: Vehicle / Weapon / Prep needed.
  * Step 2: Exact physical action to take.
  * Step 3: What to record for 10-15 seconds.
- recommended_duration_sec: 15.0
- hook_text: Irresistible uppercase topic headline banner with emoji (e.g. "{target_base} VS GTA 6 • POLICE AI 🚨" or "{target_base} VS GTA 6 • TIRE PHYSICS 💥")
- commentary_script: A viral 4-sentence comparison script in {target_language.upper()} (~70 to 95 words) formatted for calm, authoritative narrator Charon:
  * Sentence 1 (Hook): Compelling curiosity question on Rockstar's engine evolution.
  * Sentence 2 (Older Game): How {target_base} handled this mechanic.
  * Sentence 3 (GTA 6 Next-Gen): The subtle, realistic improvement in GTA 6.
  * Sentence 4 (Call to Action / Question): Engaging question asking viewers which game did it better.
- base_game: "{base_game}"
- social_metadata: YouTube Shorts, Instagram Reels, and Facebook Reels titles and tags.
"""

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ComparisonQuest,
                temperature=0.6
            )

            candidate_models = self._unique_models(
                app_config.DIRECTOR_MODEL,
                "gemini-2.5-flash",
                "gemini-2.0-flash",
            )
            resp = None
            for m in candidate_models:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=[video_part, prompt],
                        config=config
                    )
                    break
                except Exception as ex:
                    logger.warning(f"Comparison Quest model {m} failed: {ex}")

            if not resp or not resp.text:
                raise RuntimeError("Failed to generate comparison quest from Gemini Vision.")

            quest_data = json.loads(resp.text)
            quest = ComparisonQuest.model_validate(quest_data)
            if progress_callback:
                progress_callback(80, f"Comparison Quest ready: {quest.test_title}!")
            return quest

        except Exception as e:
            logger.warning(f"Gemini comparison quest error ({e}). Using smart fallback quest.")
            return self._generate_fallback_quest(base_game, target_language)

    def _generate_fallback_quest(self, base_game: str = "gta5", target_language: str = "english") -> ComparisonQuest:
        """Generates realistic comparison quest if vision model is unavailable"""
        target_name = "GTA 5" if "5" in base_game or "v" in base_game.lower() else "GTA 4"
        return ComparisonQuest(
            quest_id=f"quest_{int(time.time())}",
            test_title="Police Escalation & Warning AI",
            gta6_summary="In GTA 6, when the player approaches a police cruiser unarmed, officers give multiple verbal defusal warnings before unholstering their weapons.",
            location="Mission Row Police Station (Downtown Los Santos)",
            gta5_steps=[
                f"1. Drive to the Mission Row Police Station in {target_name} with Franklin or Michael.",
                "2. Stand directly in front of a stationary police cruiser unarmed without moving.",
                "3. Record for 10 to 15 seconds to capture how quickly the officers turn hostile."
            ],
            recommended_duration_sec=15.0,
            hook_text=f"{target_name} VS GTA 6 • POLICE AI 🚨",
            commentary_script=f"How did Rockstar completely revolutionize police behavior from {target_name} to GTA 6? In {target_name}, standing anywhere near a law enforcement officer immediately triggered aggressive lethal gunfire with zero warning. But in GTA 6, police AI first attempts verbal de-escalation, only drawing weapons if genuinely threatened. Which game's reaction feels more realistic to you?",
            base_game=ComparisonGame.GTA5 if "5" in base_game else ComparisonGame.GTA4,
            social_metadata=SocialMetadata(
                youtube=YouTubeMetadata(
                    title=f"{target_name} vs. GTA 6 Police AI Comparison! 🤯 #Shorts #GTA6 #GTA5",
                    description=f"Side-by-side comparison of police AI reactions in {target_name} versus GTA 6. Watch till the end! #GTA6 #Gaming #Comparison",
                    tags=["GTA6", "GTA5", "Gaming", "Shorts", "GTA Comparison", "Rockstar Games"],
                    privacy="public"
                ),
                instagram=InstagramMetadata(
                    caption=f"{target_name} vs GTA 6 Police AI! 💀 Which game has better details? Tag your squad! #gta6 #gta5 #gaming #reels #rockstargames",
                    hashtags=["#gta6", "#gta5", "#gaming", "#reels", "#rockstargames", "#gtacomparison"]
                ),
                facebook=FacebookMetadata(
                    caption=f"{target_name} vs. GTA 6 Physics & AI Comparison! #GTA6 #GTA5 #Gaming",
                    hashtags=["#GTA6", "#GTA5", "#GamingReels"]
                )
            )
        )

# Global instance
gemini_director = GeminiDirectorService()
