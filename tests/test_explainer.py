import asyncio
import json
import math
import struct
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from google.genai import types

import backend.main as app_main
from backend.schemas import CreateJobRequest, VideoFormat, VoiceoverPacing
from backend.services.explainer import (
    Discovery, Explanation, ExplanationPlan, ExplanationReview, ExplainerScene,
    ExplainerService, Observation, SceneReview, output_duration_range, scan_windows,
    provider_schema,
    NarrationRewrite,
)
from backend.services.gemini_director import GeminiDirectorService


class TestExplainer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="explainer_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.touch()
        self.director = MagicMock()
        self.director.temp_dir = self.root
        self.service = ExplainerService(self.director)
        self.story = Explanation(
            topic="The escape", synopsis="A briefing leads to an escape.", explanation_complete=True,
            scenes=[
                ExplainerScene(evidence_id="event_1", role="context", label="Briefing", start_time=5, duration=15, narration="The briefing explains the objective."),
                ExplainerScene(evidence_id="event_2", role="conclusion", label="Outcome", start_time=1110, duration=15, narration="They reach the escape boat."),
            ],
        )
        self.review = ExplanationReview(
            approved=True, explanation_complete=True, quality_score=88, verdict="Context and outcome are supported.",
            topic="A briefing and escape", synopsis="The objective and outcome are visible.",
            scenes=[
                SceneReview(scene_index=0, approved=True, trim_start_offset=0, trim_end_offset=15, narration="The briefing establishes their objective.", observation="Quiet briefing dialogue."),
                SceneReview(scene_index=1, approved=True, trim_start_offset=0, trim_end_offset=15, narration="They finally reach the escape boat.", observation="Boat escape visible."),
            ],
        )

    def _run(self, review=None, story=None, keep_cache=False):
        if not keep_cache:
            shutil.rmtree(self.root / "explainer_scan_cache", ignore_errors=True)
        discoveries = [
            Discovery(observations=[Observation(topic="Escape", role="context", start_time=5, end_time=20, description="A quiet briefing explains the objective.")]),
            Discovery(),
            Discovery(observations=[Observation(topic="Escape", role="conclusion", start_time=30, end_time=45, description="They reach the boat.")]),
        ]
        with (
            patch("backend.services.explainer.ingest_service._get_video_metadata", return_value={"duration": 1250}),
            patch.object(self.service, "_watch", side_effect=[review or self.review] if keep_cache else [*discoveries, review or self.review]) as watch,
            patch.object(self.service, "_request", return_value=ExplanationPlan(stories=[story or self.story])) as request,
        ):
            plan = self.service.analyze(self.source, "Mission", clip_count=1, window_seconds=600)
        return plan, watch, request

    def test_windows_cover_whole_source_with_boundary_overlap(self):
        windows = scan_windows(2851, window=1200)
        self.assertEqual(windows, [(0, 1200), (1140, 1200), (2280, 571)])
        self.assertEqual(scan_windows(60), [(0, 60)])
        self.assertEqual(scan_windows(700, start=120)[0][0], 120)
        for bad in (-1, 700, math.inf):
            with self.assertRaises(ValueError):
                scan_windows(700, start=bad)

    def test_explainer_enforces_full_commentary_and_verification_only_for_this_format(self):
        req = CreateJobRequest(url_or_path="test.mp4", video_format="explainer", voiceover_pacing="hook_only", enable_closeup_verify=False)
        self.assertEqual(req.voiceover_pacing, VoiceoverPacing.FULL_COMMENTARY)
        self.assertTrue(req.enable_closeup_verify)
        legacy = CreateJobRequest(url_or_path="test.mp4", voiceover_pacing="hook_only", enable_closeup_verify=False)
        self.assertEqual(legacy.video_format, VideoFormat.HIGHLIGHT)
        self.assertFalse(legacy.enable_closeup_verify)

    def test_schema_compatibility_and_duration_validation(self):
        from google.genai import _transformers
        for schema in (Discovery, ExplanationPlan, ExplanationReview):
            types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema)
            for vertex in (True, False):
                # Exercise the same schema conversion used immediately before an HTTP request.
                self.assertIsNotNone(_transformers.t_schema(SimpleNamespace(vertexai=vertex), schema))
        self.assertEqual(output_duration_range("30s-55s"), (30, 55))
        self.assertNotIn("maxItems", json.dumps(provider_schema(ExplanationPlan.model_json_schema())))
        for invalid in ("55s-30s", "a minute", "0s-90s", "20s-120s"):
            with self.assertRaises(ValueError):
                output_duration_range(invalid)

    def test_quiet_context_and_cross_window_outcome_form_one_explanation(self):
        plan, watch, request = self._run()
        clip = plan.clips[0]
        self.assertEqual([call.args[1] for call in watch.call_args_list[:3]], [[(0, 600)], [(540, 600)], [(1080, 170)]])
        self.assertEqual([beat.start_time for beat in clip.beats], [5, 1110])
        self.assertEqual(clip.duration, 30)
        self.assertEqual(clip.end_time, 1125)  # Source span differs from assembled duration.
        self.assertEqual(clip.hook_text, "A briefing and escape")
        self.assertEqual(clip.commentary_script, " ".join(beat.narration for beat in clip.beats))
        self.assertTrue(clip.verification_passed)
        self.assertIn("briefing", request.call_args.args[0][0])
        self.assertEqual(watch.call_args.args[2], 5.0)

    def test_rejection_never_becomes_a_fallback_even_with_high_score(self):
        review = self.review.model_copy(update={"approved": False, "quality_score": 99})
        with self.assertRaisesRegex(ValueError, "No complete explanation"):
            self._run(review=review)

    def test_successful_scan_checkpoints_survive_downstream_rejection(self):
        with self.assertRaisesRegex(ValueError, "No complete explanation"):
            self._run(review=self.review.model_copy(update={"approved": False}))
        plan, watch, _ = self._run(keep_cache=True)
        self.assertEqual(len(plan.clips), 1)
        self.assertEqual(watch.call_count, 1)  # Only close-up review; no repeated source scanning.

    def test_missing_scene_review_cannot_pass(self):
        review = self.review.model_copy(update={"scenes": self.review.scenes[:1]})
        with self.assertRaisesRegex(ValueError, "No complete explanation"):
            self._run(review=review)

    def test_scene_cannot_move_beyond_observed_evidence(self):
        story = self.story.model_copy(deep=True)
        story.scenes[-1].start_time += 20
        with self.assertRaisesRegex(ValueError, "No complete explanation"):
            self._run(story=story)

    def test_unknown_outcome_requires_acknowledgement(self):
        story = self.story.model_copy(update={"uncertainty": "The final escape is not shown."})
        with self.assertRaisesRegex(ValueError, "No complete explanation"):
            self._run(story=story)
        review = self.review.model_copy(update={"uncertainty_acknowledged": True})
        plan, _, _ = self._run(story=story, review=review)
        self.assertIn("not shown", plan.clips[0].hook_summary)

    def test_unfinished_mission_can_have_a_verified_complete_topic_explanation(self):
        story = self.story.model_copy(update={"explanation_complete": False, "uncertainty": "The later rescue is not shown."})
        review = self.review.model_copy(update={"uncertainty_acknowledged": True})
        plan, _, _ = self._run(story=story, review=review)
        self.assertTrue(plan.clips[0].verification_passed)
        self.assertIn("later rescue", plan.clips[0].hook_summary)

    def test_overlong_evidence_is_trimmed_by_reviewer_into_requested_duration(self):
        observations = [Observation(topic="A decision", role=role, start_time=start, end_time=start + 20, description="Supporting source evidence.")
                        for role, start in (("context", 5), ("development", 35), ("conclusion", 65))]
        scenes = [ExplainerScene(evidence_id=f"event_{idx + 1}", role=obs.role, label=obs.role,
                                start_time=obs.start_time, duration=20, narration="Source-supported commentary.")
                  for idx, obs in enumerate(observations)]
        story = Explanation(topic="A decision", synopsis="Its cause and outcome.", explanation_complete=True, scenes=scenes)
        review = self.review.model_copy(update={"scenes": [
            SceneReview(scene_index=idx, approved=True, trim_start_offset=2, trim_end_offset=16,
                        narration="A concise supported explanation of this scene.", observation="Verified source evidence.")
            for idx in range(3)
        ]})
        with (
            patch("backend.services.explainer.ingest_service._get_video_metadata", return_value={"duration": 120}),
            patch.object(self.service, "_watch", side_effect=[Discovery(observations=observations), review]),
            patch.object(self.service, "_request", return_value=ExplanationPlan(stories=[story])),
        ):
            plan = self.service.analyze(self.source, "Decision", clip_count=1)
        self.assertEqual(plan.clips[0].duration, 42)
        self.assertEqual([beat.start_time for beat in plan.clips[0].beats], [7, 37, 67])

    def test_unavailable_analysis_does_not_produce_demo_stories(self):
        self.director._ensure_client.return_value = None
        with self.assertRaisesRegex(RuntimeError, "Configure Gemini"):
            self.service.analyze(self.source, "Mission")

    def test_api_failure_does_not_generate_demo_speech(self):
        director = GeminiDirectorService()
        with patch.object(director, "_ensure_client", return_value=None), patch.object(director, "_generate_fallback_audio") as fallback:
            with self.assertRaisesRegex(RuntimeError, "speech generation failed"):
                director.synthesize_voiceover("A complete explanation of this scene.", "test", "clip", require_speech=True)
        fallback.assert_not_called()

    def test_close_review_explicitly_requests_five_frames_per_second_from_provider(self):
        self.director._prepare_video_part.return_value = (types.Part.from_bytes(data=b"video", mime_type="video/mp4"), None, None)
        self.director._unique_models.return_value = ["test-model"]
        self.director._generate_content_with_retry.return_value = MagicMock(text=Discovery().model_dump_json())
        with patch("backend.services.explainer.ingest_service.create_micro_verification_clip"):
            self.service._watch(self.source, [(5, 10)], 5, "Review this scene.", Discovery)
        contents = self.director._generate_content_with_retry.call_args.args[2]
        self.assertEqual(contents[0].video_metadata.fps, 5)

    def test_narration_starts_on_each_scene_boundary_without_extra_footage(self):
        def synthesize(**kwargs):
            frequency = 440 if kwargs["clip_id"].endswith("1") else 880
            path = self.root / f"{frequency}.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"".join(struct.pack("<h", int(5000 * math.sin(2 * math.pi * frequency * idx / 24000))) for idx in range(72000)))
            return path
        self.director.synthesize_voiceover.side_effect = synthesize
        clip = {"clip_id": "clip_1", "commentary_script": "First scene. Second scene.", "beats": [
            {"label": "Context", "duration": 4, "narration": "First scene."},
            {"label": "Conclusion", "duration": 4, "narration": "Second scene."},
        ]}
        with patch("backend.services.explainer.ASSETS_DIR", self.root):
            output = self.service.synthesize_narration(clip, "test")
        import numpy as np
        with wave.open(str(output), "rb") as audio:
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 8, places=2)
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16)
        for offset, expected in ((0.5, 440), (4.5, 880)):
            snippet = samples[int(offset * 24000):int((offset + 0.5) * 24000)]
            frequency = np.argmax(abs(np.fft.rfft(snippet))) * 24000 / len(snippet)
            self.assertAlmostEqual(frequency, expected, delta=5)
        # Three seconds of speech should finish before 2.9s at the gently brisk
        # pace, retaining its pitch. Scene fitting must not stretch it to fill 4s.
        for offset in (2.9, 6.9):
            tail = samples[int(offset * 24000):int((offset + 0.1) * 24000)]
            self.assertLess(np.max(np.abs(tail)), 10)
        self.assertTrue(all(call.kwargs["require_speech"] for call in self.director.synthesize_voiceover.call_args_list))

    def test_spoken_duration_feedback_shortens_narration_without_extending_scene(self):
        def synthesize(**kwargs):
            duration = 8 if len(kwargs['script'].split()) > 4 else 2
            path = self.root / f"voice_{duration}.wav"
            with wave.open(str(path), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\x00\x00' * (24000 * duration))
            return path
        self.director.synthesize_voiceover.side_effect = synthesize
        clip = {'clip_id': 'clip_1', 'commentary_script': 'Michael checks the CCTV footage for evidence.', 'beats': [
            {'label': 'CCTV clue', 'duration': 4, 'start_time': 118.5, 'narration': 'Michael checks the CCTV footage for evidence.', 'description': 'He examines the tablet.'},
        ]}
        with patch('backend.services.explainer.ASSETS_DIR', self.root), patch.object(self.service, '_request', return_value=NarrationRewrite(narration='Michael checks CCTV.')):
            output = self.service.synthesize_narration(clip, 'test')
        self.assertEqual(clip['commentary_script'], 'Michael checks CCTV.')
        self.assertEqual(clip['beats'][0]['duration'], 4)
        self.assertEqual(clip['beats'][0]['start_time'], 118.5)
        self.assertEqual(self.director.synthesize_voiceover.call_count, 2)
        with wave.open(str(output), 'rb') as audio:
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 4, places=2)

    def test_pipeline_routes_explainer_with_absolute_source_timestamps(self):
        plan, _, _ = self._run()
        req = CreateJobRequest(url_or_path=str(self.source), video_format="explainer", mode="manual_studio", cut_start_time="00:02:00")
        job = {"request": req.model_dump(), "clips": []}
        with (
            patch.dict(app_main.JOBS_DB, {"explainer_test": job}),
            patch.object(app_main, "save_jobs_db"),
            patch.object(app_main.manager, "broadcast", new_callable=AsyncMock),
            patch.object(app_main.ingest_service, "download_or_link_video", return_value={"raw_path": str(self.source), "duration": 1250, "title": "Mission"}),
            patch.object(app_main.ingest_service, "cut_video_segment") as legacy_cut,
            patch.object(app_main.ExplainerService, "analyze", return_value=plan) as analyze,
            patch.object(app_main.ExplainerService, "synthesize_narration", return_value=self.root / "voice.wav") as narration,
        ):
            asyncio.run(app_main.execute_job_pipeline("explainer_test"))
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["metadata"]["cut_start_sec"], 0)
        self.assertFalse(job["metadata"]["has_more_segments"])
        self.assertEqual(analyze.call_args.kwargs["scan_start"], 120)
        legacy_cut.assert_not_called()
        narration.assert_called_once()

    def test_verified_narration_cannot_be_silently_desynchronized_by_patch(self):
        clip = {"clip_id": "clip_1", "video_format": "explainer", "commentary_script": "Verified narration."}
        with patch.dict(app_main.JOBS_DB, {"explainer_patch_test": {"clips": [clip]}}), patch.object(app_main, "save_jobs_db"):
            client = TestClient(app_main.app)
            result = client.patch("/api/jobs/explainer_patch_test/clips/clip_1", json={"commentary_script": "Unrelated text."})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(clip["commentary_script"], "Verified narration.")


if __name__ == "__main__":
    unittest.main()
