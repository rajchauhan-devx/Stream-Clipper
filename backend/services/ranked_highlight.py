"""Discover independent gameplay payoffs and reveal their ranks in one Short."""
import io
import math
import re
import subprocess
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from google.genai import types
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from backend import config
from backend.schemas import ClipBlueprint, DirectorPlan, SocialMetadata, StoryBeat
from backend.services.explainer import ExplainerService
from backend.services.extraction_review import Finding, review_cuts
from backend.services.ingest import ingest_service
from backend.services.renderer import _get_font


class Moment(BaseModel):
    start: float
    end: float
    score: int = Field(ge=1, le=100)
    label: str
    setup: str
    payoff: str
    wide: bool
    focus_x: float = Field(ge=0, le=1)
    radio_music: bool


class Picks(BaseModel):
    moments: list[Moment]


def _watch(director, path, prompt, fps=2):
    client = director._ensure_client()
    if not client:
        raise RuntimeError("Connect Gemini in Settings to find and rank gameplay moments.")
    part = types.Part.from_bytes(data=path.read_bytes(), mime_type="video/mp4")
    part.video_metadata = types.VideoMetadata(fps=fps)
    response = director._generate_content_with_retry(client, config.DIRECTOR_MODEL, [part, prompt],
        types.GenerateContentConfig(response_schema=Picks, response_mime_type="application/json", temperature=0.2))
    return Picks.model_validate_json(response.text).moments


def reveal_order(count: int) -> list[int]:
    return [rank for rank in (3, 5, 2, 4, 1) if rank <= count]


def verify_moment(director, source, offset, duration, candidate, goal):
    # Give the close-up pass room before the trigger and after the reaction.
    # A scout often returns only the instant of impact.
    extra = max(4.0, goal - (candidate.end - candidate.start))
    origin = max(0, candidate.start - extra * .6 - 2)
    stop = min(duration, candidate.end + extra * .4 + 2)
    cut = Finding(role="highlight", title=candidate.label, start=offset + origin, end=offset + stop,
                  reason=f"{candidate.setup} · {candidate.payoff}", tags=[], record="")
    checked = review_cuts(ExplainerService(director), source, [cut])[0]
    if checked is None:
        return None
    start, end = checked.start - offset, checked.end - offset
    if start >= candidate.end or end <= candidate.start:
        return None
    return candidate.model_copy(update={"start": start, "end": end, "payoff": checked.reason})


class Framing(BaseModel):
    portrait_ranks: list[int]


