"""Find reproducible actions and compare two user-reviewed cuts."""
import json
import logging
import math
import re
import subprocess
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, HTTPException
from google.genai import types
from pydantic import BaseModel, Field

from backend import config
from backend.schemas import ComparisonFormat, ComparisonGame, ComparisonNarration, ComparisonRenderRequest
from backend.services.explainer import ExplainerService
from backend.services.extraction_review import Finding, review_cuts
from backend.services.gemini_director import gemini_director
from backend.services.ingest import ingest_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/comparison")
WINDOW = 150
OVERLAP = 20


class SourceRequest(BaseModel):
    url: str


class AssetRequest(BaseModel):
    asset: str


class WindowRequest(AssetRequest):
    window: int = Field(ge=0)
    base_game: ComparisonGame = ComparisonGame.GTA5


class Cut(AssetRequest):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


class PairRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    gta6: Cut
    base_game: ComparisonGame = ComparisonGame.GTA5


class MatchRequest(PairRequest):
    recording: str


class BoardRenderRequest(PairRequest):
    older: Cut
    format: ComparisonFormat = ComparisonFormat.SHORTS_SPLIT
    tts_voice: str = "Charon"
    library_id: str | None = None


class Moment(BaseModel):
    start: float
    end: float
    question: str
    observation: str
    record: str


class Findings(BaseModel):
    moments: list[Moment]


class Match(BaseModel):
    confidence: int
    start: float
    end: float
    reason: str


class Observation(BaseModel):
    initial_state: str
    action_in_order: str
    visible_result: str


class Review(BaseModel):
    same_action: bool
    reason: str
    hook: str
    older_game: str
    gta6: str


def asset_path(name: str) -> Path:
    root = config.DOWNLOADS_DIR.resolve()
    path = root / name
    if (not name or Path(name).name != name or not name.startswith(("scan_", "rec_"))
            or path.resolve().parent != root or not path.is_file()):
        raise HTTPException(404, "Source file is unavailable. Scan the link or upload the recording again.")
    return path


def media_info(path: Path) -> tuple[float, str]:
    raw = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=codec_name,duration:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True)
    if raw.returncode == 0:
        data = json.loads(raw.stdout)
        for stream in data.get("streams", []):
            for value in (stream.get("duration"), data.get("format", {}).get("duration")):
                try:
                    duration = float(value)
                except (ValueError, TypeError):
                    continue
                if math.isfinite(duration) and duration >= 5:
                    return duration, stream["codec_name"]
    raise HTTPException(422, "Choose a readable video with at least five seconds of footage.")


def describe_asset(path: Path) -> dict:
    duration, codec = media_info(path)
    if path.suffix.lower() == ".mp4" and codec == "h264":
        url = f"/workspace/downloads/{quote(path.name)}"
    else:
        # Browsers cannot reliably seek in every supported capture format.
        preview = config.PROXIES_DIR / f"{path.name}.av-preview.mp4"
        if not preview.exists():
            with TemporaryDirectory(dir=config.PROXIES_DIR) as tmp:
                output = Path(tmp) / "preview.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                                "-map", "0:a:0?", "-c:a", "aac", "-b:a", "96k", "-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast",
                                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], check=True)
                output.replace(preview)
        url = f"/workspace/proxies/{quote(preview.name)}"
    return {"asset": path.name, "preview_url": url, "duration": duration, "windows": window_count(duration)}


def window_count(duration: float) -> int:
    return max(1, math.ceil((duration - OVERLAP) / WINDOW))


def bounded_cut(start: float, end: float, duration: float) -> bool:
    return math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration and 5 <= end - start <= 60


def action_cut(start: float, end: float, length: float) -> tuple[float, float] | None:
    """Keep brief impacts and reactions by including the footage around them."""
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= length + 0.05):
        return None
    end = min(end, length)
    if end - start < 10:
        span = min(10.0, length)
        start = max(0.0, min(start - (span - (end - start)) * 0.45, length - span))
        end = start + span
    return (round(start, 2), min(length, round(end, 2))) if bounded_cut(start, end, length) else None


def reviewed_clip(cut: Cut, output: Path) -> Path:
    path = asset_path(cut.asset)
    if not bounded_cut(cut.start, cut.end, media_info(path)[0]):
        raise HTTPException(422, "Each cut must be 5–60 seconds and lie within its source video.")
    return ingest_service.create_micro_verification_clip(path, cut.start, cut.end - cut.start, output)


