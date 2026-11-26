from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator

# ------------------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------------------
class OperatingMode(str, Enum):
    AUTO_PILOT = "auto_pilot"
    MANUAL_STUDIO = "manual_studio"

class CropMode(str, Enum):
    ACTION_TRACK = "action_track"
    FACECAM_SPLIT = "facecam_split"
    CENTER_ZOOM = "center_zoom"

class CaptionStyle(str, Enum):
    HORMOZI_YELLOW = "hormozi_yellow"
    NEON_CYAN = "neon_cyan"
    CLEAN_WHITE = "clean_white"

class TargetLanguage(str, Enum):
    HINGLISH = "hinglish"
    ENGLISH = "english"
    HINDI = "hindi"

class VoiceoverPacing(str, Enum):
    HOOK_ONLY = "hook_only"
    FULL_COMMENTARY = "full_commentary"

class VideoFormat(str, Enum):
    HIGHLIGHT = "highlight"
    EXPLAINER = "explainer"

class LongVideoStrategy(str, Enum):
    SEGMENT_HOPPER = "segment_hopper"
    FULL_VOD_BATCH = "full_vod_batch"
    ENERGY_PEAKS = "energy_peaks"

class WatermarkCorner(str, Enum):
    NONE = "none"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_LEFT = "bottom_left"
    TOP_RIGHT = "top_right"
    TOP_LEFT = "top_left"

class CreatorOverlayRegion(BaseModel):
    kind: str = Field(description="facecam, channel_logo, or creator_text; never ordinary game HUD")
    label: str = ""
    x: float = Field(ge=0, le=1, allow_inf_nan=False, description="Left edge as fraction of original source width")
    y: float = Field(ge=0, le=1, allow_inf_nan=False, description="Top edge as fraction of original source height")
    width: float = Field(ge=0, le=1, allow_inf_nan=False)
    height: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def inside_source(self):
        if self.width <= 0 or self.height <= 0 or self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("Creator overlay rectangle extends outside the source frame")
        return self


class WatermarkInfo(BaseModel):
    detected: bool = Field(default=False, description="Whether a third-party channel name, watermark, or streamer cam is detected")
    label: Optional[str] = Field(default=None, description="The detected watermark text or handle (e.g. MKIceAndFire)")
    corner: WatermarkCorner = Field(default=WatermarkCorner.NONE, description="Corner location: bottom_right, bottom_left, top_right, top_left, or none")
    regions: List[CreatorOverlayRegion] = Field(default_factory=list, description="All creator overlay rectangles in normalized ORIGINAL source coordinates; include full facecam box and every separate creator logo/name")

class JobStatus(str, Enum):
    PENDING = "pending"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    SCRIPTING = "scripting"
    VOICING = "voicing"
    CROPPING = "cropping"
    CAPTIONING = "captioning"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# ------------------------------------------------------------------------------
# Social Media Platform Metadata
# ------------------------------------------------------------------------------
class YouTubeMetadata(BaseModel):
    title: str = Field(..., max_length=100, description="Punchy YouTube Shorts title with hashtags")
    description: str = Field(..., description="Shorts description with relevant tags and links")
    tags: List[str] = Field(default_factory=list, description="Relevant YouTube tags")
    privacy: str = Field(default="private", description="Upload privacy: public, private, or unlisted")

class InstagramMetadata(BaseModel):
    caption: str = Field(..., max_length=2200, description="Engaging Instagram Reels caption with emojis")
    hashtags: List[str] = Field(default_factory=list, description="Top 15-25 trending Instagram hashtags")

class FacebookMetadata(BaseModel):
    caption: str = Field(..., description="Facebook Reels post text and hashtags")
    hashtags: List[str] = Field(default_factory=list, description="Trending hashtags for FB Reels")

class SocialMetadata(BaseModel):
    youtube: YouTubeMetadata
    instagram: InstagramMetadata
    facebook: FacebookMetadata

