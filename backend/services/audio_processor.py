import gc
import os
import sys
import uuid
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable
import torch

from backend.config import TEMP_DIR, HARDWARE

logger = logging.getLogger("gta6-studio.audio")

class AudioProcessor:
    def __init__(self):
        self.temp_dir = TEMP_DIR

    def strip_copyright_radio(
        self,
        audio_segment_path: Path,
        output_clean_path: Path,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Uses Demucs (htdemucs) to isolate gameplay SFX/vocals and strip copyrighted radio music.
        Enforces sequential memory cleanup to preserve 6GB VRAM / unified RAM.
        """
        if progress_callback:
            progress_callback(5, "Running Demucs audio separation to strip copyrighted radio...")

        logger.info(f"Stripping copyrighted radio from {audio_segment_path} using Demucs...")
        demucs_out_dir = self.temp_dir / f"demucs_out_{uuid.uuid4().hex[:8]}"
        demucs_out_dir.mkdir(parents=True, exist_ok=True)

        try:
            device = "cuda" if (torch.cuda.is_available() and getattr(HARDWARE, "is_cuda", False)) else "cpu"
            # Run demucs command-line tool with two-stems=vocals or htdemucs
            cmd = [
                sys.executable, "-m", "demucs",
                "-d", device,
                "--two-stems", "vocals",
                "-n", "htdemucs",
                "--out", str(demucs_out_dir),
                str(audio_segment_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Look for non-vocal / SFX output
            track_name = audio_segment_path.stem
            isolated_no_vocals = demucs_out_dir / "htdemucs" / track_name / "no_vocals.wav"

            if isolated_no_vocals.exists() and isolated_no_vocals.stat().st_size > 1000:
                shutil.copy2(isolated_no_vocals, output_clean_path)
                logger.info(f"Demucs voice separation successful: {output_clean_path}")
            else:
                logger.warning("Demucs no_vocals file missing or empty. Muting source so original dialogue cannot return.")
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(audio_segment_path),
                    "-af", "volume=0",
                    str(output_clean_path)
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        except Exception as e:
            logger.warning(f"Demucs separation encountered issue ({e}). Muting source so original dialogue cannot return.")
            subprocess.run([
                "ffmpeg", "-y", "-i", str(audio_segment_path),
                "-af", "volume=0",
                str(output_clean_path)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        finally:
            shutil.rmtree(demucs_out_dir, ignore_errors=True)
            # Strict VRAM and unified memory cleanup
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            logger.info("Demucs memory cleaned and cache flushed.")

        return output_clean_path

    def duck_and_mix_audio(
        self,
        gameplay_audio_path: Path,
        voiceover_path: Path,
        output_mixed_path: Path,
        ducking_db: float = -16.0,
        game_volume_boost: float = 1.5,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Applies FFmpeg sidechaincompress to automatically duck gameplay audio by -16dB
        whenever the Gemini commentary voiceover speaks, smoothly restoring volume in pauses.
        Also boosts gameplay audio (e.g. 1.5x) with an alimiter to keep sound effects loud & punchy.
        """
        if progress_callback:
            progress_callback(15, f"Applying -16dB sidechain ducking & {game_volume_boost}x game volume boost...")

        logger.info(f"Ducking gameplay audio: {gameplay_audio_path} (boost={game_volume_boost}x) under voiceover: {voiceover_path}")

        # FFmpeg filtergraph:
        # [0:a] = gameplay, [1:a] = voiceover
        # [0:a]volume=X,alimiter=limit=0.95 boosts gameplay SFX while preventing clipping
        # [1:a]apad pads voiceover with silence so sidechaincompress stays open for full gameplay duration
        # sidechaincompress ducks gameplay by ~16dB while voice is active, restoring 100% volume when voice ends
        # amix with duration=first ensures the mixed output NEVER truncates when the voiceover finishes!
        boost = max(0.5, min(3.0, float(game_volume_boost)))
        filter_complex = (
            f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={boost:.2f},alimiter=limit=0.95[boosted_game];"
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[voice_padded];"
            "[boosted_game][voice_padded]sidechaincompress="
            "threshold=0.03:ratio=10:attack=15:release=250[ducked];"
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[voice_norm];"
            "[ducked][voice_norm]amix=inputs=2:duration=first:weights=1.0 1.5:dropout_transition=2[aout]"
        )

        # Determine codec based on file extension
        is_wav = str(output_mixed_path).lower().endswith(".wav")
        audio_codec = ["-c:a", "pcm_s16le"] if is_wav else ["-c:a", "aac", "-b:a", "192k"]

        cmd = [
            "ffmpeg", "-y",
            "-i", str(gameplay_audio_path),
            "-i", str(voiceover_path),
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            *audio_codec,
            "-ar", "48000",
            str(output_mixed_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.warning(f"Sidechaincompress fallback: {result.stderr[:150]}")
            # Fallback simple amix if sidechain fails
            fallback_cmd = [
                "ffmpeg", "-y",
                "-i", str(gameplay_audio_path),
                "-i", str(voiceover_path),
                "-filter_complex", "[0:a]volume=0.85[g];[1:a]volume=1.4[v];[g][v]amix=inputs=2:duration=first[aout]",
                "-map", "[aout]",
                *audio_codec,
                "-ar", "48000",
                str(output_mixed_path)
            ]
            subprocess.run(fallback_cmd, check=True)

        return output_mixed_path

audio_processor = AudioProcessor()
