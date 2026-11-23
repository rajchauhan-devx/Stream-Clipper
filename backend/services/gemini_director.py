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
    CropMode, CaptionStyle, ComparisonQuest, ComparisonGame
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
        preferred_voice: str = "Charon",
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> DirectorPlan:
        """
        Uploads 480p proxy to Gemini File API, prompts gemini-2.5-flash with
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

            # 3. Prompt Gemini Director for High-Retention Topics and Viral Storytelling
            prompt = f"""
You are the world's best Short-Form Video Director and Master Gaming Storyteller specializing in GTA 6, open-world gameplay, and viral TikTok / YouTube Shorts / Instagram Reels retention.
Analyze this raw gameplay video proxy and extract exactly {clip_count} viral, high-retention clips.

CORE RETENTION DIRECTIVE - NEVER CHOOSE BORING TOPICS:
1. STRICT FILTER: ZERO BORING OR MUNDANE TOPICS!
   - You MUST NEVER pick boring, mundane, repetitive, or filler segments.
   - FORBIDDEN TOPICS: Basic swimming in water, mundane wildlife/shark encounters with no stakes, regular driving down an empty road without action or chase, routine walking, shopping in clothing stores, or aimless roaming.
   - Mundane topics (like "underwater shark attack", "character swimming", "driving a car") KILL retention instantly and are strictly forbidden.

2. WHAT MAKES A CLIP VIRAL (WHAT TO HUNT FOR):
   Actively search the video for moments with maximum viewer curiosity, stakes, or adrenaline:
   - High-Stakes Action & Stunts: Insane stunts, near-death escapes, 5-star police pursuits, massive explosions, jet/heli stunts, chaotic physics, vehicle crashes.
   - Secrets, Easter Eggs & Unsolved Mysteries: Hidden map locations, underwater sunken secrets, illegal cartel stashes, hidden vaults, creepy lore, unexplained NPC behavior.
   - Mind-Blowing Details: Next-gen physics, unbelievable graphics details, unseen mechanics, or features 99% of players never noticed.
   - High-Stakes Missions & Suspenseful Dilemmas: Infiltration, stealth missions, betrayal, moral choices with consequences.

3. "CREATE OUR OWN STORY USING THE CLIP" (CRITICAL STORYTELLING INSTRUCTION):
   - Real gameplay often contains calm, exploratory, or free-roam footage (such as diving underwater, driving at night, navigating a swamp, walking through an abandoned warehouse, or flying across Vice City).
   - If the footage does not already have an obvious pre-scripted cutscene, DO NOT describe it with boring literal statements!
   - INSTEAD: USE THE GAMEPLAY VISUALS AS CINEMATIC B-ROLL TO CRAFT AN IMMERSIVE STORY, MYSTERY, OR SECRET MISSION!
   - Cleverly ground your story in the visual elements on screen so the visuals feel like a cinematic movie illustrating your story:
     * If footage is underwater/ocean: DO NOT say "character swimming with sharks". Frame it as: An illegal sunken cartel submarine carrying $10,000,000 in classified prototypes, an abandoned deep-sea research facility, or a legendary creature mystery in Vice City waters!
     * If footage is driving at night: Frame it as: A high-stakes midnight black-market drop, an urgent distress beacon, or a pursuit where one mistake means death!
     * If footage is exploring a secluded location: Frame it as: Uncovering an abandoned syndicate safehouse, investigating a Vice City urban legend, or a secret undercover contract!
     * If footage shows high-speed action or combat: Frame it as: The world-record stunt challenge, an impossible 5-star escape, or a legendary showdown!
   - Give the footage PURPOSE, DRAMA, and INTENSE CURIOSITY. The viewer must feel compelled to watch until the very end to see the outcome!