# ------------------------------------------------------------------------------
# Clip & Director Plan Schemas
# ------------------------------------------------------------------------------
class StoryBeat(BaseModel):
    rank: Optional[int] = Field(default=None, ge=1, le=5)
    wide: bool = False
    focus_x: float = Field(default=0.5, ge=0, le=1)
    beat_id: str = Field(..., description="Unique beat identifier (e.g., beat_1, setup, climax)")
    label: str = Field(..., description="Short punchy beat title (e.g. 'Mission Briefing', 'Infiltration', 'SWAT Ambush', 'Boat Escape')")
    start_time: float = Field(..., description="Start timestamp in seconds from raw video")
    duration: float = Field(..., description="Duration of this beat in seconds (typically 5s-14s)")
    description: Optional[str] = Field(default="", description="What happens visually in this beat")
    narration: str = Field(default="", description="Explainer commentary spoken during this scene")
    role: str = Field(default="", description="Editorial purpose: context, development, detail, or conclusion")
    evidence_id: str = Field(default="", description="Source observation supporting this explainer scene")

class ClipBlueprint(BaseModel):
    clip_id: str = Field(..., description="Unique clip identifier (e.g., clip_1)")
    clip_type: str = Field(default="story_montage", description="'story_montage' for multi-beat narrative arc or 'single_moment' for continuous action")
    video_format: VideoFormat = VideoFormat.HIGHLIGHT
    start_time: float = Field(..., description="Start timestamp in seconds from raw video (or first beat start)")
    end_time: float = Field(..., description="End timestamp in seconds from raw video")
    duration: float = Field(..., description="Total combined duration in seconds (typically 30s-55s)")
    beats: List[StoryBeat] = Field(default_factory=list, description="List of 2-4 narrative story beats stitched together into one short")
    virality_score: int = Field(..., ge=1, le=100, description="Virality potential rating from 1 to 100")
    reviewer_score: int = Field(default=92, ge=1, le=100, description="Senior Reviewer AI quality rating from 1 to 100")
    reviewer_verdict: str = Field(default="Approved: High-retention story arc with zero dead air", description="Senior Reviewer audit notes")
    hook_text: str = Field(..., description="Immediate attention-grabbing visual hook text (0-3s)")
    hook_summary: str = Field(..., description="Brief 1-sentence synopsis of why this moment is viral")
    commentary_script: str = Field(..., description="Ultra-short punchy opening hook (4-7 words maximum, finishes under 2.5s)")
    has_copyrighted_music: bool = Field(default=False, description="True if GTA in-game radio music is playing")
    detected_music_name: Optional[str] = Field(default=None, description="Name/artist of detected song if any")
    overlay_prompt: str = Field(..., description="Visual prompt for gemini-3.1-flash-image callout graphic")
    overlay_path: Optional[str] = Field(default=None, description="Local path to generated callout PNG")
    crop_mode: CropMode = Field(default=CropMode.CENTER_ZOOM, description="Vertical framing method: center_zoom (Landscape centered with blurred background), action_track, facecam_split")
    watermark_info: WatermarkInfo = Field(default_factory=WatermarkInfo, description="AI-detected third-party watermark or creator tag info")
    caption_style: CaptionStyle = Field(default=CaptionStyle.HORMOZI_YELLOW, description="Subtitle visual preset")
    voiceover_pacing: VoiceoverPacing = Field(default=VoiceoverPacing.HOOK_ONLY, description="Pacing: 3-6s hook only or full commentary")
    tts_voice: str = Field(default="Charon", description="Gemini TTS voice persona: Charon (cinematic/storytelling male), Aoede (smooth female), Kore (calm female), Fenrir (commanding male), Puck (energetic)")
    is_pure_gameplay: bool = Field(default=True, description="True if clip contains pure in-game footage without full-screen streamer webcam/talking head")
    social_metadata: SocialMetadata
    rendered_video_path: Optional[str] = Field(default=None, description="Local path to final 1080x1920 MP4")
    preview_url: Optional[str] = Field(default=None, description="Static URL to stream preview in Studio UI")
    status: str = Field(default="ready", description="Clip status: ready, rendering, rendered, error")
    verification_passed: bool = Field(default=False, description="True if verified and frame-trimmed via 5 FPS close-up pass")
    verification_notes: Optional[str] = Field(default=None, description="Notes from close-up visual & audio verification pass")
    narration_language: str = Field(default="", description="Language of verified narration; blank for legacy clips requiring migration")