def check_framing(director, source, offset, beats):
    """Compare the actual portrait crop with the full frame at three points per moment."""
    client = director._ensure_client()
    if not client:
        return
    parts = []
    for beat in beats:
        sheet = Image.new("RGB", (750, 288), "black")
        for i, fraction in enumerate((.15, .5, .85)):
            result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(offset + beat.start_time + beat.duration*fraction),
                                     "-i", str(source), "-frames:v", "1", "-vf", "scale=250:144:force_original_aspect_ratio=decrease",
                                     "-f", "image2pipe", "-c:v", "mjpeg", "-"], capture_output=True, check=True)
            if not result.stdout:
                continue
            with Image.open(io.BytesIO(result.stdout)) as frame:
                width = min(frame.width, round(frame.height * 1080 / 1540))
                left = max(0, min(frame.width-width, round(frame.width*beat.focus_x-width/2)))
                sheet.paste(frame, (i*250, 0))
                crop = frame.crop((left, 0, left+width, frame.height))
                sheet.paste(crop, (i*250+(250-width)//2, 144))
        buf = io.BytesIO()
        sheet.save(buf, "JPEG", quality=88)
        parts.extend([f"Rank {beat.rank}: {beat.description}", types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")])
    parts.append("Each sheet shows three original frames on top and their proposed portrait crops below. Select ALL ranks "
                 "where the lower row still shows the main action. Prefer portrait whenever the gag reads. Ignore missing HUD, "
                 "scenery or parts of a vehicle. Keep wide only if a key actor, object or payoff is outside the crop.")
    response = director._generate_content_with_retry(client, config.DIRECTOR_MODEL, parts,
        types.GenerateContentConfig(response_schema=Framing, response_mime_type="application/json", temperature=0))
    portrait = set(Framing.model_validate_json(response.text).portrait_ranks)
    for beat in beats:
        beat.wide = beat.rank not in portrait


def analyze(director, source, source_title, offset, duration, count, length_range, verify, progress):
    limits = [int(n) for n in re.findall(r"\d+", length_range)]
    goal = max(5, min(19, (max(limits or [90]) / 5)))
    prompt = f"""Find distinct funny GTA gameplay moments for a ranked compilation. Include only visible
mishaps, surprises, awkward NPC behavior, escalating chaos or ironic outcomes. An ordinary mission step,
title, menu, webcam reaction or establishing shot alone does not qualify. Each item must have its own
setup and payoff; never split one event into several ranks. Use decimal seconds from the beginning of
this excerpt. Keep the setup through the visible payoff, roughly {goal:.0f} seconds per item, shorter for a fast gag.
Score the comedic payoff 1–100. Give each a distinctive 1–3 word English leaderboard label and a short
English setup caption (at most 8 words) that doesn't spoil the ending. Describe the actual payoff.
Set wide=true if a portrait crop would lose the action; otherwise give normalized horizontal focus_x.
Flag audible licensed radio music. Return an empty list for uneventful footage."""
    candidates = []
    accepted = []
    with TemporaryDirectory(dir=config.TEMP_DIR) as folder:
        proxy = Path(folder) / "scan.mp4"
        for i in range(max(1, math.ceil((duration - 10) / 120))):
            start = i * 120
            span = min(130, duration - start)
            progress(33 + int(20 * start / duration), f"Finding funny moments at {int(offset + start)}s…")
            ingest_service.create_micro_verification_clip(source, start + offset, span, proxy, fps=2)
            for m in _watch(director, proxy, prompt):
                if 0 <= m.start < m.end <= span + 0.1 and 2 <= m.end - m.start <= 35:
                    candidates.append(m.model_copy(update={"start": start + m.start, "end": min(duration, start + m.end)}))
        labels = set()
        for m in sorted(candidates, key=lambda pick: -pick.score):
            if len(accepted) >= count * 5:
                break
            if any(m.start < other.end and m.end > other.start for other in accepted):
                continue
            progress(60, f"Checking the payoff for {m.label}…")
            m = verify_moment(director, source, offset, duration, m, goal)
            if m is None or not m.payoff.strip() or not m.setup.strip():
                continue
            if any(m.start < other.end and m.end > other.start for other in accepted):
                continue
            key = " ".join(m.label.casefold().split())
            if not key or key in labels:
                continue
            labels.add(key)
            accepted.append(m)
    if len(accepted) < 2:
        raise ValueError("This scan found fewer than two distinct funny payoffs. Try a longer gameplay window.")
    title = source_title.upper()
    match = re.search(r"(?:GTA|GRAND THEFT AUTO)\s*(VI|V|IV|[456])\b", title)
    game = "GTA" if "GTA" in title or "GRAND THEFT AUTO" in title else "Gameplay"
    if match:
        number = match.group(1)
        game = "GTA " + {"VI": "6", "V": "5", "IV": "4"}.get(number, number)
    clips = []
    accepted.sort(key=lambda m: -m.score)
    for first in range(0, len(accepted), 5):
        group = accepted[first:first+5]
        if len(group) < 2:
            break
        beats = []
        for rank in reveal_order(len(group)):
            m = group[rank - 1]
            beats.append(StoryBeat(beat_id=f"rank_{rank}", rank=rank, label=m.label, narration=m.setup,
                                   description=m.payoff, wide=m.wide, focus_x=m.focus_x,
                                   start_time=round(m.start, 2), duration=round(m.end - m.start, 2)))
        if verify:
            check_framing(director, source, offset, beats)
        hook = f"Ranking Funniest {game} Moments"
        description = " · ".join(f"#{b.rank} {b.label}" for b in beats)
        tags = [game, "Gaming", "FunnyMoments", "Shorts"]
        social = SocialMetadata(youtube={"title": hook, "description": description, "tags": tags},
                                instagram={"caption": hook, "hashtags": ["#gaming", "#funnymoments"]},
                                facebook={"caption": hook, "hashtags": ["#gaming"]})
        clips.append(ClipBlueprint(clip_id=f"clip_{len(clips)+1}", clip_type="ranked_highlight",
            start_time=min(b.start_time for b in beats), end_time=max(b.start_time+b.duration for b in beats),
            duration=round(sum(b.duration for b in beats), 2), beats=beats, virality_score=group[0].score,
            reviewer_score=group[0].score, reviewer_verdict="Distinct payoffs ranked by comedic impact.",
            hook_text=hook, hook_summary=description, commentary_script="", overlay_prompt="", social_metadata=social,
            verification_passed=True, has_copyrighted_music=any(m.radio_music for m in group)))
    return DirectorPlan(source_title=source_title, duration_seconds=duration, clips=clips,
                        overall_analysis=f"{len(clips)} ranked compilations from {len(accepted)} distinct moments.")


def artwork(beats: list[dict], index: int, game: str, path: Path, *, reveal=True, title=""):
    canvas = Image.new("RGBA", (1080, 1920))
    d = ImageDraw.Draw(canvas)
    font_names = ["Arial Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
    def line(parts, y, size):
        font = _get_font(font_names, size)
        width = sum(font.getlength(s) for s, _ in parts)
        x = (1080 - width) / 2
        for s, color in parts:
            d.text((x, y+3), s, font=font, fill="black", anchor="lm", stroke_width=2)
            d.text((x, y), s, font=font, fill=color, anchor="lm")
            x += font.getlength(s)
        return x
    d.rectangle((0, 0, 1080, 190), fill="#272727")
    d.rectangle((0, 1730, 1080, 1920), fill="#272727")
    if title:
        words = title.split()
        # Split at a word boundary and fit each line to the fixed leaderboard header.
        split = min(range(1, len(words) + 1), key=lambda pos:
                    abs(len(" ".join(words[:pos])) - len(" ".join(words[pos:]))))
        lines = [" ".join(words[:split]), " ".join(words[split:])]
        for value, y, color in zip(lines, (69, 155) if lines[1] else (96,), ("white", "#00ecec")):
            size = 68
            while size > 12 and _get_font(font_names, size).getlength(value) > 1010:
                size -= 1
            line([(value, color)], y, size)
    else:
        line([("Ranking ", "white"), ("Funniest", "#ff2424")], 69, 69)
        x = line([(game+" ", "#00ecec"), ("Moments  ", "white"), ("   ", "#272727")], 155, 67)
        # Small laughing face drawn inline so the banner also works without a color emoji font.
        x = int(x) - 24
        d.ellipse((x-27,126,x+27,179),fill="#ffca24")
        for dx in (-12,12):
            d.line([(x+dx-7,147),(x+dx,142),(x+dx+6,147)],fill="#513018",width=4)
            d.ellipse((x+dx*1.8-5,150,x+dx*1.8+4,161),fill="#42caff")
        d.chord((x-16,143,x+16,170),0,180,fill="#612b20")
    colors = ["#ffce23", "#d4d4d4", "#d88b4b", "white", "white"]
    known = {b["rank"]: b["label"].upper() for b in beats[:index + int(reveal)]}
    for rank in range(1, len(beats)+1):
        y = 710 + (rank-1)*190
        d.text((18,y), f"{rank}.",font=_get_font(["Arial Black.ttf", *font_names],94),
               anchor="lm",fill=colors[rank-1],stroke_width=8,stroke_fill="black")
        if rank in known:
            label = known[rank]
            font = _get_font(font_names, 35)
            while font.getlength(label) > 525 and font.size > 20:
                font = _get_font(font_names, font.size-1)
            d.text((153,y),label,font=font,anchor="lm",fill="white",stroke_width=3,stroke_fill="black")
    setup = beats[index].get("narration","")
    font = _get_font(font_names, 46)
    lines = [""]
    for word in setup.split():
        trial = (lines[-1]+" "+word).strip()
        if lines[-1] and font.getlength(trial)>810:
            lines.append(word)
        else:
            lines[-1]=trial
    for row, value in enumerate(lines):
        d.text((540, 537 + row*53),value,font=font,anchor="mm",fill="white",stroke_width=3,stroke_fill="#111111")
    canvas.save(path)


def mix_sound(source: Path, beats: list[dict], output: Path, game_boost: float):
    """An original quiet rhythmic bed and a short per-reveal accent under the source audio."""
    sr = 24000
    total = round(sum(b["duration"] for b in beats)*sr)
    bed = np.zeros(total, dtype=np.float32)
    pulse = 60/108
    def add(at, sound):
        start = round(at*sr)
        n = min(len(sound), total-start)
        if n > 0:
            bed[start:start+n] += sound[:n]
    t = np.arange(round(.28*sr))/sr
    for step in range(math.ceil(total/sr/pulse)):
        note = (65.41,65.41,77.78,58.27)[(step//2)%4]
        tone = .062*np.sin(2*np.pi*note*t)*np.exp(-14*t)
        kick = .08*np.sin(2*np.pi*(46*t+.75*(1-np.exp(-35*t))))*np.exp(-22*t)
        add(step*pulse,(tone+kick)*np.minimum(1,t*300))
    elapsed=0.0
    for beat in beats:
        add(elapsed + .25,.14*np.sin(2*np.pi*(620+42*(6-beat["rank"]))*t)*np.exp(-18*t)*np.minimum(1,t*450))
        elapsed+=beat["duration"]
    backing = output.with_suffix(".bed.wav")
    try:
        with wave.open(str(backing),"wb") as f:
            f.setparams((1,2,sr,0,"NONE","not compressed"))
            f.writeframes((bed*32767).astype("<i2").tobytes())
        subprocess.run(["ffmpeg","-v","error","-y","-i",str(source),"-i",str(backing),"-filter_complex",
            f"[0:a]volume={game_boost}[game];[game][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95","-ar","48000","-ac","2",str(output)],check=True)
    finally:
        backing.unlink(missing_ok=True)