4. HOOK TEXT / TOPIC HEADLINE (3-6 WORDS):
   - The 'hook_text' is displayed on the prominent top headline banner.
   - It MUST be an irresistible, click-worthy, cool topic title that makes viewers freeze and watch.
   - Must be in uppercase with 1-2 relevant emojis.
   - Examples of COOL, viral topic hooks:
     * "THE SUNKEN CARTEL MYSTERY 🤫"
     * "SECRET $10M UNDERWATER VAULT 💰"
     * "99% OF PLAYERS MISSED THIS 🤯"
     * "VICE CITY'S UNFORGIVING 5-STAR HEAT 🚨"
     * "THE IMPOSSIBLE JET GETAWAY 🚀"
     * "WHY NOBODY VISITS THIS ISLAND 💀"
     * "THE UNDERCOVER HITMAN CONTRACT 🎯"
     * "DID ROCKSTAR REALLY HIDE THIS? 🔥"
   - NEVER use boring literal descriptions like "UNDERWATER SHARK ATTACK", "SWIMMING IN WATER", or "CAR DRIVING".

5. VOICEOVER SCRIPT & PACING REQUIREMENTS:
   - Target Language: {target_language.upper()} (e.g. Hinglish: natural, engaging Hinglish with cool gaming lingo; English: articulate, compelling; Hindi: natural, conversational Hindi).
   - Voiceover Pacing: {voiceover_pacing.upper()}.

   * If 'HOOK_ONLY':
     - Write an ultra-catchy opening hook of 5 to 8 words maximum (finishes under 2.5 seconds).
     - Must ignite intense curiosity about what happens next, then let the raw game audio take over.
     - Spoken in a calm, magnetic, confident tone (NOT screaming or hyper!).
     - Examples:
       * "Wait until you see what was hidden here!"
       * "This is why nobody goes here alone."
       * "He actually tried the impossible escape!"
       * "Watch what happens when the timer hits zero!"

   * If 'FULL_COMMENTARY' (Story Breakdown & Secret Lore):
     - Craft an engaging, complete storytelling script that spans the full duration of the clip (target 80 to 110 words for a 35-50s clip, spoken at a natural ~160 WPM storytelling pace).
     - Use the 4-part viral narrative structure:
       1. Curiosity Hook Question / Statement: Open with an intriguing mystery about what's on screen.
          (e.g., "What actually lies at the bottom of Vice City's deepest trench?", "How did this simple farm mission turn into the craziest secret in Vice City?")
       2. Setup & Second-Person Context ("You"): Address the viewer directly as 'you' progressing through the story.
          (e.g., "In Chapter 2, you receive encrypted coordinates leading to an abandoned underwater wreckage...", "After accepting a midnight contract, you arrive at...")
       3. Rising Tension & Deepening Mystery: Describe the escalating stakes or shocking revelation.
          (e.g., "As you dive closer, you notice emergency sirens flashing in the distance, and sonar picks up something massive moving in the dark...", "However, the guards were waiting for you...")
       4. Climax & Resolution: The dramatic payoff, choice, or twist ending.
          (e.g., "With only seconds of oxygen left, you pry open the hatch and discover what the cartel was hiding all along.", "Now you have to choose: fight your way out, or trigger the detonation and run.")
     - TONE GUIDELINES:
       * Calm, captivating, articulate, and suspenseful documentary storyteller (like top true-crime and gaming lore documentaries).
       * NEVER shout, screech, or sound cartoonishly excited.
       * Steady, natural pacing with cinematic intrigue that holds retention from first frame to last.

- Target Clip Length: {clip_length_range} per clip.
- Virality Score (1-100): Rate retention and hook potential.
- Crop Mode: ALWAYS set 'crop_mode' to 'center_zoom'.
- TTS Voice: You MUST set 'tts_voice' to '{preferred_voice}' or choose from: 'Charon' (deep cinematic male, best for storytelling), 'Aoede' (expressive female), 'Kore' (calm female), 'Fenrir' (commanding male), or 'Puck' (energetic male). Default to '{preferred_voice}'.
- Watermark & Streamer Webcam Detection: Inspect video frames carefully for any streamer webcam / facecam, third-party channel watermark, or logo (e.g. in top_right, top_left, bottom_right, or bottom_left).
  * If detected: set watermark_info.detected=True, watermark_info.label="<e.g. streamer_webcam or channel_logo>", and watermark_info.corner="top_right" | "top_left" | "bottom_right" | "bottom_left".
  * If clean: set watermark_info.detected=False, watermark_info.corner="none".
