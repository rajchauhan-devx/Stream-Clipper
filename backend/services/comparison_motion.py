"""Word-aligned logo motion and sound for comparison hooks."""

import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from backend.services.comparison import FPS, SAMPLE_RATE

COMPARISON_ASSETS = Path(__file__).resolve().parents[1] / "assets" / "comparison"
TILE_WIDTH = 448
TILE_HEIGHT = 352
SLIDE_FRAMES = 26
POP_SCALE = 2.20
HOLD_SCALE = 1.85


def spoken_logo_frames(
    words: list[dict[str, Any]], base_game: str, hook_frames: int,
) -> tuple[int | None, int | None]:
    """Find the onset of each game name, regardless of numeral spelling."""
    text = ""
    starts = {}
    for word in words:
        token = " ".join(re.findall(r"[a-z0-9]+", word["word"].lower()))
        if token:
            starts[len(text)] = word["start"]
            text += token + " "
    prefix = r"\b(?:gta|g\s+t\s+a|grand\s+theft\s+auto)\s*"

    def onset(number: str) -> int | None:
        for match in re.finditer(prefix + number + r"\b", text):
            if match.start() in starts:
                frame = max(0, round(starts[match.start()] * FPS))
                if frame < hook_frames:
                    return frame
        return None

    return onset(r"(?:5|five|v)" if base_game == "gta5" else r"(?:4|four|iv)"), onset(r"(?:6|six|vi)")


def write_logo_motion(
    logo_path: Path, movie_path: Path, pop_frame: int, slide_frame: int,
) -> None:
    """Render a short alpha video over a fixed-size tile, keeping the logo centered."""
    with Image.open(logo_path) as source:
        logo = source.convert("RGBA")
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s:v", f"{TILE_WIDTH}x{TILE_HEIGHT}", "-framerate", str(FPS), "-i", "-",
        "-an", "-pix_fmt", "argb", "-c:v", "qtrle", str(movie_path),
    ]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as process:
        assert process.stdin is not None
        for frame in range(pop_frame, slide_frame + SLIDE_FRAMES + 1):
            age = frame - pop_frame
            if age < 7:
                scale = POP_SCALE - (POP_SCALE - 0.82) * (1 - age / 7) ** 2
            elif age < 16:
                scale = HOLD_SCALE + (POP_SCALE - HOLD_SCALE) * (1 - (age - 7) / 9) ** 2
            else:
                scale = HOLD_SCALE - (HOLD_SCALE - 1) * slide_progress(frame, slide_frame)
            size = round(logo.width * scale), round(logo.height * scale)
            artwork = logo.resize(size, Image.Resampling.LANCZOS)
            tile = Image.new("RGBA", (TILE_WIDTH, TILE_HEIGHT))
            tile.paste(artwork, ((TILE_WIDTH - size[0]) // 2, (TILE_HEIGHT - size[1]) // 2))
            process.stdin.write(tile.tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)


def slide_progress(frame: int, slide_frame: int) -> float:
    p = max(0.0, min(1.0, (frame - slide_frame) / SLIDE_FRAMES))
    return p * p * (3 - 2 * p)


def panel_logo_overlay(
    panel: str, stream: int, output: str, end_x: str, end_y: str,
    logo_size: tuple[int, int], pop_frame: int | None, slide_frame: int,
) -> list[str]:
    if pop_frame is None:
        return [f"[{panel}][{stream}:v]overlay={end_x}:{end_y}[{output}]"]
    width, height = logo_size
    x0 = f"(W-{TILE_WIDTH})/2"
    y0 = f"H*0.45-{TILE_HEIGHT / 2}"
    x1 = f"({end_x.replace('w', str(width))})-{(TILE_WIDTH-width) // 2}"
    y1 = f"{end_y}-{(TILE_HEIGHT-height) // 2}"
    p = f"clip((t*{FPS}-{slide_frame})/{SLIDE_FRAMES},0,1)"
    easing = f"({p}*{p}*(3-2*{p}))"
    # Both the effect and its sound use this same frame index.
    return [
        f"[{stream}:v]setpts=PTS-STARTPTS+{pop_frame}/({FPS}*TB)[{output}_tile]",
        f"[{panel}][{output}_tile]overlay="
        f"x='{x0}+({x1}-({x0}))*{easing}':y='{y0}+({y1}-({y0}))*{easing}':"
        f"enable='gte(t,{pop_frame}/{FPS})'[{output}]",
    ]


def pop_audio_filters(frames: tuple[int | None, int | None]) -> tuple[list[str], str]:
    filters = []
    labels = []
    for index, frame in enumerate(frames):
        if frame is None:
            continue
        # A short pitched pop with a soft attack so it sits under the spoken word.
        label = f"logo_pop{index}"
        peak = 690 if index == 0 else 880
        expression = (
            f"(0.25*sin(2*PI*({peak}*t-1100*t*t))"
            f"+0.13*sin(2*PI*({peak // 2}*t-540*t*t)))*exp(-26*t)*min(1,t*750)"
        )
        filters.append(
            f"aevalsrc='{expression}':s={SAMPLE_RATE}:d=0.14,"
            f"pan=stereo|c0=c0|c1=c0,adelay={frame * (SAMPLE_RATE // FPS)}S:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    if not labels:
        return [], "[5:a]"
    filters.append(f"[5:a]{''.join(labels)}amix=inputs={len(labels)+1}:duration=first:normalize=0[with_pops]")
    return filters, "[with_pops]"