class BeatTrim(BaseModel):
    beat_id: str = Field(..., description="Identifier of the beat being trimmed")
    trim_start_offset: float = Field(..., ge=0.0, description="Trimmed start offset in seconds relative to this beat's micro-clip")
    trim_end_offset: float = Field(..., ge=0.0, description="Trimmed end offset in seconds relative to this beat's micro-clip")
    approved: bool = Field(default=True, description="Whether this beat shows clear action/payoff without dead air or menus")
    notes: Optional[str] = Field(default=None, description="What happens in this beat visually and audibly")


class ClipVerificationResult(BaseModel):
    approved: bool = Field(..., description="True if candidate delivers engaging pure gameplay with clear hook/payoff")
    quality_score: int = Field(..., ge=1, le=100, description="Close-up editorial retention score 1-100")
    trim_start_offset: float = Field(default=0.0, ge=0.0, description="Start offset in seconds relative to micro-clip start (for single_moment)")
    trim_end_offset: float = Field(default=0.0, ge=0.0, description="End offset in seconds relative to micro-clip start (for single_moment)")
    beat_trims: List[BeatTrim] = Field(default_factory=list, description="Per-beat trim adjustments (for story_montage)")
    verified_hook_text: Optional[str] = Field(default=None, description="Crisp 3-6 word uppercase title grounded strictly in what happens in these verified 5-FPS frames (no emojis needed)")
    verified_script: Optional[str] = Field(default=None, description="Voiceover narration rewritten strictly around what visibly and audibly occurs in the verified trimmed frames, sized to match the verified duration")
    has_third_party_overlay: Optional[bool] = Field(default=None, description="True ONLY if an actual channel logo/handle watermark or streamer facecam box appears; false for clean game HUD")
    focus_hint: Optional[str] = Field(default=None, description="Visual focus area or detail worth highlighting")
    verdict: str = Field(..., description="Concise editorial justification based on close-up frames & audio")


class DirectorPlan(BaseModel):
    source_title: str = Field(..., description="Title of the input gameplay video")
    duration_seconds: float = Field(..., description="Total duration of analyzed gameplay video")
    intro_end_time: float = Field(default=0.0, description="Timestamp in seconds where streamer full-screen talking-head intro ends and pure in-game gameplay starts")
    reviewer_summary: str = Field(default="Senior Reviewer approved: High-retention story arcs with zero dead air.", description="Senior Reviewer overall evaluation")
    detected_radio_songs: List[str] = Field(default_factory=list, description="All copyrighted tracks detected")
    overall_analysis: str = Field(..., description="Gemini Vision director notes on gameplay pace and highlights")
    clips: List[ClipBlueprint] = Field(..., min_length=1, description="List of generated clip blueprints")
    candidate_pool: List[ClipBlueprint] = Field(default_factory=list, description="Additional scouted backup candidates ranked during close-up verification")

