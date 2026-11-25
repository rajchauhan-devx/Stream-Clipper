import os
import json
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import yt_dlp

from backend.config import BASE_DIR, WORKSPACE_DIR, DOWNLOADS_DIR, PROXIES_DIR, TEMP_DIR

logger = logging.getLogger("gta6-studio.ingest")

def parse_time_str(time_str: Any) -> float:
    """Parses HH:MM:SS, MM:SS, or seconds to float seconds"""
    if time_str is None:
        return 0.0
    if isinstance(time_str, (int, float)):
        return max(0.0, float(time_str))
    val = str(time_str).strip()
    if not val:
        return 0.0
    parts = val.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        pass
    return 0.0

def _extract_youtube_id(url: str) -> Optional[str]:
    """Extracts the 11-character YouTube video ID from watch, youtu.be, or shorts URLs."""
    import re
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", str(url or ""))
    return m.group(1) if m else None


class IngestService:
    def __init__(self):
        self.downloads_dir = DOWNLOADS_DIR
        self.proxies_dir = PROXIES_DIR
        self.temp_dir = TEMP_DIR

    def _get_video_metadata(self, video_path: Path) -> Dict[str, Any]:
        """Extracts resolution, duration, and fps using ffprobe or OpenCV"""
        try:
            import cv2
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError("Could not open video file with OpenCV")
            
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0.0
            cap.release()

            return {
                "width": width,
                "height": height,
                "fps": round(fps, 2),
                "duration": round(duration, 2),
                "file_size_mb": round(video_path.stat().st_size / (1024 * 1024), 2)
            }
        except Exception as e:
            logger.warning(f"Metadata extraction fallback due to: {e}")
            return {
                "width": 1920,
                "height": 1080,
                "fps": 60.0,
                "duration": 60.0,
                "file_size_mb": round(video_path.stat().st_size / (1024 * 1024), 2) if video_path.exists() else 0.0
            }

    def download_or_link_video(
        self,
        url_or_path: str,
        job_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Fetches raw 1080p MP4 from YouTube or prepares local file.
        Returns dictionary with metadata and raw file path.
        """
        output_raw_path = self.downloads_dir / f"{job_id}_raw.mp4"

        # Case 1: Local file path
        candidate_local = Path(url_or_path).expanduser().resolve()
        if candidate_local.exists() and candidate_local.is_file():
            if progress_callback:
                progress_callback(10, f"Loading local file: {candidate_local.name}")
            
            logger.info(f"Using local video file: {candidate_local}")
            # If on the same filesystem, we can symlink or copy
            if candidate_local != output_raw_path:
                self._link_or_copy(candidate_local, output_raw_path)

            meta = self._get_video_metadata(output_raw_path)
            meta["title"] = candidate_local.stem
            meta["raw_path"] = str(output_raw_path)
            meta["is_local"] = True
            return meta

        # Case 2: Check URL cache for previously downloaded online VOD (exact URL or YouTube ID)
        cache_index_file = self.downloads_dir / "url_cache.json"
        url_cache: Dict[str, Any] = {}
        if cache_index_file.exists():
            try:
                url_cache = json.loads(cache_index_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"Could not read URL cache index: {exc}")

        yt_id = _extract_youtube_id(url_or_path)
        yt_cache_key = f"yt:{yt_id}" if yt_id else None
        cached_entry = url_cache.get(url_or_path) or (url_cache.get(yt_cache_key) if yt_cache_key else None)
        if not cached_entry and yt_id:
            for k, v in url_cache.items():
                if _extract_youtube_id(k) == yt_id:
                    cached_entry = v
                    break
        cached_file_str = None
        cached_title = None
        cached_duration = None
        if isinstance(cached_entry, dict):
            cached_file_str = cached_entry.get("raw_path")
            cached_title = cached_entry.get("title")
            cached_duration = cached_entry.get("duration")
        elif isinstance(cached_entry, str):
            cached_file_str = cached_entry

        if cached_file_str:
            cached_path = Path(cached_file_str)
            if cached_path.exists() and cached_path.stat().st_size > 10 * 1024 * 1024:
                if progress_callback:
                    progress_callback(25, f"Using fast cached 1080p stream ({cached_path.name})...")
                logger.info(f"Reusing cached raw video for {url_or_path}: {cached_path}")
                if cached_path.resolve() != output_raw_path.resolve():
                    self._link_or_copy(cached_path, output_raw_path)
                meta = self._get_video_metadata(output_raw_path)
                meta["title"] = cached_title or cached_path.stem
                if cached_duration and float(cached_duration) > 0:
                    meta["duration"] = float(cached_duration)
                meta["raw_path"] = str(output_raw_path)
                meta["is_local"] = False
                return meta

        # Case 3: YouTube / Online VOD link via yt-dlp
        if progress_callback:
            progress_callback(5, "Connecting to YouTube stream via yt-dlp...")

        import time
        last_progress_time = [0.0]

        def ytdl_hook(d):
            status = d.get('status')
            if status == 'downloading':
                now = time.time()
                # Rate limit to ~4 updates per second to avoid flooding WS
                if now - last_progress_time[0] < 0.25:
                    return
                last_progress_time[0] = now

                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed', 0) or 0
                eta = d.get('eta')

                pct_dl = (downloaded / total * 100) if total > 0 else 0
                mapped_pct = min(30, int(5 + (pct_dl * 0.25)))

                speed_str = f"{speed / (1024 * 1024):.1f} MB/s" if speed else "calculating..."
                dl_mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024) if total else 0
                total_str = f"{total_mb:.1f} MB" if total else "stream"
                eta_str = f" • ETA {eta}s" if eta is not None else ""

                msg = f"Downloading 1080p: {dl_mb:.1f} MB / {total_str} ({pct_dl:.1f}%) • {speed_str}{eta_str}"
                if progress_callback:
                    progress_callback(mapped_pct, msg)

            elif status == 'finished':
                if progress_callback:
                    progress_callback(30, "1080p stream downloaded. Merging video & audio tracks...")

        # Check for cookies file if provided
        cookie_file = None
        for candidate in [
            BASE_DIR / "cookies.txt",
            WORKSPACE_DIR / "cookies.txt",
            Path.cwd() / "cookies.txt",
        ]:
            if candidate.exists() and candidate.stat().st_size > 0:
                cookie_file = str(candidate.resolve())
                break

        ydl_opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'outtmpl': str(self.downloads_dir / f"{job_id}_raw.%(ext)s"),
            'merge_output_format': 'mp4',
            'concurrent_fragment_downloads': 8,
            'http_chunk_size': 10485760,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [ytdl_hook],
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv', 'visionos', 'android', 'web']
                }
            },
            'js_runtimes': {'node': {}}
        }
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file
            logger.info(f"Using cookies file for yt-dlp: {cookie_file}")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url_or_path, download=True)
                title = info.get('title', f"GTA6_Gameplay_{job_id}")
                duration = float(info.get('duration', 0.0))
        except Exception as e:
            err_msg = str(e)
            if "Sign in to confirm you’re not a bot" in err_msg or "bot" in err_msg.lower() or "429" in err_msg:
                logger.warning(f"YouTube bot detection caught: {e}. Retrying with VisionOS & Android client...")
                if progress_callback:
                    progress_callback(10, "Bypassing YouTube bot challenge via VisionOS/Android client...")
                fallback_opts = dict(ydl_opts)
                fallback_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['visionos', 'android']
                    }
                }
                with yt_dlp.YoutubeDL(fallback_opts) as fallback_ydl:
                    info = fallback_ydl.extract_info(url_or_path, download=True)
                    title = info.get('title', f"GTA6_Gameplay_{job_id}")
                    duration = float(info.get('duration', 0.0))
            else:
                raise

        # Check expected file
        if not output_raw_path.exists():
            # Sometimes yt-dlp appends other extensions or temporary names
            possible = list(self.downloads_dir.glob(f"{job_id}_raw.*"))
            if possible:
                output_raw_path = possible[0]
            else:
                raise FileNotFoundError(f"Could not locate downloaded file for {job_id}")

        meta = self._get_video_metadata(output_raw_path)
        meta["title"] = title
        meta["duration"] = duration if duration > 0 else meta["duration"]
        meta["raw_path"] = str(output_raw_path)
        meta["is_local"] = False
        try:
            cache_record = {
                "raw_path": str(output_raw_path),
                "title": meta["title"],
                "duration": meta["duration"],
            }
            url_cache[url_or_path] = cache_record
            if yt_cache_key:
                url_cache[yt_cache_key] = cache_record
            cache_index_file.write_text(json.dumps(url_cache, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to update URL cache: {exc}")
        return meta

    def cut_video_segment(
        self,
        raw_video_path: str | Path,
        job_id: str,
        start_time_str: str = "00:00:00",
        duration_mins: Optional[float] = 20.0,
        auto_cut_long: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Cuts a defined segment from the raw downloaded video using high-speed FFmpeg stream copy.
        Guarantees that Gemini Vision analysis stays under token limits (< 1M tokens)
        and reduces proxy generation time from 10 minutes to ~10 seconds.
        """
        raw_path = Path(raw_video_path)
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw video not found for cutting: {raw_video_path}")

        meta = self._get_video_metadata(raw_path)
        total_duration = meta.get("duration", 60.0)

        start_sec = parse_time_str(start_time_str)
        if start_sec >= total_duration:
            start_sec = 0.0

        # Maximum allowed duration for Gemini Vision safe analysis: 60 minutes (3600s)
        MAX_SAFE_DURATION = 3600.0  # 60 mins = max 1800 frames with adaptive fps, ~460k tokens, well under 1M limit

        if duration_mins is not None and duration_mins > 0:
            target_duration = min(duration_mins * 60.0, MAX_SAFE_DURATION)
        elif auto_cut_long and total_duration > MAX_SAFE_DURATION:
            target_duration = MAX_SAFE_DURATION
        else:
            target_duration = total_duration - start_sec

        effective_duration = min(target_duration, total_duration - start_sec)

        # If starting from 0 and total duration is already within safe limits, no cut needed
        if start_sec == 0.0 and total_duration <= (target_duration + 5.0):
            logger.info(f"Video duration ({total_duration:.1f}s) is already within safe window. No cut needed.")
            if progress_callback:
                progress_callback(30, f"Full video ({int(total_duration)}s) is within safe AI window. Skipping cut.")
            return {
                "cut_path": str(raw_path),
                "is_cut": False,
                "start_sec": 0.0,
                "duration_sec": total_duration,
                "total_raw_duration": total_duration
            }

        # Format timestamps for display
        start_fmt = f"{int(start_sec//3600):02d}:{int((start_sec%3600)//60):02d}:{int(start_sec%60):02d}"
        end_sec = start_sec + effective_duration
        end_fmt = f"{int(end_sec//3600):02d}:{int((end_sec%3600)//60):02d}:{int(end_sec%60):02d}"
        cut_path = self.downloads_dir / f"{job_id}_cut.mp4"

        if progress_callback:
            progress_callback(30, f"Cutting video segment: {start_fmt} -> {end_fmt} ({int(effective_duration)}s)...")

        logger.info(f"Cutting video {raw_path} from {start_fmt} to {end_fmt} ({effective_duration:.1f}s) -> {cut_path}")

        # High-speed stream copy (lossless, instant 1-2s cut)
        cmd_fast = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-i", str(raw_path),
            "-t", str(effective_duration),
            "-c", "copy",
            str(cut_path)
        ]

        result = subprocess.run(cmd_fast, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0 or not cut_path.exists() or cut_path.stat().st_size < 1000:
            logger.warning("Stream-copy cut failed; falling back to ultrafast re-encode...")
            cmd_reencode = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-i", str(raw_path),
                "-t", str(effective_duration),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "18",
                "-c:a", "aac",
                str(cut_path)
            ]
            subprocess.run(cmd_reencode, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cut_meta = self._get_video_metadata(cut_path)
        logger.info(f"Video cutter produced {cut_path} ({cut_meta.get('duration')}s, {cut_meta.get('file_size_mb')} MB)")

        if progress_callback:
            progress_callback(31, f"Video segment cut successfully ({int(effective_duration)}s). Building lightweight proxy...")

        return {
            "cut_path": str(cut_path),
            "is_cut": True,
            "start_sec": start_sec,
            "duration_sec": effective_duration,
            "total_raw_duration": total_duration
        }

    def find_peak_action_window(
        self,
        raw_video_path: str | Path,
        search_duration_sec: float = 7200.0,
        window_duration_mins: float = 20.0,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> float:
        """
        Ultra-fast audio RMS energy scanner (4s for 2 hours) to locate the highest
        firefight, explosion, and combat action density window across a long video.
        Returns the optimal start timestamp in seconds.
        """
        raw_path = Path(raw_video_path)
        if not raw_path.exists():
            return 0.0

        if progress_callback:
            progress_callback(28, "Audio Energy Peak Scanner: Analyzing 2-hour waveform for combat peaks...")

        meta = self._get_video_metadata(raw_path)
        total_duration = meta.get("duration", 3600.0)
        scan_len = min(total_duration, search_duration_sec)
        win_sec = min(window_duration_mins * 60.0, scan_len)

        try:
            import numpy as np
            # Downsampled to 8000Hz mono 16-bit PCM (takes ~3s to stream 2 hours)
            cmd = [
                "ffmpeg", "-y", "-ss", "0", "-t", str(scan_len),
                "-i", str(raw_path),
                "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"
            ]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            raw_bytes, _ = p.communicate()
            if not raw_bytes:
                return 0.0

            samples = np.frombuffer(raw_bytes, dtype=np.int16)
            block_size = 8000 * 10  # 10-second blocks
            num_blocks = len(samples) // block_size
            if num_blocks < 2:
                return 0.0

            energies = []
            for i in range(num_blocks):
                block = samples[i * block_size : (i + 1) * block_size].astype(np.float32)
                rms = np.sqrt(np.mean(block ** 2))
                energies.append(rms)

            win_blocks = max(1, int(win_sec // 10))
            if win_blocks >= len(energies):
                return 0.0

            # Skip initial 40s on long videos (>180s) to prevent locking onto loud streamer intro greetings
            start_block = 4 if (len(energies) > 18 and total_duration > 180.0) else 0
            best_idx = start_block
            best_avg = 0.0
            for i in range(start_block, len(energies) - win_blocks + 1):
                avg = float(np.mean(energies[i : i + win_blocks]))
                if avg > best_avg:
                    best_avg = avg
                    best_idx = i

            best_start_sec = float(best_idx * 10)
            logger.info(f"Audio Energy Peak Scanner found maximum combat density at {best_start_sec:.1f}s (RMS={best_avg:.1f})")
            return best_start_sec
        except Exception as e:
            logger.warning(f"Audio energy peak scan fallback: {e}")
            return 0.0

    @staticmethod
    def _link_or_copy(src: Path, dst: Path) -> None:
        """Hardlinks src -> dst when on the same filesystem, falling back to shutil.copy2."""
        if src.resolve() == dst.resolve():
            return
        if dst.exists():
            dst.unlink(missing_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)

    @staticmethod
    def _has_audio_stream(video_path: Path) -> bool:
        """Returns True if the media file contains at least one audio stream."""
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "csv=p=0",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "audio" in (probe.stdout or "").lower()
        except Exception:
            return False

    def extract_timeline_signals(
        self,
        video_path: str | Path,
        max_duration_sec: float = 3600.0,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Stage 1 Signal Pre-Indexer:
        Extracts 2-second audio RMS energy spikes and hard visual scene-cut timestamps
        so Gemini receives concrete anchor points alongside the proxy video.
        """
        src = Path(video_path)
        if not src.exists():
            return {"duration": 0.0, "audio_peaks": [], "scene_cuts": []}

        if progress_callback:
            progress_callback(31, "Scanning audio energy spikes & scene cuts for cue sheet...")

        meta = self._get_video_metadata(src)
        total_duration = float(meta.get("duration", 0.0))
        scan_len = min(total_duration, max_duration_sec) if total_duration > 0 else max_duration_sec

        audio_peaks: list[Dict[str, float]] = []
        if self._has_audio_stream(src):
            try:
                import numpy as np
                cmd = [
                    "ffmpeg", "-y", "-ss", "0", "-t", str(scan_len),
                    "-i", str(src),
                    "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
                ]
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                raw_bytes, _ = proc.communicate(timeout=45)
                if raw_bytes:
                    samples = np.frombuffer(raw_bytes, dtype=np.int16)
                    block_size = 8000 * 2  # 2-second buckets
                    num_blocks = len(samples) // block_size
                    energies = []
                    for i in range(num_blocks):
                        blk = samples[i * block_size : (i + 1) * block_size].astype(np.float32)
                        energies.append((i * 2.0, float(np.sqrt(np.mean(blk ** 2)))))
                    if energies:
                        vals = [e[1] for e in energies]
                        mean_rms = float(np.mean(vals))
                        std_rms = float(np.std(vals))
                        threshold = mean_rms + 0.8 * std_rms
                        # Pick local maxima spaced at least 8s apart
                        ranked = sorted((e for e in energies if e[1] >= threshold), key=lambda x: x[1], reverse=True)
                        chosen: list[tuple[float, float]] = []
                        for ts, rms in ranked:
                            if all(abs(ts - c_ts) >= 8.0 for c_ts, _ in chosen):
                                chosen.append((ts, rms))
                            if len(chosen) >= 25:
                                break
                        audio_peaks = [
                            {"time_sec": round(ts, 1), "rms": round(rms, 1)}
                            for ts, rms in sorted(chosen, key=lambda x: x[0])
                        ]
            except Exception as e:
                logger.warning(f"Timeline audio signal scan failed: {e}")

        scene_cuts: list[float] = []
        try:
            sc_proc = subprocess.run(
                [
                    "ffmpeg", "-ss", "0", "-t", str(scan_len),
                    "-i", str(src),
                    "-vf", "fps=2,select='gt(scene,0.32)',showinfo",
                    "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
            for line in (sc_proc.stderr or "").splitlines():
                if "pts_time:" in line:
                    for part in line.split():
                        if part.startswith("pts_time:"):
                            try:
                                t_val = round(float(part.split(":")[1]), 2)
                                if not scene_cuts or (t_val - scene_cuts[-1]) >= 2.0:
                                    scene_cuts.append(t_val)
                            except ValueError:
                                pass
            scene_cuts = scene_cuts[:40]
        except Exception as e:
            logger.warning(f"Timeline scene-cut scan failed: {e}")

        logger.info(
            f"Signal scan complete: {len(audio_peaks)} audio peaks, {len(scene_cuts)} scene cuts"
        )
        return {
            "duration": total_duration,
            "audio_peaks": audio_peaks,
            "scene_cuts": scene_cuts,
        }

    def create_micro_verification_clip(
        self,
        source_video_path: str | Path,
        start_sec: float,
        duration_sec: float,
        output_path: str | Path,
        fps: float = 5.0,
    ) -> Path:
        """
        Stage 3 Close-Up Micro-Clip:
        Cuts a focused 5 FPS, 480p/720p + low-bitrate audio clip around a candidate moment
        with relative offset timestamps (+00.0s) burned into the corner so Gemini can verify
        action, hear dialogue/SFX, and trim boundaries with ~0.2s accuracy.
        """
        src = Path(source_video_path)
        out = Path(output_path)
        if not src.exists():
            raise FileNotFoundError(f"Source video missing for verification clip: {src}")

        has_audio = self._has_audio_stream(src)
        vf_filter = (
            f"fps={fps},scale=-2:480,"
            "drawtext=text='t=+%{pts\\:flt}s':x=14:y=14:fontsize=24:"
            "fontcolor=yellow:box=1:boxcolor=black@0.75"
        )
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(0.0, float(start_sec))),
            "-t", str(max(1.0, float(duration_sec))),
            "-i", str(src),
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
        ]
        if has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "32k", "-ac", "1", "-ar", "16000"])
        else:
            cmd.append("-an")
        cmd.append(str(out))

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not out.exists() or out.stat().st_size < 500:
            # Retry without drawtext in case system font/filter fails
            fallback_cmd = [
                "ffmpeg", "-y",
                "-ss", str(max(0.0, float(start_sec))),
                "-t", str(max(1.0, float(duration_sec))),
                "-i", str(src),
                "-vf", f"fps={fps},scale=-2:480",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            ]
            if has_audio:
                fallback_cmd.extend(["-c:a", "aac", "-b:a", "32k", "-ac", "1", "-ar", "16000"])
            else:
                fallback_cmd.append("-an")
            fallback_cmd.append(str(out))
            subprocess.run(fallback_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return out

    def create_lightweight_proxy(
        self,
        raw_video_path: str,
        job_id: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Creates lightweight 480p @ 1 FPS (or 0.5 FPS >30m) proxy video WITH low-bitrate mono audio
        so Gemini Vision can both SEE gameplay and HEAR dialogue, sirens, gunfire, and reactions.
        """
        raw_path = Path(raw_video_path)
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw video not found: {raw_video_path}")

        proxy_path = self.proxies_dir / f"{job_id}_proxy.mp4"

        meta = self._get_video_metadata(raw_path)
        total_duration = meta.get("duration", 60.0)
        has_audio = self._has_audio_stream(raw_path)

        # Dynamic Adaptive FPS:
        # If duration <= 1800s (30m): 1 FPS (max 1800 frames = ~460k tokens)
        # If duration > 1800s (up to 3600s / 60m): 0.5 FPS (1 frame every 2s -> max 1800 frames = ~460k tokens)
        fps_val = 1.0 if total_duration <= 1800.0 else 0.5
        total_frames = max(1, int(total_duration * fps_val))

        if progress_callback:
            progress_callback(31, f"Encoding 480p @ {fps_val} FPS audio-enabled proxy (0/{total_frames} frames)...")

        logger.info(f"Creating 480p @ {fps_val} FPS proxy (audio={has_audio}) from {raw_path} -> {proxy_path} (Total frames: {total_frames})")

        # Keep proxy comfortably under 18MB for inline Vertex AI while preserving 1 FPS & mono audio
        target_v_kbps = max(45, min(140, int((13.0 * 8192) / max(60.0, total_duration)) - 24))
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_path),
            "-vf", f"scale=-2:480,fps={fps_val}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "30",
            "-maxrate", f"{target_v_kbps}k",
            "-bufsize", f"{target_v_kbps * 2}k",
        ]
        if has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "24k", "-ac", "1", "-ar", "16000"])
        else:
            cmd.append("-an")
        cmd.extend(["-progress", "pipe:1", str(proxy_path)])

        import time
        err_log_path = self.temp_dir / f"{job_id}_proxy_ffmpeg.log"
        err_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(err_log_path, "w", encoding="utf-8") as err_f:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=err_f,
                universal_newlines=True
            ) as proc:
                last_update = 0.0
                if proc.stdout:
                    for line in proc.stdout:
                        line = line.strip()
                        if line.startswith("frame="):
                            try:
                                curr_frame = int(line.split("=")[1].strip())
                                now = time.time()
                                if now - last_update >= 0.25:
                                    last_update = now
                                    progress_frac = min(1.0, curr_frame / total_frames)
                                    mapped_pct = min(50, int(31 + (progress_frac * 19)))
                                    pct_display = progress_frac * 100
                                    if progress_callback:
                                        progress_callback(
                                            mapped_pct,
                                            f"Encoding 480p proxy: {pct_display:.1f}% ({curr_frame}/{total_frames} frames)"
                                        )
                            except Exception:
                                pass
                proc.wait()
                ret_code = proc.returncode

        stderr_tail = ""
        try:
            if err_log_path.exists():
                stderr_tail = err_log_path.read_text(encoding="utf-8", errors="ignore")[-300:]
                err_log_path.unlink(missing_ok=True)
        except Exception:
            pass
        if ret_code != 0:
            raise RuntimeError(f"FFmpeg 480p proxy encode failed: {stderr_tail}")

        proxy_size_mb = proxy_path.stat().st_size / (1024 * 1024)
        logger.info(f"Proxy created successfully: {proxy_path} ({proxy_size_mb:.2f} MB)")

        if progress_callback:
            progress_callback(50, f"Proxy ready ({proxy_size_mb:.1f} MB). Handing off to Gemini Vision Director...")

        return proxy_path

# Global instance
ingest_service = IngestService()
