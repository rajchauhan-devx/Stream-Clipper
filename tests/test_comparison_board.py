import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.services import comparison_board as board


class ComparisonBoardTests(unittest.TestCase):
    def test_source_uses_only_the_selected_youtube_video(self):
        with patch.object(board.ingest_service, "download_or_link_video", return_value={"raw_path": "scan_a.mp4"}) as ingest, \
             patch.object(board, "describe_asset", return_value={"asset": "scan_a.mp4"}):
            result = board.open_source(board.SourceRequest(url="https://www.youtube.com/watch?v=ys_3h2nuNCY&list=PLabc"))
            self.assertEqual(result["asset"], "scan_a.mp4")
            self.assertEqual(ingest.call_args.args[0], "https://youtu.be/ys_3h2nuNCY")
            with self.assertRaises(HTTPException):
                board.open_source(board.SourceRequest(url="https://www.youtube.com/playlist?list=PLabc"))

    def test_scan_covers_the_tail_and_overlaps_section_boundaries(self):
        for duration in [5, 150, 170, 170.01, 300, 2981.5]:
            starts = [i * board.WINDOW for i in range(board.window_count(duration))]
            self.assertEqual(starts[0], 0)
            self.assertGreaterEqual(starts[-1] + board.WINDOW + board.OVERLAP, duration)
            self.assertLess(starts[-1], duration)
        self.assertFalse(board.bounded_cut(8, 14, 13))
        self.assertFalse(board.bounded_cut(8, 12, 40))

    def test_timestamped_moments_use_absolute_source_seconds(self):
        findings = board.Findings(moments=[
            board.Moment(start=7.5, end=18, question="What happens on impact?", observation="The car stops.", record="Drive into the same object."),
            board.Moment(start=0, end=3, question="Brief impact", observation="", record="Record it."),
        ])
        with tempfile.TemporaryDirectory() as tmp, patch.object(board.config, "TEMP_DIR", Path(tmp)), \
             patch.object(board, "asset_path", return_value=Path("source")), \
             patch.object(board, "media_info", return_value=(185, "h264")), \
             patch.object(board.ingest_service, "create_micro_verification_clip"), patch.object(board, "analyze", return_value=findings), patch.object(board,"review_cuts",side_effect=lambda s,p,cuts:cuts) as checked:
            topics = board.scan_window(board.WindowRequest(asset="scan_a.mp4", window=1))["topics"]
            self.assertEqual(checked.call_count,1)
            self.assertEqual([(t["start"], t["end"]) for t in topics], [(157.5, 168), (150, 160)])

    def test_a_confident_candidate_still_requires_independent_evidence(self):
        payload = board.MatchRequest(topic="How does a seaplane take off?", gta6={"asset": "scan_a.mp4", "start": 0, "end": 11}, recording="rec_b.mp4")
        candidate = board.Match(start=0, end=14, confidence=100, reason="Both show a plane.")
        rejected = board.Review(same_action=False, reason="It enters the water already airborne.", hook="", older_game="", gta6="")
        with tempfile.TemporaryDirectory() as tmp, patch.object(board.config, "TEMP_DIR", Path(tmp)), \
             patch.object(board, "asset_path", return_value=Path("source")), patch.object(board, "media_info", return_value=(30, "h264")), \
             patch.object(board.ingest_service, "create_micro_verification_clip"), patch.object(board, "reviewed_clip"), \
             patch.object(board, "analyze", return_value=candidate), patch.object(board, "observe") as observations, \
             patch.object(board, "review_actions", return_value=rejected):
            self.assertIsNone(board.match_recording(payload)["match"])
            self.assertEqual(observations.call_count, 2)
            render = board.BoardRenderRequest(**payload.model_dump(), older={"asset": "rec_b.mp4", "start": 0, "end": 14})
            with self.assertRaises(HTTPException) as error:
                board.prepare_render(render)
            self.assertEqual(error.exception.status_code, 422)