# ------------------------------------------------------------------------------
# Request & Progress Schemas
# ------------------------------------------------------------------------------
class CreateJobRequest(BaseModel):
    url_or_path: str = Field(..., description="YouTube URL or local file path to raw MP4")
    mode: OperatingMode = Field(default=OperatingMode.AUTO_PILOT, description="Execution mode")
    video_format: VideoFormat = VideoFormat.HIGHLIGHT
    explainer_topic: str = Field(default="", max_length=300, description="Optional topic to look for; blank discovers interesting stories")
    target_language: TargetLanguage = Field(default=TargetLanguage.ENGLISH, description="English narration; legacy Hindi/Hinglish requests normalize to English")
    clip_length_range: str = Field(default="30s-55s", description="Target clip length (e.g. 30s-55s)")
    clip_count: int = Field(default=3, ge=1, le=10, description="Number of viral clips to extract")
    copyright_guard: bool = Field(default=True, description="Strip in-game GTA radio music via Demucs")
    strip_streamer_voice: bool = Field(default=True, description="Isolate and remove streamer microphone speech via Demucs")
    voiceover_pacing: VoiceoverPacing = Field(default=VoiceoverPacing.FULL_COMMENTARY, description="Voiceover style: hook_only (3-6s) or full_commentary")
    tts_voice: str = Field(default="Charon", description="Preferred TTS voice persona: Charon (cinematic storytelling), Aoede (smooth female), Kore (calm female), Fenrir (commanding male), Puck (energetic)")
    caption_style: CaptionStyle = Field(default=CaptionStyle.HORMOZI_YELLOW, description="Default caption style")
    crop_mode: Optional[CropMode] = Field(default=None, description="Vertical framing preset: center_zoom, facecam_split, or action_track")
    enable_callout_overlay: bool = Field(default=False, description="Burn in top meme callout sticker overlay (default: False for clean gameplay)")
    enable_watermark_masker: bool = Field(default=True, description="Audit and hide creator facecams, logos and names before framing")
    enable_topic_header: bool = Field(default=True, description="Render attractive topic headline banner in top blurred zone")
    cut_start_time: str = Field(default="00:00:00", description="Start timestamp for video cutter (HH:MM:SS or MM:SS)")
    cut_duration_mins: Optional[float] = Field(default=20.0, description="Duration in minutes to cut and analyze with Gemini (1 to 60 mins)")
    auto_cut_long_videos: bool = Field(default=True, description="Automatically cuts videos longer than 60 mins into safe segments under Gemini's token limit")
    long_video_strategy: LongVideoStrategy = Field(default=LongVideoStrategy.SEGMENT_HOPPER, description="Strategy for long videos: segment_hopper, full_vod_batch, or energy_peaks")
    game_volume_boost: float = Field(default=1.5, description="Audio boost multiplier for in-game sound effects (1.0 = Normal, 1.5 = Boosted SFX, 2.0 = High Impact)")
    enable_closeup_verify: bool = Field(default=True, description="Check the portrait framing of verified highlights. The setup and payoff are always reviewed.")

    @model_validator(mode="after")
    def enforce_explainer_requirements(self):
        self.target_language = TargetLanguage.ENGLISH
        if self.video_format == VideoFormat.EXPLAINER:
            self.voiceover_pacing = VoiceoverPacing.FULL_COMMENTARY
            self.enable_closeup_verify = True
        return self

class UpdateClipRequest(BaseModel):
    commentary_script: Optional[str] = None
    hook_text: Optional[str] = None
    crop_mode: Optional[CropMode] = None
    caption_style: Optional[CaptionStyle] = None
    tts_voice: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    overlay_prompt: Optional[str] = None
    social_metadata: Optional[SocialMetadata] = None

class JobProgressUpdate(BaseModel):
    job_id: str
    status: JobStatus
    step: str
    progress_pct: int
    message: str
    error: Optional[str] = None
    clip_index: Optional[int] = None
    data: Optional[Dict[str, Any]] = None

class HardwareStatusResponse(BaseModel):
    os: str
    architecture: str
    device_name: str
    accelerator: str
    vram_gb: float
    ffmpeg_codec: str
    encoder_args: List[str]
    whisper_backend: str
    compute_type: str
    badge_label: str
    models: Dict[str, str]

class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    meta_access_token: Optional[str] = None
    meta_page_id: Optional[str] = None
    instagram_account_id: Optional[str] = None
    public_tunnel_url: Optional[str] = None
    director_model: Optional[str] = None
    tts_model: Optional[str] = None
    image_model: Optional[str] = None

