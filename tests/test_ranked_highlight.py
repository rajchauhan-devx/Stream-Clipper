import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from backend import main
from backend.schemas import CreateJobRequest
from backend.services import ranked_highlight as ranked


class RankedHighlightTests(unittest.TestCase):
    def test_rank_labels_accumulate_without_revealing_the_winner_early(self):
        beats = [{"rank": r, "label": f"Moment {r}"} for r in ranked.reveal_order(5)]
        with tempfile.TemporaryDirectory() as tmp:
            for index in (0, 1, 4):
                output = Path(tmp) / "board.png"
                ranked.artwork(beats, index, "GTA 5", output)
                with Image.open(output) as image:
                    alpha = image.getchannel("A")
                    for rank in range(1, 6):
                        y = 710 + (rank-1)*190
                        filled = alpha.crop((150, y-45, 680, y+45)).getbbox() is not None
                        self.assertEqual(filled, rank in [b["rank"] for b in beats[:index+1]])
        self.assertEqual(ranked.reveal_order(4)[-1], 1)

    def test_scanner_does_not_pad_a_short_source_with_duplicate_moments(self):
        def pick(a,b,label,score):
            return ranked.Moment(start=a,end=b,score=score,label=label,setup="Watch this",payoff="Misses the landing",
                                 wide=True,focus_x=0.5,radio_music=False)
        moments = [pick(1,9,"Crash",95),pick(2,8,"Same crash",90),pick(12,20,"Fall",85)]
        with patch.object(ranked.ingest_service, "create_micro_verification_clip"), patch.object(ranked,"_watch",return_value=moments), patch.object(ranked,"verify_moment",side_effect=lambda d,s,o,n,m,g:m) as review:
            plan = ranked.analyze(None, Path("source.mp4"), "GTA V", 120, 30, 3, "60s-95s", False, lambda *_: None)
        self.assertEqual(review.call_count,2)
        self.assertEqual(len(plan.clips),1)
        clip = plan.clips[0]
        self.assertEqual([b.rank for b in clip.beats],[2,1])
        self.assertEqual([b.start_time for b in clip.beats],[12,1])
        self.assertEqual(clip.commentary_script,"")
        self.assertEqual(clip.hook_text,"Ranking Funniest GTA 5 Moments")

    def test_launchpad_creates_one_ranked_output_without_tts(self):
        request = CreateJobRequest(url_or_path="game.mp4", video_format="highlight", mode="manual_studio",
                                   clip_count=1, enable_closeup_verify=False)
        job = {"request": request.model_dump(), "clips": []}
        picks = [ranked.Moment(start=i, end=i+4, score=90, label=f"Moment {i}", setup="Watch",
                               payoff="A collision", wide=True, focus_x=.5, radio_music=False) for i in (2, 12, 22)]
        with (patch.dict(main.JOBS_DB, {"rank_test": job}), patch.object(main, "save_jobs_db"),
              patch.object(main.manager, "broadcast", new_callable=AsyncMock),
              patch.object(main.ingest_service, "download_or_link_video", return_value={"raw_path":"game.mp4","duration":100,"title":"GTA 5"}),
              patch.object(main.ingest_service, "cut_video_segment", return_value={"cut_path":"cut.mp4","start_sec":30,"duration_sec":40}),
              patch.object(ranked.ingest_service,"create_micro_verification_clip") as scan, patch.object(ranked,"_watch",return_value=picks),
              patch.object(ranked,"verify_moment",side_effect=lambda d,s,o,n,m,g:m) as review,
              patch.object(main.gemini_director,"synthesize_voiceover") as tts):
            asyncio.run(main.execute_job_pipeline("rank_test"))
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["clips"]), 1)
        self.assertEqual(scan.call_args.args[1], 30)
        self.assertEqual([b["rank"] for b in job["clips"][0]["beats"]], [3,2,1])
        self.assertEqual(review.call_count,3)
        tts.assert_not_called()
