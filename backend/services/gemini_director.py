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

from backend.config import (
    GEMINI_API_KEY, DIRECTOR_MODEL, TTS_MODEL, IMAGE_MODEL, ASSETS_DIR, TEMP_DIR
)
from backend.schemas import (
    DirectorPlan, ClipBlueprint, SocialMetadata,
    YouTubeMetadata, InstagramMetadata, FacebookMetadata,
    CropMode, CaptionStyle
)

logger = logging.getLogger("gta6-studio.director")

class GeminiDirectorService:
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.temp_dir = TEMP_DIR
        self.client: Optional[genai.Client] = None
        self.auth_mode = "Unconfigured"
        self.is_adc = False
        self.project_id = ""
        self._init_client()

    def _init_client(self):
        # 1. Primary: Check Google Cloud ADC (matching new-oms-native pattern)
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
                with open(adc_path) as f:
                    data = json.load(f)
                project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or data.get("quota_project_id") or ""
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
                if project_id:
                    self.client = genai.Client(vertexai=True, project=project_id, location=location)
                    self.auth_mode = f"Google Cloud ADC ({project_id})"
                    self.is_adc = True
                    self.project_id = project_id
                    logger.info(f"Initialized Gemini Client via Google ADC (Project: {project_id})")
                    return self.client
            except Exception as e:
                logger.warning(f"Failed to initialize ADC client: {e}")

        # 2. Secondary: GEMINI_API_KEY if configured
        api_key = os.getenv("GEMINI_API_KEY") or self.api_key
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                self.auth_mode = "Gemini API Key"
                self.is_adc = False
                logger.info("Initialized Gemini Client via GEMINI_API_KEY")
                return self.client
            except Exception as e:
                logger.warning(f"Could not initialize GenAI client: {e}")

        self.auth_mode = "Offline Demo Mode"
        return None

    def _ensure_client(self):
        if not self.client:
            self._init_client()
        return self.client

    # --------------------------------------------------------------------------
    # 1. Multimodal Video Analysis & Plan Generation
    # --------------------------------------------------------------------------
    def analyze_gameplay_and_plan(
        self,
        proxy_path: Path,
        source_title: str,
        target_language: str = "hinglish",
        clip_count: int = 3,
        clip_length_range: str = "30s-55s",
        voiceover_pacing: str = "hook_only",
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> DirectorPlan:
        """
        Uploads 480p proxy to Gemini File API, prompts gemini-3.8-flash with
        DirectorPlan response_schema, and immediately deletes remote file.
        """
        client = self._ensure_client()

        # If no client/API key, use intelligent algorithmic fallback for local testing
        if not client:
            logger.warning("GEMINI_API_KEY not configured. Generating offline blueprint plan.")
            return self._generate_fallback_plan(source_title, clip_count, target_language)

        if progress_callback:
            progress_callback(55, "Preparing gameplay video for Gemini Vision...")

        remote_file = None
        video_part = None
        compact_cleanup_path = None

        try:
            is_vertex = getattr(self, "is_adc", False) or getattr(getattr(client, "_api_client", None), "vertexai", False)

            if is_vertex:
                target_video_file = proxy_path
                file_size_mb = proxy_path.stat().st_size / (1024 * 1024)

                # Vertex AI inline Part limit is 20MB. If proxy > 18MB, downsample to ultra-compact < 18MB
                if file_size_mb > 18.0:
                    compact_cleanup_path = self.temp_dir / f"compact_{proxy_path.name}"
                    logger.info(f"Proxy is {file_size_mb:.1f}MB, compressing to compact video (<18MB) for Vertex AI...")
                    if progress_callback:
                        progress_callback(58, "Compressing proxy for Vertex AI Gemini Vision...")
                    import subprocess
                    subprocess.run([
                        "ffmpeg", "-y", "-i", str(proxy_path),
                        "-vf", "scale=-2:240,fps=0.25",
                        "-c:v", "libx264", "-crf", "34", "-preset", "ultrafast", "-an",
                        str(compact_cleanup_path)
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    target_video_file = compact_cleanup_path

                with open(target_video_file, "rb") as vf:
                    vid_bytes = vf.read()
                video_part = types.Part.from_bytes(data=vid_bytes, mime_type="video/mp4")
                logger.info(f"Loaded video Part ({len(vid_bytes)/1024/1024:.2f} MB) for Vertex AI Gemini Vision.")

            else:
                # Gemini Developer API with GEMINI_API_KEY supports client.files.upload
                try:
                    remote_file = client.files.upload(file=str(proxy_path))
                    logger.info(f"Uploaded proxy to Gemini File API: {remote_file.name}. Polling status...")
                    max_wait = 60
                    elapsed = 0
                    while remote_file.state.name != "ACTIVE" and elapsed < max_wait:
                        time.sleep(2)
                        elapsed += 2
                        remote_file = client.files.get(name=remote_file.name)
                        if remote_file.state.name == "FAILED":
                            raise RuntimeError("Gemini file processing failed on server.")
                    video_part = remote_file
                except Exception as ex:
                    logger.warning(f"client.files.upload failed ({ex}). Falling back to inline bytes...")
                    with open(proxy_path, "rb") as vf:
                        vid_bytes = vf.read()
                    video_part = types.Part.from_bytes(data=vid_bytes, mime_type="video/mp4")

            if progress_callback:
                progress_callback(65, "Gemini Vision analyzing video & planning viral clips...")

            # 3. Prompt Gemini Director with strict visual grounding
            prompt = f"""
You are the world's best Short-Form Video Director specializing in GTA 6 / high-octane gaming gameplay.
Analyze this raw gameplay video proxy and extract exactly {clip_count} viral clips.

CRITICAL VISUAL GROUNDING RULES (DO NOT HALLUCINATE):
- You MUST base all clip selection, summaries, and commentary STRICTLY on what is VISUALLY PRESENT in the video frames!
- DO NOT invent, assume, or hallucinate fictional cutscenes, trailer lore, shootouts, or events (like burning buildings, betrayal, cops) if they are NOT clearly visible in the footage!
- Identify the exact visual action occurring: What are the player/characters actually doing? (e.g. driving a vehicle, flying an aircraft, walking down a street, shopping, cutscene dialogue, escaping police).
- The 'hook_text' (3-5 words) and 'commentary_script' MUST 100% MATCH what is physically happening on screen at that timestamp!

REQUIREMENTS:
- Target Language: {target_language.upper()} (e.g. Hinglish: natural, energetic gaming slang, Hindi, or English).
- Voiceover Pacing: {voiceover_pacing.upper()}.
  * If 'HOOK_ONLY': You MUST write an ULTRA-SHORT, PUNCHY opening hook line of ONLY 4 TO 7 WORDS MAXIMUM (finishes in under 2 to 2.5 seconds).
    Do NOT make the starting line long. It MUST finish very fast so the viewer immediately gets immersed in the raw in-game gameplay audio.
    Examples of ideal short hooks:
    - "Caught in the act!" (4 words)
    - "Watch what happens next!" (4 words)
    - "Wait till you see this!" (5 words)
    - "Lucia pulled off the impossible!" (5 words)
    - "Bro did not expect this!" (5 words)
    - "They never saw this coming!" (5 words)
    STRICT REQUIREMENT: NEVER exceed 7 words! Keep it ultra-short and punchy so it finishes in 2 seconds.
  * If 'FULL_COMMENTARY':
    You MUST write continuous, captivating storytelling commentary in the EXACT viral "Story Lore Breakdown & Secret Explained" format (the exact style of top gaming lore reels like "How Kyle became the Red Hulk in GTA 6 Explained"):
    - DURATION & WORD COUNT: The voiceover MUST span the full duration of the clip (target 140 to 185 words for a 40-55s clip, spoken at a smooth, confident ~200 WPM pace).
    - EXACT 5-PART NARRATIVE STORYTELLING FORMULA:
      1. Intriguing Hook Question (Sentence 1):
         Open with a compelling rhetorical question that triggers intense curiosity about what's on screen.
         Reference example: "How is this monster looking character actually a normal man in GTA 6?"
         Other examples:
         - "How did this simple farm mission turn into the craziest monster in GTA 6?"
         - "Why does everyone in Vice City fear this secret hidden character?"
         - "What actually happens if you make this dangerous secret choice in GTA 6?"
      2. Immersive Second-Person Narrative Setup ("You"):
         Address the viewer directly as 'you' progressing through the story:
         - "In Chapter 2, you meet a farmer named Kyle, who asks you to help him spray chemicals on his farm using his crop duster plane."
         - "After completing the mission, he rewards you with $400."
      3. Escalation & Deepening Lore/Mystery:
         - "Later, he contacts you again, asking you to bring him more chemicals. So, you deliver a van full of chemicals and discover that he's using them to grow special strawberries that boost human abilities..."
         - "However, you can notice the terrifying side effects Kyle experiences from consuming too many..."
      4. Climax & Shocking Reveal:
         - "Now, in Chapter 3, you find out the police have surrounded Kyle's farm and ask you to bring him out. But when you enter the barn, you discover that Kyle has transformed into a giant monster!"
      5. Moral Choice, Resolution & Ending:
         - "Now you have two choices: either defeat Kyle and receive a $5,000 reward for helping the police, or help him escape."
         - "If you choose to help him, he defeats everyone except you, gives you a hug, and jumps away like the Hulk."
    - TONE & PACING:
      - Crisp, articulate, curious, documentary lore storyteller.
      - Never shout or scream; speak with calm, engaging intrigue and steady narrative momentum.
      - Ground the story in the on-screen events and characters seen in the footage.
- Target Clip Length: {clip_length_range} per clip.
- Virality Score (1-100): Rate retention and hook potential.
- Crop Mode: ALWAYS set 'crop_mode' to 'center_zoom'. 'center_zoom' centers the full 16:9 landscape gameplay in a 9:16 frame with a cinematic blurred background, keeping the gameplay completely uncropped and in full landscape view.
- TTS Voice: You MUST set 'tts_voice' to one of these exact names: 'Puck' (energetic male), 'Kore' (dynamic female), 'Charon' (deep cinematic male), 'Aoede' (expressive female), or 'Fenrir' (commanding male).
- Watermark & Streamer Webcam Detection: Inspect video frames carefully for any streamer webcam / facecam, third-party channel watermark, or logo (e.g. in top_right, top_left, bottom_right, or bottom_left).
  * If detected: set watermark_info.detected=True, watermark_info.label="<e.g. streamer_webcam or channel_logo>", and watermark_info.corner="top_right" | "top_left" | "bottom_right" | "bottom_left".
  * If clean (no foreign watermark or webcam): set watermark_info.detected=False, watermark_info.corner="none".
- Copyright Music Detection: Identify if in-game radio music is playing. If detected, set has_copyrighted_music=True.
- Social Metadata: Generate YouTube Shorts, Instagram Reels, and Facebook Reels titles, descriptions, and viral hashtags.
"""

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DirectorPlan,
                temperature=0.7
            )

            response = None
            candidate_models = ["gemini-2.5-flash", DIRECTOR_MODEL, "gemini-2.0-flash", "gemini-1.5-flash"]
            for m in candidate_models:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=[video_part, prompt],
                        config=config
                    )
                    logger.info(f"Director analysis successfully generated using model: {m}")
                    break
                except Exception as ex:
                    logger.warning(f"Director Model {m} failed ({ex}). Trying next candidate...")

            if not response:
                raise RuntimeError("All candidate director models failed.")

            # Parse JSON into DirectorPlan
            plan_json = json.loads(response.text)
            plan = DirectorPlan.model_validate(plan_json)

            if progress_callback:
                progress_callback(75, f"Director Plan generated with {len(plan.clips)} clips!")

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
        voice_name: str = "Puck",
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Path:
        """
        Converts commentary script to 24kHz audio WAV via gemini-3.8-flash-tts.
        """
        out_wav_path = ASSETS_DIR / f"{job_id}_{clip_id}_voice.wav"
        client = self._ensure_client()

        if progress_callback:
            progress_callback(80, f"Synthesizing voiceover for {clip_id} via Gemini TTS...")

        if client:
            try:
                # Normalize voice name to valid Gemini prebuilt voices
                valid_voices = {"Puck", "Charon", "Kore", "Fenrir", "Aoede"}
                safe_voice = voice_name if voice_name in valid_voices else "Puck"

                vc = types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=safe_voice)
                    )
                )
                cfg = types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=vc
                )
                candidate_tts = ["gemini-3.1-flash-tts-preview", TTS_MODEL, "gemini-2.5-flash-tts"]
                for tm in candidate_tts:
                    try:
                        resp = client.models.generate_content(
                            model=tm,
                            contents=f"Say energetically and fast in an entertaining gamer tone in under 2 seconds: {script}",
                            config=cfg
                        )
                        for part in resp.candidates[0].content.parts:
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

        # Fallback local TTS / Tone synthesizer if API key is absent
        self._generate_fallback_audio(script, out_wav_path)
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
                    model=IMAGE_MODEL,
                    contents=f"Generate a transparent PNG callout sticker/meme graphic for a gaming short: {prompt}. High resolution sticker style."
                )
                # If image bytes returned
                for part in resp.candidates[0].content.parts:
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
        """Generates realistic structured director plan for testing"""
        short_hooks = [
            "Caught in the act!",
            "She actually pulled this off!",
            "Bro did not expect that!",
            "Watch this insane police chase!",
            "They never saw this coming!"
        ]
        clips = []
        for i in range(1, count + 1):
            start = (i - 1) * 35.0
            end = start + 32.0
            clip_script = short_hooks[(i - 1) % len(short_hooks)]
            clip = ClipBlueprint(
                clip_id=f"clip_{i}",
                start_time=start,
                end_time=end,
                duration=32.0,
                virality_score=88 + i,
                hook_text=f"GTA 6 MOMENT #{i} 🚨",
                hook_summary=f"High-speed action and crazy stunt sequence #{i}",
                commentary_script=clip_script,
                has_copyrighted_music=False,
                detected_music_name=None,
                overlay_prompt=f"Gaming 'BUSTED' or 'WASTED' bold graphic badge for clip {i}",
                crop_mode=CropMode.ACTION_TRACK,
                caption_style=CaptionStyle.HORMOZI_YELLOW,
                tts_voice="Puck",
                social_metadata=SocialMetadata(
                    youtube=YouTubeMetadata(
                        title=f"GTA 6 Insane Moment You Missed! 🤯 #Shorts #GTA6",
                        description=f"Viral GTA 6 gameplay moment #{i}. Watch till the end! #GTA6 #Gaming #Shorts",
                        tags=["GTA6", "Gaming", "Shorts", "GTA 6 Gameplay", "Viral"],
                        privacy="private"
                    ),
                    instagram=InstagramMetadata(
                        caption=f"Bro GTA 6 physics are on another level! 💀🔥 What would you do here? #gta6 #gaming #reels",
                        hashtags=["#gta6", "#gaming", "#reels", "#grandtheftauto", "#viralreels"]
                    ),
                    facebook=FacebookMetadata(
                        caption=f"Crazy GTA 6 gameplay action #{i}! Tag your squad. #GTA6 #GamingReels",
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
        """Generates real spoken human voiceover using native macOS `say` or OS speech synthesis"""
        # Clean text of quotes and special characters for speech CLI
        clean_text = text.replace('"', '').replace("'", "").strip()
        if not clean_text:
            clean_text = "Wait till you see what happens next in Vice City!"

        # 1. Primary on macOS: use native `say` command with fast brisk rate (210 wpm)
        try:
            aiff_temp = output_path.with_suffix(".aiff")
            # Try high-retention English voice 'Daniel' or system default with energetic 210 wpm pace
            cmd = ["say", "-v", "Daniel", "-r", "210", "-o", str(aiff_temp), clean_text]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode != 0:
                # Fallback to system default voice if 'Daniel' is missing
                cmd = ["say", "-r", "210", "-o", str(aiff_temp), clean_text]
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
            ps_script = f"""
            Add-Type -AssemblyName System.Speech;
            $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer;
            $synth.Rate = 2;
            $synth.SetOutputToWaveFile('{output_path}');
            $synth.Speak('{clean_text}');
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

# Global instance
gemini_director = GeminiDirectorService()