def analyze(files: list[tuple[str, Path]], prompt: str, schema, fps=5):
    client = gemini_director._ensure_client()
    if not client:
        raise HTTPException(503, "Connect Gemini in Settings to analyze comparison footage.")
    parts = []
    for label, file in files:
        parts.append(types.Part.from_text(text=label))
        video = types.Part.from_bytes(data=file.read_bytes(), mime_type="video/mp4")
        video.video_metadata = types.VideoMetadata(fps=fps)
        parts.append(video)
    options = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.1)
    try:
        response = gemini_director._generate_content_with_retry(client, config.DIRECTOR_MODEL, [*parts, prompt], options)
        return schema.model_validate_json(response.text)
    except Exception as exc:
        logger.exception("Comparison vision request failed for %s", schema.__name__)
        raise HTTPException(502, "Gemini could not finish this footage review. Retry the section or recording.") from exc


def observe(file: Path) -> Observation:
    # Independent observations prevent the requested topic from biasing what the model sees.
    return analyze([("One unlabeled gameplay excerpt", file)], """Watch this excerpt independently.
Describe the initial physical state and location of the main subject, the motion or trigger in time order,
and the visible result. Distinguish what was already happening when the clip starts from what begins
on screen. Use visible evidence only. Do not infer player intent, objectives or unseen events.""", Observation)


def review_actions(request: PairRequest, older: Observation, six: Observation) -> Review:
    game = "GTA Five" if request.base_game == ComparisonGame.GTA5 else "GTA Four"
    return analyze([], f"""Two gameplay cuts were observed independently.
{game}: {older.model_dump_json()}
GTA Six: {six.model_dump_json()}
Question: {request.topic}
Check that BOTH observations supply positive evidence for the required starting conditions and physical
action. Check direction and order of motion. For example, a car entering water and a car leaving water
are different tests. Do not infer an attempted action from an outcome or the question. Different results
of the SAME test are valid. If setup or action is absent, set same_action=false, explain the specific
mismatch in plain English and leave the spoken lines empty. Otherwise write concise English narration.
The hook is a short question about the action naming "{game} versus GTA Six", aim for 8–11 words.
Give one short sentence for each game using its own observed sequence and result.""", Review)