- Copyright Music Detection: Identify if in-game radio music is playing. If detected, set has_copyrighted_music=True.
- Social Metadata: Generate YouTube Shorts, Instagram Reels, and Facebook Reels titles, descriptions, and viral hashtags that match this cool story.
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
        voice_name: str = "Charon",
        pacing: str = "full_commentary",
        progress_callback: Optional[Callable[[int, str], None]] = None
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
        is_short_hook = word_count <= 10 or pacing == "hook_only"

        if is_short_hook:
            tts_prompt = (
                f"Speak this hook in a calm, confident, and magnetic storytelling tone with clear articulation. "
                f"Keep the listener intrigued. Do NOT shout, scream, or sound hyperactive or rushed: {clean_script}"
            )
        else:
            tts_prompt = (
                f"Narrate this in a calm, captivating, and suspenseful documentary storytelling tone. "
                f"Speak clearly and steadily with natural pauses, keeping the audience engaged from start to finish. "
                f"Do NOT shout, scream, or sound overly excited or rushed: {clean_script}"
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
                candidate_tts = ["gemini-2.5-flash-tts", TTS_MODEL, "gemini-3.1-flash-tts-preview"]
                for tm in candidate_tts:
                    try:
                        resp = client.models.generate_content(
                            model=tm,
                            contents=tts_prompt,
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
        """Generates realistic structured director plan with cool topics and story lore for testing"""
        cool_clips_data = [
            {
                "hook_text": "THE SUNKEN CARTEL SECRET 🤫",
                "summary": "Deep-sea discovery of an abandoned smuggling submarine carrying classified contraband.",
                "script": "Deep beneath Vice City's waters lies an abandoned cargo submarine carrying millions in cartel contraband. When players dove into the underwater trench, sonar detected an unmapped signal. But opening the hatch revealed a classified military prototype that was never supposed to be found.",
                "category": "GTA 6 • SECRET LORE"
            },
            {
                "hook_text": "THE IMPOSSIBLE 5-STAR GETAWAY 🚨",
                "summary": "High-octane escape evading SWAT roadblocks and helicopter pursuit across Vice City highway.",
                "script": "With maximum 5-star police heat and helicopters swarming above, this player pulled off the cleanest escape in Vice City history. Cornered at the docks with zero health remaining, one split-second jump changed everything.",
                "category": "GTA 6 • VIRAL MOMENT"
            },
            {
                "hook_text": "SECRET $10M ABANDONED VAULT 💰",
                "summary": "Hidden offshore vault location that 99% of players miss during the main story campaign.",
                "script": "Rockstar secretly hid a ten million dollar vault in a location that ninety-nine percent of players drive past without noticing. Inside the derelict warehouse behind the docks, an unmarked keypad unlocks the underground vault.",
                "category": "GTA 6 • HIDDEN VAULT"
            }
        ]
        clips = []
        for i in range(1, count + 1):
            start = (i - 1) * 35.0
            end = start + 34.0
            clip_meta = cool_clips_data[(i - 1) % len(cool_clips_data)]
            clip = ClipBlueprint(
                clip_id=f"clip_{i}",
                start_time=start,
                end_time=end,
                duration=34.0,
                virality_score=92 + (i % 8),
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

    # --------------------------------------------------------------------------
    # 4. Comparison Quest & Match Generator (Gemini Vision)
    # --------------------------------------------------------------------------
    def analyze_gta6_and_generate_quest(
        self,
        proxy_path: Path,
        base_game: str = "gta5",
        target_language: str = "hinglish",
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

            candidate_models = ["gemini-2.5-flash", DIRECTOR_MODEL, "gemini-2.0-flash"]
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

    def _generate_fallback_quest(self, base_game: str = "gta5", target_language: str = "hinglish") -> ComparisonQuest:
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
