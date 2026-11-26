import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import backend.config as app_config
import backend.main as app_main
from backend.schemas import (
    BeatTrim, CaptionStyle, ClipBlueprint, ClipVerificationResult, CropMode,
    DirectorPlan, FacebookMetadata, InstagramMetadata, SocialMetadata, StoryBeat, YouTubeMetadata
)
from backend.services.audio_processor import audio_processor
from backend.services.captioner import CaptionerService
from backend.services.gemini_director import GeminiDirectorService
from backend.services.ingest import IngestService, parse_time_str
from backend.services.renderer import VideoRenderer
from backend.services.video_cropper import VideoCropper
import start as launcher


class TestStreamClipper(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="sc_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Ingest & URL Cache Tests
    # ------------------------------------------------------------------
    def test_parse_time_str(self):
        self.assertEqual(parse_time_str("01:02:03"), 3723.0)
        self.assertEqual(parse_time_str("05:30"), 330.0)
        self.assertEqual(parse_time_str("42.5"), 42.5)
        self.assertEqual(parse_time_str(""), 0.0)
        self.assertEqual(parse_time_str(None), 0.0)
        self.assertEqual(parse_time_str("invalid"), 0.0)

    def test_ingest_url_cache_preserves_title_and_uses_json(self):
        svc = IngestService()
        svc.downloads_dir = self.tmp_dir / "downloads"
        svc.proxies_dir = self.tmp_dir / "proxies"
        svc.temp_dir = self.tmp_dir / "temp"
        svc.downloads_dir.mkdir(parents=True)
        svc.proxies_dir.mkdir(parents=True)
        svc.temp_dir.mkdir(parents=True)

        cached_raw = svc.downloads_dir / "job_prev_raw.mp4"
        cached_raw.write_bytes(b"0" * (11 * 1024 * 1024))  # >10MB cache threshold

        test_url = "https://youtu.be/test_video_123"
        cache_file = svc.downloads_dir / "url_cache.json"
        cache_file.write_text(
            json.dumps({
                test_url: {
                    "raw_path": str(cached_raw),
                    "title": "My Custom Gameplay Video",
                    "duration": 123.4,
                }
            }),
            encoding="utf-8",
        )

        with patch.object(svc, "_get_video_metadata", return_value={"width": 1920, "height": 1080, "fps": 60.0, "duration": 123.4, "file_size_mb": 11.0}):
            meta = svc.download_or_link_video(test_url, "job_new")

        self.assertEqual(meta["title"], "My Custom Gameplay Video")
        self.assertEqual(meta["duration"], 123.4)
        self.assertTrue(Path(meta["raw_path"]).exists())

    # ------------------------------------------------------------------
    # Gemini Director Priority & Config Reload Tests
    # ------------------------------------------------------------------
    def test_director_model_priority_order(self):
        ordered = GeminiDirectorService._unique_models(
            "gemini-3.8-flash",
            "gemini-2.5-flash",
            "gemini-3.8-flash",
            "gemini-2.0-flash",
        )
        self.assertEqual(ordered, ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"])
        # Ensure Google GenAI SDK accepts both response schemas without unsupported JSON Schema keywords
        from google.genai import types
        types.GenerateContentConfig(response_mime_type="application/json", response_schema=DirectorPlan)
        types.GenerateContentConfig(response_mime_type="application/json", response_schema=ClipVerificationResult)

    def test_director_fallback_plan_and_quest(self):
        svc = GeminiDirectorService()
        plan = svc._generate_fallback_plan("Test Video", count=2, language="hinglish")
        self.assertEqual(len(plan.clips), 2)
        self.assertGreaterEqual(len(plan.clips[0].beats), 2)
        quest = svc._generate_fallback_quest("gta4", "english")
        self.assertEqual(quest.base_game.value, "gta4")
        self.assertEqual(len(quest.gta5_steps), 3)

    # ------------------------------------------------------------------
    # Captioner Non-Overlapping Subtitles & Language Tests
    # ------------------------------------------------------------------
    def test_captioner_non_overlapping_cues_and_language_mapping(self):
        svc = CaptionerService()
        fake_words = [
            type("W", (), {"word": "hello", "start": 0.0, "end": 0.5})(),
            type("W", (), {"word": "world{1}", "start": 0.5, "end": 1.0})(),
            type("W", (), {"word": "again", "start": 1.0, "end": 1.4})(),
        ]
        fake_seg = type("Seg", (), {"words": fake_words})()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_seg], None)

        ass_out = self.tmp_dir / "subs.ass"
        audio_in = self.tmp_dir / "voice.wav"
        audio_in.write_bytes(b"RIFF")

        with patch.object(svc, "_get_whisper", return_value=mock_model):
            svc.generate_ass_subtitles(audio_in, ass_out, style=CaptionStyle.HORMOZI_YELLOW, target_language="hindi")

        mock_model.transcribe.assert_called_once()
        self.assertEqual(mock_model.transcribe.call_args.kwargs["language"], "hi")

        content = ass_out.read_text(encoding="utf-8")
        dialogues = [line for line in content.splitlines() if line.startswith("Dialogue:")]
        self.assertEqual(len(dialogues), 3)
        # First cue must end at or before 0:00:00.50 (start of second word), not 0.60
        first_parts = dialogues[0].split(",", 3)
        self.assertEqual(first_parts[1], "0:00:00.00")
        self.assertEqual(first_parts[2], "0:00:00.50")
        self.assertNotIn("{1}", dialogues[1].split(",,", 1)[1])

    # ------------------------------------------------------------------
    # FFmpeg End-to-End Smoke Test (Silent Video -> Crop -> Mix -> Render)
    # ------------------------------------------------------------------
    def test_ffmpeg_pipeline_silent_video_crop_and_render(self):
        raw_vid = self.tmp_dir / "raw_no_audio.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=1.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(raw_vid),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cropper = VideoCropper()
        cropper.temp_dir = self.tmp_dir
        cropped_vid = self.tmp_dir / "cropped.mp4"
        cropper.crop_to_vertical(raw_vid, 0.0, 1.0, cropped_vid, mode=CropMode.CENTER_ZOOM, mask_webcam=False)
        self.assertTrue(cropped_vid.exists())
        self.assertGreater(cropped_vid.stat().st_size, 1000)

        # Silent audio extraction fallback when source video has no audio stream
        game_wav = self.tmp_dir / "game.wav"
        app_main._extract_audio_or_silence(raw_vid, game_wav, duration_sec=1.0, start_sec=0.0)
        self.assertTrue(game_wav.exists())
        self.assertGreater(game_wav.stat().st_size, 1000)

        # Tone voiceover wav
        voice_wav = self.tmp_dir / "voice.wav"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8",
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(voice_wav),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        mixed_wav = self.tmp_dir / "mixed.wav"
        audio_processor.duck_and_mix_audio(game_wav, voice_wav, mixed_wav, game_volume_boost=1.5)
        self.assertTrue(mixed_wav.exists())

        renderer = VideoRenderer()
        renderer.renders_dir = self.tmp_dir
        renderer.assets_dir = self.tmp_dir
        banner_png = renderer.generate_topic_banner(
            "THIS IS AN EXTRAORDINARILY LONG TOPIC BANNER HEADLINE THAT MUST SHRINK AND FIT CLEANLY",
            "tjob",
            "c1",
        )
        self.assertTrue(banner_png.exists())

        ass_file = self.tmp_dir / "o'hare_test.ass"
        ass_file.write_text(
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,2,60,60,200,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:00.80,Default,,0,0,0,,TEST\n",
            encoding="utf-8",
        )

        final_mp4 = renderer.render_final_clip(
            cropped_video_path=cropped_vid,
            mixed_audio_path=mixed_wav,
            ass_subtitles_path=ass_file,
            overlay_png_path=None,
            job_id="tjob",
            clip_id="c1",
            watermark_corner="bottom_right",
            topic_banner_path=banner_png,
        )
        self.assertTrue(final_mp4.exists())
        self.assertGreater(final_mp4.stat().st_size, 1000)

        # Also verify FACECAM_SPLIT crop mode and both Comparison Render formats
        facecam_vid = self.tmp_dir / "facecam.mp4"
        cropper.crop_to_vertical(raw_vid, 0.0, 0.8, facecam_vid, mode=CropMode.FACECAM_SPLIT, mask_webcam=False)
        self.assertTrue(facecam_vid.exists())
        self.assertGreater(facecam_vid.stat().st_size, 1000)

        race_title = self.tmp_dir / "race-title.png"
        renderer.write_comparison_title("How do planes fly in GTA V vs GTA VI?", race_title)
        comp_short = self.tmp_dir / "comp_short.mp4"
        renderer.render_comparison_clip(
            base_video_path=raw_vid,
            gta6_video_path=raw_vid,
            mixed_audio_path=mixed_wav,
            output_path=comp_short,
            comparison_format="shorts_split",
            base_game="gta5",
            ass_subtitles_path=ass_file,
            title_path=race_title,
        )
        self.assertTrue(comp_short.exists())
        self.assertGreater(comp_short.stat().st_size, 1000)

        comp_long = self.tmp_dir / "comp_long.mp4"
        renderer.render_comparison_clip(
            base_video_path=raw_vid,
            gta6_video_path=raw_vid,
            mixed_audio_path=mixed_wav,
            output_path=comp_long,
            comparison_format="long_side_by_side",
            base_game="gta4",
            ass_subtitles_path=ass_file,
            title_path=race_title,
        )
        self.assertTrue(comp_long.exists())
        self.assertGreater(comp_long.stat().st_size, 1000)

    # ------------------------------------------------------------------
    # FastAPI Endpoints, Security Headers, Settings Reload & Upload Tests
    # ------------------------------------------------------------------
    def test_api_security_headers_cors_and_health(self):
        client = TestClient(app_main.app)
        res = client.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(res.headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertNotIn("access-control-allow-origin", res.headers)

        ok_res = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(ok_res.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_upload_recording_sanitizes_path_and_validates_extension(self):
        client = TestClient(app_main.app)
        dl_dir = self.tmp_dir / "downloads"
        dl_dir.mkdir(parents=True)

        with patch.object(app_main, "DOWNLOADS_DIR", dl_dir):
            bad_ext = client.post(
                "/api/comparison/upload-recording",
                files={"file": ("../../evil.exe", b"mz", "application/octet-stream")},
            )
            self.assertEqual(bad_ext.status_code, 400)

            empty = client.post(
                "/api/comparison/upload-recording",
                files={"file": ("clip.mp4", b"", "video/mp4")},
            )
            self.assertEqual(empty.status_code, 400)

            good = client.post(
                "/api/comparison/upload-recording",
                files={"file": ("../../my test clip.mp4", b"ftypmp42", "video/mp4")},
            )
            self.assertEqual(good.status_code, 200)
            saved_path = Path(good.json()["file_path"])
            self.assertTrue(saved_path.resolve().is_relative_to(dl_dir.resolve()))
            self.assertNotIn("..", saved_path.name)

    def test_download_rejects_traversal_ids(self):
        client = TestClient(app_main.app)
        res = client.get("/api/jobs/..%2Fetc/clips/c1/download")
        self.assertIn(res.status_code, (400, 404))

    def test_settings_update_preserves_comments_and_reloads_config(self):
        client = TestClient(app_main.app)
        fake_base = self.tmp_dir
        env_path = fake_base / ".env"
        env_path.write_text("# Important Comment\nGEMINI_API_KEY=\nDIRECTOR_MODEL=gemini-3.8-flash\n", encoding="utf-8")

        orig_base = app_config.BASE_DIR
        orig_main_base = app_main.BASE_DIR
        try:
            app_config.BASE_DIR = fake_base
            app_main.BASE_DIR = fake_base

            bad = client.post("/api/settings", json={"director_model": "bad\nINJECTED=1"})
            self.assertEqual(bad.status_code, 400)

            ok = client.post("/api/settings", json={"director_model": "gemini-2.5-flash"})
            self.assertEqual(ok.status_code, 200)
            written = env_path.read_text(encoding="utf-8")
            self.assertIn("# Important Comment", written)
            self.assertIn("DIRECTOR_MODEL=gemini-2.5-flash", written)
            self.assertEqual(app_config.DIRECTOR_MODEL, "gemini-2.5-flash")

            settings_res = client.get("/api/settings")
            self.assertEqual(settings_res.json()["director_model"], "gemini-2.5-flash")
        finally:
            app_config.BASE_DIR = orig_base
            app_main.BASE_DIR = orig_main_base
            app_config.reload_runtime_config()
            app_main.gemini_director.reload_client()

    def test_patch_clip_persists_social_metadata(self):
        client = TestClient(app_main.app)
        jobs_cache = self.tmp_dir / "jobs_db.json"
        sample_job = {
            "job_id": "job_test1",
            "request": {},
            "status": "completed",
            "progress_pct": 100,
            "step": "Done",
            "clips": [
                {
                    "clip_id": "clip_1",
                    "hook_text": "OLD HOOK",
                    "commentary_script": "Old script",
                    "social_metadata": {
                        "youtube": {"title": "Old", "description": "D", "tags": ["GTA6"], "privacy": "private"},
                        "instagram": {"caption": "IG", "hashtags": ["#gta6"]},
                        "facebook": {"caption": "FB", "hashtags": ["#GTA6"]},
                    },
                }
            ],
        }
        orig_db = dict(app_main.JOBS_DB)
        try:
            with patch.object(app_main, "JOBS_CACHE_FILE", jobs_cache):
                app_main.JOBS_DB.clear()
                app_main.JOBS_DB["job_test1"] = sample_job
                res = client.patch(
                    "/api/jobs/job_test1/clips/clip_1",
                    json={
                        "social_metadata": {
                            "youtube": {"title": "New Title", "description": "D2", "tags": ["GTA6"], "privacy": "unlisted"},
                            "instagram": {"caption": "IG2", "hashtags": ["#gta6"]},
                            "facebook": {"caption": "FB2", "hashtags": ["#GTA6"]},
                        }
                    },
                )
                self.assertEqual(res.status_code, 200)
                persisted = json.loads(jobs_cache.read_text(encoding="utf-8"))
                self.assertEqual(
                    persisted["job_test1"]["clips"][0]["social_metadata"]["youtube"]["title"],
                    "New Title",
                )
        finally:
            app_main.JOBS_DB.clear()
            app_main.JOBS_DB.update(orig_db)

    def test_client_secret_validation(self):
        client = TestClient(app_main.app)
        bad_json = client.post("/api/youtube/client-secret", json={"content": "{not json"})
        self.assertEqual(bad_json.status_code, 400)
        bad_shape = client.post("/api/youtube/client-secret", json={"content": '{"foo": "bar"}'})
        self.assertEqual(bad_shape.status_code, 400)

    def test_launcher_detects_node_package_manager(self):
        pkg_mgr = launcher.get_node_package_manager()
        self.assertTrue(Path(pkg_mgr).exists() or shutil.which(pkg_mgr) is not None)

    def test_comparison_list_endpoint_returns_saved_entries(self):
        client = TestClient(app_main.app)
        orig_comp = list(app_main.COMPARISONS_DB)
        try:
            app_main.COMPARISONS_DB.clear()
            app_main.COMPARISONS_DB.extend([
                {"comp_id": "comp_1", "format": "shorts_split", "hook_text": "First"},
                {"comp_id": "comp_2", "format": "long_side_by_side", "hook_text": "Second"},
            ])
            res = client.get("/api/comparison/list")
            self.assertEqual(res.status_code, 200)
            items = res.json()
            self.assertEqual([i["comp_id"] for i in items], ["comp_2", "comp_1"])
        finally:
            app_main.COMPARISONS_DB.clear()
            app_main.COMPARISONS_DB.extend(orig_comp)

    def test_websocket_snapshot_and_regenerate_voice_persists(self):
        client = TestClient(app_main.app)
        jobs_cache = self.tmp_dir / "jobs_db.json"
        voice_out = self.tmp_dir / "voice_regen.wav"
        voice_out.write_bytes(b"RIFF")

        orig_db = dict(app_main.JOBS_DB)
        try:
            with patch.object(app_main, "JOBS_CACHE_FILE", jobs_cache):
                app_main.JOBS_DB.clear()
                app_main.JOBS_DB["job_ws1"] = {
                    "job_id": "job_ws1",
                    "request": {"voiceover_pacing": "full_commentary"},
                    "status": "completed",
                    "progress_pct": 100,
                    "step": "Done",
                    "clips": [
                        {
                            "clip_id": "clip_1",
                            "commentary_script": "Test script",
                            "narration_language": "english",
                            "tts_voice": "Charon",
                        }
                    ],
                }
                with client.websocket_connect("/ws/progress/job_ws1") as ws:
                    snap = ws.receive_json()
                    self.assertEqual(snap["event"], "state_snapshot")
                    self.assertEqual(snap["job"]["job_id"], "job_ws1")

                with patch.object(app_main.gemini_director, "synthesize_voiceover", return_value=voice_out):
                    res = client.post("/api/jobs/job_ws1/clips/clip_1/regenerate-voice")
                    self.assertEqual(res.status_code, 200)
                    persisted = json.loads(jobs_cache.read_text(encoding="utf-8"))
                    self.assertEqual(
                        persisted["job_ws1"]["clips"][0]["voice_path"],
                        str(voice_out),
                    )
        finally:
            app_main.JOBS_DB.clear()
            app_main.JOBS_DB.update(orig_db)

    # ------------------------------------------------------------------
    # 4-Stage Human-Like Selection Funnel Tests
    # ------------------------------------------------------------------
    def test_audio_proxy_signals_and_micro_verification_clip(self):
        # Generate a 6s video with audio + sharp scene transition at 3s
        part1 = self.tmp_dir / "p1.mp4"
        part2 = self.tmp_dir / "p2.mp4"
        combo = self.tmp_dir / "combo.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=3",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=3",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(part1),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(part2),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        concat_txt = self.tmp_dir / "concat.txt"
        concat_txt.write_text(f"file '{part1}'\nfile '{part2}'\n", encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(combo),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        svc = IngestService()
        svc.proxies_dir = self.tmp_dir / "proxies"
        svc.proxies_dir.mkdir(parents=True)

        signals = svc.extract_timeline_signals(combo)
        self.assertGreater(signals["duration"], 5.0)
        self.assertTrue(any(p["time_sec"] >= 2.0 for p in signals["audio_peaks"]))
        self.assertTrue(any(2.0 <= c <= 4.0 for c in signals["scene_cuts"]))

        proxy = svc.create_lightweight_proxy(str(combo), "sigjob")
        self.assertTrue(proxy.exists())
        self.assertTrue(svc._has_audio_stream(proxy))

        micro = self.tmp_dir / "micro.mp4"
        svc.create_micro_verification_clip(combo, start_sec=2.0, duration_sec=3.0, output_path=micro, fps=5.0)
        self.assertTrue(micro.exists())
        self.assertTrue(svc._has_audio_stream(micro))

    def test_4stage_scout_verify_trim_and_ranking(self):
        src_vid = self.tmp_dir / "src10s.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=12",
            "-f", "lavfi", "-i", "sine=frequency=520:duration=12",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(src_vid),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        proxy = self.tmp_dir / "proxy.mp4"
        proxy.write_bytes(b"\x00" * 1024)

        def _make_clip(cid: str, start: float, dur: float, vscore: int) -> ClipBlueprint:
            return ClipBlueprint(
                clip_id=cid,
                clip_type="single_moment",
                start_time=start,
                end_time=start + dur,
                duration=dur,
                beats=[],
                virality_score=vscore,
                hook_text=f"HOOK {cid}",
                hook_summary="Summary",
                commentary_script="Short hook script",
                overlay_prompt="Badge",
                social_metadata=SocialMetadata(
                    youtube=YouTubeMetadata(title="T", description="D", tags=["GTA6"]),
                    instagram=InstagramMetadata(caption="C", hashtags=["#gta6"]),
                    facebook=FacebookMetadata(caption="F", hashtags=["#GTA6"]),
                ),
            )

        scout_plan = DirectorPlan(
            source_title="Test",
            duration_seconds=12.0,
            intro_end_time=0.0,
            overall_analysis="Fast action",
            clips=[
                _make_clip("cand_1", 1.0, 6.0, 95),  # High scout score, will fail verification
                _make_clip("cand_2", 3.0, 6.0, 88),  # Passes close-up verify with tighter trim
                _make_clip("cand_3", 4.0, 5.0, 80),  # Rejected
            ],
        )

        # Responses: 1 Scout call + 3 Close-Up Verify calls
        resp_scout = MagicMock(text=scout_plan.model_dump_json())
        resp_v1 = MagicMock(text=ClipVerificationResult(
            approved=False, quality_score=42, trim_start_offset=0.5, trim_end_offset=5.5,
            verdict="Rejected: Pause menu visible",
        ).model_dump_json())
        resp_v2 = MagicMock(text=ClipVerificationResult(
            approved=True, quality_score=96, trim_start_offset=1.5, trim_end_offset=8.5,
            verdict="Approved: Tight action trim",
        ).model_dump_json())
        resp_v3 = MagicMock(text=ClipVerificationResult(
            approved=False, quality_score=55, trim_start_offset=0.0, trim_end_offset=5.0,
            verdict="Rejected: Slow empty road",
        ).model_dump_json())

        mock_client = MagicMock()
        mock_client.is_adc = True
        mock_client.models.generate_content.side_effect = [resp_scout, resp_v1, resp_v2, resp_v3]

        director = GeminiDirectorService()
        director.temp_dir = self.tmp_dir
        director.client = mock_client
        director.is_adc = True

        with patch("backend.services.video_cropper.video_cropper.detect_streamer_fullscreen_intro", return_value=0.0):
            plan = director.analyze_gameplay_and_plan(
                proxy_path=proxy,
                source_title="Test",
                clip_count=1,
                source_video_path=src_vid,
                timeline_signals={"duration": 12.0, "audio_peaks": [{"time_sec": 4.0, "rms": 9000.0}], "scene_cuts": [3.0]},
                enable_closeup_verify=True,
            )

        # 1 final selected clip: cand_2 beat cand_1 because cand_2 passed close-up verification
        self.assertEqual(len(plan.clips), 1)
        self.assertEqual(plan.clips[0].hook_text, "HOOK cand_2")
        self.assertTrue(plan.clips[0].verification_passed)
        self.assertEqual(plan.clips[0].reviewer_score, 96)
        # cand_2 padded window started at max(0, 3.0-3.0)=0.0, trim_start_offset=1.5 -> 1.5s, trim_end=8.5 -> dur=7.0
        self.assertAlmostEqual(plan.clips[0].start_time, 1.5, places=1)
        self.assertAlmostEqual(plan.clips[0].duration, 7.0, places=1)
        self.assertEqual(len(plan.candidate_pool), 2)
        # Ensure cue sheet was passed in Scout prompt
        scout_prompt = mock_client.models.generate_content.call_args_list[0].kwargs["contents"][1]
        self.assertIn("4.0s (RMS=9000)", scout_prompt)
        # Ensure temporary verify_*.mp4 micro-clips were cleaned up
        self.assertEqual(list(self.tmp_dir.glob("verify_*.mp4")), [])

    def test_apply_verified_trims_multibeat_montage(self):
        clip = ClipBlueprint(
            clip_id="c1",
            clip_type="story_montage",
            start_time=10.0,
            end_time=45.0,
            duration=20.0,
            beats=[
                StoryBeat(beat_id="b1", label="Setup", start_time=10.0, duration=6.0),
                StoryBeat(beat_id="b2", label="Dead Air", start_time=20.0, duration=6.0),
                StoryBeat(beat_id="b3", label="Climax", start_time=35.0, duration=8.0),
            ],
            virality_score=90,
            hook_text="TEST",
            hook_summary="S",
            commentary_script="Script",
            overlay_prompt="P",
            social_metadata=SocialMetadata(
                youtube=YouTubeMetadata(title="T", description="D", tags=[]),
                instagram=InstagramMetadata(caption="C", hashtags=[]),
                facebook=FacebookMetadata(caption="F", hashtags=[]),
            ),
        )
        ver = ClipVerificationResult(
            approved=True,
            quality_score=94,
            beat_trims=[
                BeatTrim(beat_id="b1", trim_start_offset=1.0, trim_end_offset=5.5, approved=True, notes="Tight setup"),
                BeatTrim(beat_id="b2", trim_start_offset=0.0, trim_end_offset=4.0, approved=False, notes="Empty driving"),
                BeatTrim(beat_id="b3", trim_start_offset=2.0, trim_end_offset=9.0, approved=True, notes="Explosion payoff"),
            ],
            verdict="Dropped dead air beat b2 and tightened setup & climax",
        )
        windows = [(7.0, 12.0), (17.0, 12.0), (32.0, 14.0)]
        GeminiDirectorService._apply_verified_trims(clip, ver, windows, max_duration=60.0)
        self.assertEqual(len(clip.beats), 2)
        self.assertEqual([b.beat_id for b in clip.beats], ["b1", "b3"])
        self.assertAlmostEqual(clip.beats[0].start_time, 8.0, places=2)
        self.assertAlmostEqual(clip.beats[0].duration, 4.5, places=2)
        self.assertAlmostEqual(clip.beats[1].start_time, 34.0, places=2)
        self.assertAlmostEqual(clip.beats[1].duration, 7.0, places=2)
        self.assertAlmostEqual(clip.duration, 11.5, places=2)

    def test_emoji_strip_game_branding_and_watermark_gating(self):
        from backend.services.renderer import VideoRenderer
        from backend.schemas import WatermarkInfo, WatermarkCorner

        self.assertEqual(VideoRenderer._strip_emojis("🔥 GTA 5 • REEL 🚨"), "GTA 5 • REEL")
        renderer = VideoRenderer()
        renderer.assets_dir = self.tmp_dir
        banner = renderer.generate_topic_banner("FRANKLIN'S WILD GETAWAY 🚨🔥", "j_test", "c_test", "GTA 5 • VIRAL")
        self.assertTrue(banner.exists())
        badge_v = renderer._ensure_badge_png("GTA V")
        self.assertTrue(badge_v.exists())
        self.assertIn("gta_v", badge_v.name)

        self.assertEqual(
            app_main._detect_game_branding({"metadata": {"title": "Grand Theft Auto V Gameplay"}, "request": {}}),
            ("GTA 5", "GTA V"),
        )
        self.assertEqual(
            app_main._detect_game_branding({"metadata": {"title": "MY FIRST DAY IN VICE CITY | GTA 6"}, "request": {}}),
            ("GTA 6", "GTA VI"),
        )

        # Clean HUD gameplay must NOT mask webcam or draw corner badge
        clean_clip = {"watermark_info": WatermarkInfo(detected=False, corner=WatermarkCorner.NONE)}
        self.assertEqual(app_main._resolve_watermark_settings(clean_clip, True), (None, False, "top_right"))

        # Channel logo watermark triggers badge without blurring sky for webcam
        logo_clip = {"watermark_info": {"detected": True, "label": "channel_logo", "corner": "WatermarkCorner.BOTTOM_RIGHT"}}
        self.assertEqual(app_main._resolve_watermark_settings(logo_clip, True), ("bottom_right", False, "bottom_right"))

        # Streamer facecam triggers BOTH badge and corner blur
        cam_clip = {"watermark_info": {"detected": True, "label": "streamer_webcam", "corner": "top_right"}}
        self.assertEqual(app_main._resolve_watermark_settings(cam_clip, True), ("top_right", True, "top_right"))

    def test_apply_verified_trims_updates_script_and_clears_false_overlay(self):
        from backend.schemas import WatermarkInfo, WatermarkCorner
        clip = ClipBlueprint(
            clip_id="c2",
            clip_type="single_moment",
            start_time=10.0,
            end_time=24.0,
            duration=14.0,
            virality_score=88,
            hook_text="OLD BIKE HOOK 🚨",
            hook_summary="S",
            commentary_script="Franklin steals a motorcycle",
            overlay_prompt="P",
            watermark_info=WatermarkInfo(detected=True, label="mini_map", corner=WatermarkCorner.BOTTOM_LEFT),
            social_metadata=SocialMetadata(
                youtube=YouTubeMetadata(title="T", description="D", tags=[]),
                instagram=InstagramMetadata(caption="C", hashtags=[]),
                facebook=FacebookMetadata(caption="F", hashtags=[]),
            ),
        )
        ver = ClipVerificationResult(
            approved=True,
            quality_score=95,
            trim_start_offset=1.0,
            trim_end_offset=13.0,
            verified_hook_text="HIGH SPEED CAR CHASE",
            verified_script="Franklin rockets down Del Perro Freeway in a stolen white sports car.",
            has_third_party_overlay=False,
            verdict="Corrected vehicle from bike to white car and cleared HUD false positive",
        )
        GeminiDirectorService._apply_verified_trims(clip, ver, [(8.0, 18.0)], max_duration=100.0)
        self.assertEqual(clip.hook_text, "HIGH SPEED CAR CHASE")
        self.assertIn("white sports car", clip.commentary_script)
        self.assertFalse(clip.watermark_info.detected)
        self.assertEqual(clip.watermark_info.corner, WatermarkCorner.NONE)

    def test_ingest_canonical_youtube_cache_hit(self):
        from backend.services.ingest import IngestService
        ing = IngestService()
        ing.downloads_dir = self.tmp_dir
        fake_raw = self.tmp_dir / "src_yt.mp4"
        fake_raw.write_bytes(b"\x00" * (11 * 1024 * 1024))
        (self.tmp_dir / "url_cache.json").write_text(
            json.dumps({
                "https://youtu.be/169ZzvPxvvM?si=OLD": {
                    "raw_path": str(fake_raw),
                    "title": "GTA 6 Gameplay",
                    "duration": 1800.0,
                }
            }),
            encoding="utf-8",
        )
        meta = ing.download_or_link_video("https://www.youtube.com/watch?v=169ZzvPxvvM", "test_cache_hit")
        self.assertEqual(meta["title"], "GTA 6 Gameplay")
        self.assertTrue((self.tmp_dir / "test_cache_hit_raw.mp4").exists())

    def test_create_job_request_crop_mode_and_sanitize_timestamps(self):
        from backend.schemas import CreateJobRequest, CropMode
        req = CreateJobRequest(url_or_path="https://youtu.be/abc", crop_mode=CropMode.FACECAM_SPLIT)
        self.assertEqual(req.crop_mode, CropMode.FACECAM_SPLIT)

        plan = DirectorPlan(
            source_title="Bounded Test",
            duration_seconds=500.0,
            overall_analysis="ok",
            clips=[
                ClipBlueprint(
                    clip_id="c1",
                    clip_type="story_montage",
                    start_time=600.0,
                    end_time=630.0,
                    duration=30.0,
                    beats=[
                        StoryBeat(beat_id="b1", label="OOB", start_time=600.0, duration=12.0),
                        StoryBeat(beat_id="b2", label="End", start_time=495.0, duration=15.0),
                    ],
                    virality_score=90,
                    hook_text="TEST",
                    hook_summary="S",
                    commentary_script="Script",
                    overlay_prompt="P",
                    social_metadata=SocialMetadata(
                        youtube=YouTubeMetadata(title="T", description="D", tags=[]),
                        instagram=InstagramMetadata(caption="C", hashtags=[]),
                        facebook=FacebookMetadata(caption="F", hashtags=[]),
                    ),
                )
            ],
        )
        GeminiDirectorService._sanitize_plan_timestamps(plan, 500.0)
        for beat in plan.clips[0].beats:
            self.assertLessEqual(beat.start_time + beat.duration, 500.0)

        # Partial/empty beat_trims should still clamp bloated beat durations on a valid multi-beat clip
        ver_empty = ClipVerificationResult(
            approved=True, quality_score=88, trim_start_offset=0.0, trim_end_offset=4.0, verdict="ok"
        )
        fresh_clip = ClipBlueprint(
            clip_id="c_fresh",
            clip_type="story_montage",
            start_time=10.0,
            end_time=495.0,
            duration=45.0,
            beats=[
                StoryBeat(beat_id="b1", label="Setup", start_time=10.0, duration=25.0),
                StoryBeat(beat_id="b2", label="Payoff", start_time=480.0, duration=20.0),
            ],
            virality_score=90,
            hook_text="TEST",
            hook_summary="S",
            commentary_script="Script",
            overlay_prompt="P",
            social_metadata=SocialMetadata(
                youtube=YouTubeMetadata(title="T", description="D", tags=[]),
                instagram=InstagramMetadata(caption="C", hashtags=[]),
                facebook=FacebookMetadata(caption="F", hashtags=[]),
            ),
        )
        GeminiDirectorService._apply_verified_trims(fresh_clip, ver_empty, [(10.0, 25.0), (480.0, 20.0)], 500.0)
        self.assertEqual(len(fresh_clip.beats), 2)
        self.assertLessEqual(fresh_clip.beats[0].duration, 10.0)

        # Duplicate OOB beats clamped near EOF must deduplicate rather than looping identical footage
        dup_plan = DirectorPlan(
            source_title="Dup Beats",
            duration_seconds=500.0,
            overall_analysis="ok",
            clips=[
                ClipBlueprint(
                    clip_id="c_dup",
                    clip_type="story_montage",
                    start_time=610.0,
                    end_time=640.0,
                    duration=30.0,
                    beats=[
                        StoryBeat(beat_id="b1", label="First", start_time=120.0, duration=10.0),
                        StoryBeat(beat_id="b2", label="OOB1", start_time=620.0, duration=10.0),
                        StoryBeat(beat_id="b3", label="OOB2", start_time=635.0, duration=10.0),
                    ],
                    virality_score=85,
                    hook_text="TEST",
                    hook_summary="S",
                    commentary_script="Script",
                    overlay_prompt="P",
                    social_metadata=SocialMetadata(
                        youtube=YouTubeMetadata(title="T", description="D", tags=[]),
                        instagram=InstagramMetadata(caption="C", hashtags=[]),
                        facebook=FacebookMetadata(caption="F", hashtags=[]),
                    ),
                )
            ],
        )
        GeminiDirectorService._sanitize_plan_timestamps(dup_plan, 500.0)
        self.assertEqual(len(dup_plan.clips[0].beats), 2)
        self.assertAlmostEqual(dup_plan.clips[0].beats[0].start_time, 120.0, places=1)
        self.assertLessEqual(dup_plan.clips[0].beats[1].start_time + dup_plan.clips[0].beats[1].duration, 500.0)

    def test_synchronize_voice_and_render_span_prevents_audio_cutoff(self):
        import wave
        from backend.main import _synchronize_voice_and_render_span, _probe_audio_duration

        voice_in = self.tmp_dir / "long_voice.wav"
        voice_out = self.tmp_dir / "synced_voice.wav"
        # Write 12.5s PCM WAV @ 24kHz
        sample_rate = 24000
        n_frames = int(sample_rate * 12.5)
        with wave.open(str(voice_in), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * n_frames)

        # Planned 2 beats totaling 10s, while voice is 12.5s -> should extend final beat within max_source_dur
        beats = [
            {"beat_id": "b1", "label": "Setup", "start_time": 10.0, "duration": 5.0},
            {"beat_id": "b2", "label": "Payoff", "start_time": 30.0, "duration": 5.0},
        ]
        out_path, new_beats, new_dur = _synchronize_voice_and_render_span(
            voice_path=voice_in,
            beats_list=beats,
            clip_dur=10.0,
            start_time=10.0,
            cut_start_sec=0.0,
            use_raw_offset=False,
            max_source_dur=100.0,
            norm_voice_out=voice_out,
        )
        total_span = sum(float(b["duration"]) for b in new_beats)
        self.assertGreater(total_span, 12.5)
        self.assertAlmostEqual(new_dur, 10.0)

        # Now constrain max_source_dur tightly so clip cannot extend -> must apply gentle FFmpeg atempo
        voice_out_tempo = self.tmp_dir / "synced_voice_tempo.wav"
        single_out_path, _, single_new_dur = _synchronize_voice_and_render_span(
            voice_path=voice_in,
            beats_list=[],
            clip_dur=10.5,
            start_time=89.0,
            cut_start_sec=0.0,
            use_raw_offset=False,
            max_source_dur=100.0,
            norm_voice_out=voice_out_tempo,
        )
        self.assertEqual(single_out_path, voice_out_tempo)
        self.assertTrue(voice_out_tempo.exists())
        probed_dur = _probe_audio_duration(voice_out_tempo)
        self.assertGreater(probed_dur, 5.0)
        self.assertLessEqual(probed_dur, single_new_dur)

    def test_enforce_non_overlapping_beats_prevents_replay_rewind(self):
        from backend.services.gemini_director import GeminiDirectorService
        from backend.schemas import StoryBeat

        beats = [
            StoryBeat(beat_id="b1", label="A", start_time=22.4, duration=8.6),
            StoryBeat(beat_id="b2", label="B", start_time=26.4, duration=6.0),
            StoryBeat(beat_id="b3", label="C", start_time=42.4, duration=5.6),
        ]
        cleaned = GeminiDirectorService._enforce_non_overlapping_beats(beats, 500.0)
        self.assertEqual(len(cleaned), 3)
        self.assertAlmostEqual(cleaned[0].start_time, 22.4, places=1)
        self.assertAlmostEqual(cleaned[0].duration, 4.0, places=1)
        self.assertAlmostEqual(cleaned[1].start_time, 26.4, places=1)
        self.assertAlmostEqual(cleaned[2].start_time, 42.4, places=1)


if __name__ == "__main__":
    unittest.main()