class ResetPipelineRequest(BaseModel):
    job_id: Optional[str] = None
    delete_all: bool = True

class ResetPipelineResponse(BaseModel):
    status: str
    message: str
    freed_mb: float

class YouTubePublishRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    privacy: str = "public"  # "public", "private", "unlisted", "scheduled"
    publish_at: Optional[str] = None  # ISO 8601 string e.g. "2026-11-21T18:00:00Z"

class YouTubeAuthStatusResponse(BaseModel):
    has_token: bool
    has_client_secret: bool
    client_secrets_path: str
    channel_title: Optional[str] = None
    channel_avatar: Optional[str] = None
    channel_handle: Optional[str] = None
    channel_id: Optional[str] = None
    subscriber_count: Optional[str] = None
    auth_url: Optional[str] = None

class FacebookPublishRequest(BaseModel):
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    video_state: str = "PUBLISHED"  # "PUBLISHED", "SCHEDULED", "DRAFT"
    scheduled_publish_time: Optional[int] = None  # Epoch timestamp in seconds
    page_id: Optional[str] = None

class FacebookStatusResponse(BaseModel):
    has_token: bool
    has_page_id: bool
    page_id: Optional[str] = None

# ------------------------------------------------------------------------------
# Comparison Studio Schemas
# ------------------------------------------------------------------------------
class ComparisonFormat(str, Enum):
    SHORTS_SPLIT = "shorts_split"          # 9:16 Vertical (Top: Older Game, Bottom: GTA 6)
    LONG_SIDE_BY_SIDE = "long_side_by_side" # 16:9 Landscape (Left: Older Game, Right: GTA 6)

class ComparisonGame(str, Enum):
    GTA5 = "gta5"
    GTA4 = "gta4"

class ComparisonQuest(BaseModel):
    quest_id: str
    test_title: str
    gta6_summary: str
    location: str
    gta5_steps: List[str]
    recommended_duration_sec: float = 15.0
    hook_text: str
    commentary_script: str
    base_game: ComparisonGame = ComparisonGame.GTA5
    social_metadata: Optional[SocialMetadata] = None

class ComparisonQuestRequest(BaseModel):
    gta6_url_or_path: str
    base_game: ComparisonGame = ComparisonGame.GTA5
    target_language: TargetLanguage = TargetLanguage.ENGLISH
    start_time: str = "00:00:00"
    duration_sec: float = 20.0

    @model_validator(mode="after")
    def english_only(self):
        self.target_language = TargetLanguage.ENGLISH
        return self

class ComparisonNarration(BaseModel):
    hook: str = Field(min_length=1, max_length=220)
    older_game: str = Field(min_length=1, max_length=1000)
    gta6: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def strip_passages(self):
        for name in ("hook", "older_game", "gta6"):
            passage = getattr(self, name).strip()
            if not passage:
                raise ValueError("Fill in all three parts of the comparison narration.")
            setattr(self, name, passage)
        return self


class ComparisonRenderRequest(BaseModel):
    library_id: Optional[str] = None
    quest_id: Optional[str] = None
    format: ComparisonFormat = ComparisonFormat.SHORTS_SPLIT
    base_game: ComparisonGame = ComparisonGame.GTA5
    gta6_url_or_path: str
    gta6_start_time: str = "00:00:00"
    gta6_duration_sec: float = 15.0
    base_game_url_or_path: str
    base_game_start_time: str = "00:00:00"
    base_game_duration_sec: float = 15.0
    hook_text: str = "GTA 5 VS GTA 6 • PHYSICS COMPARISON"
    commentary_script: Optional[str] = None
    narration: Optional[ComparisonNarration] = None
    tts_voice: str = "Charon"
    caption_style: CaptionStyle = CaptionStyle.HORMOZI_YELLOW