def youtube_id(address: str) -> str:
    url = urlparse(address.strip())
    if url.scheme not in {"https", "http"} or url.hostname not in {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com", "www.youtu.be"}:
        raise HTTPException(422, "Enter a YouTube video link.")
    parts = url.path.strip("/").split("/")
    video_id = ""
    if url.hostname in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
        video_id = parts[0]
    elif parts == ["watch"]:
        video_id = parse_qs(url.query).get("v", [""])[0]
    elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
        video_id = parts[1]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
        raise HTTPException(422, "Enter a link to one YouTube video.")
    return video_id


@router.post("/source")
def open_source(request: SourceRequest):
    video_id = youtube_id(request.url)
    meta = ingest_service.download_or_link_video(f"https://youtu.be/{video_id}", f"scan_{uuid.uuid4().hex}",
                                                 reuse_cached_prefix="scan_")
    return {**describe_asset(Path(meta["raw_path"])), "title": meta.get("title") or video_id}


@router.post("/recording")
def open_recording(request: AssetRequest):
    return describe_asset(asset_path(request.asset))


@router.post("/topics")
def scan_window(request: WindowRequest):
    path = asset_path(request.asset)
    duration, _ = media_info(path)
    if request.window >= window_count(duration):
        raise HTTPException(422, "Scan window is outside the video.")
    offset = request.window * WINDOW
    length = min(WINDOW + OVERLAP, duration - offset)
    with TemporaryDirectory(dir=config.TEMP_DIR) as tmp:
        proxy = ingest_service.create_micro_verification_clip(path, offset, length, Path(tmp) / "scan.mp4", fps=2)
        findings = analyze([("GTA VI source window", proxy)], f"""Inspect this GTA VI video from beginning to end. List every distinct visible
gameplay action that a player can practically recreate in {request.base_game.value.upper()}. For each, give a short
English comparison question about the event itself (for example, "How does a seaplane lift off from water?").
Keep game names and tutorial language out of the question. Give one factual GTA VI observation and a precise
older-game recording instruction describing the same setup and action.
The outcome can differ. Skip menus, speculation, passive scenery, unrelated games, and repeated attempts.
Inspect each successive 15-second interval; include different tests that appear later in the excerpt.
Use start and end in decimal SECONDS relative to this excerpt (0 to {length:.2f}), never MM.SS.
Include the setup, action and visible result in one continuous 8–30 second cut when possible.
Omit unobserved events and return an empty list if nothing qualifies.""", Findings, fps=2)
    proposals = []
    for moment in findings.moments:
        cut = action_cut(moment.start, moment.end, length)
        if cut and moment.question.strip() and moment.record.strip():
            start, end = cut
            proposals.append(Finding(role="comparison", title=moment.question, start=round(start + offset, 2),
                end=min(duration, round(end + offset, 2)), reason=moment.observation, record=moment.record, tags=[]))
    cuts = review_cuts(ExplainerService(gemini_director), path, proposals)
    return {"topics": [{"id": uuid.uuid4().hex, "start": c.start, "end": c.end, "question": c.title,
                         "record": c.record, "observation": c.reason} for c in cuts if c is not None]}


@router.post("/match")
def match_recording(request: MatchRequest):
    path = asset_path(request.recording)
    duration, _ = media_info(path)
    candidates = []
    with TemporaryDirectory(dir=config.TEMP_DIR) as tmp:
        target = reviewed_clip(request.gta6, Path(tmp) / "reference.mp4")
        for index in range(window_count(duration)):
            offset = index * WINDOW
            length = min(WINDOW + OVERLAP, duration - offset)
            candidate = ingest_service.create_micro_verification_clip(path, offset, length, Path(tmp) / "attempt.mp4", fps=3)
            match = analyze([("VIDEO A — GTA VI reference", target),
                             ("VIDEO B — older-game recording to search", candidate)], f"""The first video is the selected GTA VI action.
The second is a {request.base_game.value} recording, possibly with multiple attempts. Compare the actual setup
and physical action for this question: {request.topic}. Outcomes may differ. Similar objects alone are insufficient.
Find the best complete attempt in the SECOND video only. Give its start/end in decimal seconds relative to the
second video's own 0–{length:.2f} timeline, including setup and result, ideally 10–25 seconds.
Give a confidence 0–100 and a short English reason. Use 0 if the action is absent.""", Match, fps=3)
            cut = action_cut(match.start, match.end, length)
            if match.confidence >= 65 and cut:
                start, end = cut
                candidates.append({"start": offset + start, "end": offset + end,
                                   "confidence": match.confidence, "reason": match.reason})
        if candidates:
            reference = observe(target)
            for candidate in sorted(candidates, key=lambda item: item["confidence"], reverse=True):
                cut = Cut(asset=request.recording, start=candidate["start"], end=candidate["end"])
                clip = reviewed_clip(cut, Path(tmp) / "candidate.mp4")
                review = review_actions(request, observe(clip), reference)
                if review.same_action:
                    return {"match": {**candidate, "reason": review.reason}}
    return {"match": None}


def prepare_render(request: BoardRenderRequest) -> ComparisonRenderRequest:
    with TemporaryDirectory(dir=config.TEMP_DIR) as tmp:
        older = reviewed_clip(request.older, Path(tmp) / "older.mp4")
        six = reviewed_clip(request.gta6, Path(tmp) / "six.mp4")
        review = review_actions(request, observe(older), observe(six))
    if not review.same_action:
        raise HTTPException(422, review.reason or "The two cuts show different actions. Adjust a cut or upload another attempt.")
    return ComparisonRenderRequest(
        format=request.format, base_game=request.base_game, hook_text=request.topic, tts_voice=request.tts_voice,
        gta6_url_or_path=str(asset_path(request.gta6.asset)), gta6_start_time=str(request.gta6.start),
        gta6_duration_sec=request.gta6.end - request.gta6.start, base_game_url_or_path=str(asset_path(request.older.asset)),
        base_game_start_time=str(request.older.start), base_game_duration_sec=request.older.end - request.older.start,
        narration=ComparisonNarration(hook=review.hook, older_game=review.older_game, gta6=review.gta6))
