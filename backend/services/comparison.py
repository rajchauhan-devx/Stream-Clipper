import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.schemas import ComparisonRenderRequest

FPS = 60
SAMPLE_RATE = 48000


@dataclass(frozen=True)
class ComparisonTimeline:
    """The three phases share frame boundaries across video and audio."""

    hook: int
    older_game: int
    gta6: int

    @classmethod
    def from_durations(
        cls, hook: float, older_voice: float, gta6_voice: float,
        older_clip: float, gta6_clip: float,
    ) -> "ComparisonTimeline":
        hook_frames = math.ceil(hook * FPS)
        return cls(
            hook_frames,
            max(math.ceil(older_voice * FPS), round(older_clip * FPS) - hook_frames),
            max(math.ceil(gta6_voice * FPS), round(gta6_clip * FPS) - hook_frames),
        )

    @property
    def phases(self) -> tuple[int, int, int]:
        return self.hook, self.older_game, self.gta6

    def video_filters(self) -> list[str]:
        older_end = self.hook + self.older_game
        gta6_end = self.hook + self.gta6
        return [
            f"[0:v]fps={FPS},tpad=stop_mode=clone:stop={older_end},"
            f"trim=end_frame={older_end},tpad=stop_mode=clone:stop={self.gta6}[older_playback]",
            f"[1:v]fps={FPS},tpad=stop_mode=clone:stop={gta6_end},"
            f"trim=end_frame={gta6_end},split[six_intro][six_focus]",
            f"[six_intro]trim=end_frame={self.hook},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop={self.older_game}[six_held]",
            f"[six_focus]trim=start_frame={self.hook},setpts=PTS-STARTPTS[six_resumed]",
            f"[six_held][six_resumed]concat=n=2:v=1:a=0,setpts=N/({FPS}*TB)[six_playback]",
        ]

    def assemble_audio(self, voices: list[Path], older_audio: Path, gta6_audio: Path,
                       narration: Path, gameplay: Path) -> None:
        """Pad each spoken section to its phase and use only the active game's sound."""
        samples = [frames * (SAMPLE_RATE // FPS) for frames in self.phases]
        speech_filters = [
            f"[{i}:a]aformat=sample_rates={SAMPLE_RATE}:channel_layouts=mono,"
            f"apad,atrim=end_sample={length},asetpts=PTS-STARTPTS[speech{i}]"
            for i, length in enumerate(samples)
        ]
        subprocess.run([
            "ffmpeg", "-v", "error", "-y",
            *(arg for path in voices for arg in ("-i", str(path))),
            "-filter_complex", ";".join(speech_filters + [
                "[speech0][speech1][speech2]concat=n=3:v=0:a=1[narration]"
            ]), "-map", "[narration]", "-c:a", "pcm_s16le", str(narration),
        ], check=True)
        intro, older, newer = samples
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(older_audio), "-i", str(gta6_audio),
            "-filter_complex",
            f"[0:a]apad,atrim=end_sample={intro + older},asetpts=PTS-STARTPTS[older];"
            f"[1:a]apad,atrim=start_sample={intro}:end_sample={intro + newer},asetpts=PTS-STARTPTS[newer];"
            "[older][newer]concat=n=2:v=0:a=1[gameplay]",
            "-map", "[gameplay]", "-c:a", "pcm_s16le", str(gameplay),
        ], check=True)


def commentary_passages(payload: ComparisonRenderRequest) -> tuple[str, str, str]:
    if payload.narration:
        return payload.narration.hook, payload.narration.older_game, payload.narration.gta6

    # Older clients sent a single script with the hook and games in story order.
    legacy = (payload.commentary_script or "").strip()
    lines = [line.strip() for line in legacy.splitlines() if line.strip()]
    if len(lines) < 3:
        lines = re.split(r"(?<=[.!?])\s+", legacy) if legacy else []
    older = "GTA Five" if payload.base_game.value == "gta5" else "GTA Four"
    return (
        lines[0] if lines else f"How does this work in {older} versus GTA Six?",
        lines[1] if len(lines) > 1 else f"First, watch what happens in {older}.",
        " ".join(lines[2:]) if len(lines) > 2 else "Now watch how the same moment plays out in GTA Six.",
    )
