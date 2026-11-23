from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

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

class WatermarkInfo(BaseModel):
    detected: bool = Field(default=False, description="Whether a third-party channel name, watermark, or streamer cam is detected")
    label: Optional[str] = Field(default=None, description="The detected watermark text or handle (e.g. MKIceAndFire)")
    corner: WatermarkCorner = Field(default=WatermarkCorner.NONE, description="Corner location: bottom_right, bottom_left, top_right, top_left, or none")

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
class ClipBlueprint(BaseModel):
    clip_id: str = Field(..., description="Unique clip identifier (e.g., clip_1)")
    start_time: float = Field(..., description="Start timestamp in seconds from raw video")
    end_time: float = Field(..., description="End timestamp in seconds from raw video")
    duration: float = Field(..., description="Duration in seconds (typically 30s-55s)")
    virality_score: int = Field(..., ge=1, le=100, description="Virality potential rating from 1 to 100")
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
    tts_voice: str = Field(default="Puck", description="Gemini TTS voice persona")
    social_metadata: SocialMetadata
    rendered_video_path: Optional[str] = Field(default=None, description="Local path to final 1080x1920 MP4")
    preview_url: Optional[str] = Field(default=None, description="Static URL to stream preview in Studio UI")
    status: str = Field(default="ready", description="Clip status: ready, rendering, rendered, error")

class DirectorPlan(BaseModel):
    source_title: str = Field(..., description="Title of the input gameplay video")
    duration_seconds: float = Field(..., description="Total duration of analyzed gameplay video")
    detected_radio_songs: List[str] = Field(default_factory=list, description="All copyrighted tracks detected")
    overall_analysis: str = Field(..., description="Gemini Vision director notes on gameplay pace and highlights")
    clips: List[ClipBlueprint] = Field(..., min_length=1, description="List of generated clip blueprints")

# ------------------------------------------------------------------------------
# Request & Progress Schemas
# ------------------------------------------------------------------------------
class CreateJobRequest(BaseModel):
    url_or_path: str = Field(..., description="YouTube URL or local file path to raw MP4")
    mode: OperatingMode = Field(default=OperatingMode.AUTO_PILOT, description="Execution mode")
    target_language: TargetLanguage = Field(default=TargetLanguage.HINGLISH, description="Commentary language")
    clip_length_range: str = Field(default="30s-55s", description="Target clip length (e.g. 30s-55s)")
    clip_count: int = Field(default=3, ge=1, le=10, description="Number of viral clips to extract")
    copyright_guard: bool = Field(default=True, description="Strip in-game GTA radio music via Demucs")
    strip_streamer_voice: bool = Field(default=True, description="Isolate and remove streamer microphone speech via Demucs")
    voiceover_pacing: VoiceoverPacing = Field(default=VoiceoverPacing.FULL_COMMENTARY, description="Voiceover style: hook_only (3-6s) or full_commentary")
    caption_style: CaptionStyle = Field(default=CaptionStyle.HORMOZI_YELLOW, description="Default caption style")
    enable_callout_overlay: bool = Field(default=False, description="Burn in top meme callout sticker overlay (default: False for clean gameplay)")
    enable_watermark_masker: bool = Field(default=True, description="AI-supervised watermark detection & dynamic GTA VI badge cover")
    enable_topic_header: bool = Field(default=True, description="Render attractive topic headline banner in top blurred zone")
    cut_start_time: str = Field(default="00:00:00", description="Start timestamp for video cutter (HH:MM:SS or MM:SS)")
    cut_duration_mins: Optional[float] = Field(default=20.0, description="Duration in minutes to cut and analyze with Gemini (1 to 60 mins)")
    auto_cut_long_videos: bool = Field(default=True, description="Automatically cuts videos longer than 60 mins into safe segments under Gemini's token limit")
    long_video_strategy: LongVideoStrategy = Field(default=LongVideoStrategy.SEGMENT_HOPPER, description="Strategy for long videos: segment_hopper, full_vod_batch, or energy_peaks")
    game_volume_boost: float = Field(default=1.5, description="Audio boost multiplier for in-game sound effects (1.0 = Normal, 1.5 = Boosted SFX, 2.0 = High Impact)")

class UpdateClipRequest(BaseModel):
    commentary_script: Optional[str] = None
    hook_text: Optional[str] = None
    crop_mode: Optional[CropMode] = None
    caption_style: Optional[CaptionStyle] = None
    tts_voice: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    overlay_prompt: Optional[str] = None

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
