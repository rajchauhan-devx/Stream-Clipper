import subprocess
import unittest

from backend.services.comparison import ComparisonTimeline
from backend.services.comparison_motion import spoken_logo_frames


class ComparisonTimelineTests(unittest.TestCase):
    def test_logo_cues_follow_the_spoken_names_and_ignore_later_mentions(self):
        words = [
            {"word": "GTA", "start": 1.72},
            {"word": "Five", "start": 2.02},
            {"word": "versus", "start": 2.30},
            {"word": "GTA6?", "start": 2.67},
            {"word": "GTA", "start": 4.25},
            {"word": "IV", "start": 4.55},
        ]
        self.assertEqual(spoken_logo_frames(words, "gta5", 210), (103, 160))
        self.assertEqual(spoken_logo_frames(words, "gta4", 210), (None, 160))
        self.assertEqual(spoken_logo_frames(words, "gta4", 300), (255, 160))

    def test_panels_freeze_and_resume_at_the_spoken_phase_boundaries(self):
        plan = ComparisonTimeline(hook=12, older_game=18, gta6=21)
        result = subprocess.run([
            "ffmpeg", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=60:duration=1",
            "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=60:duration=1",
            "-filter_complex", ";".join(plan.video_filters()), "-map", "[older_playback]",
            "-map", "[six_playback]", "-c:v", "rawvideo", "-f", "framemd5", "-",
        ], check=True, capture_output=True, text=True)
        checksums = ([], [])
        for line in result.stdout.splitlines():
            if not line.startswith("#"):
                fields = line.split(",")
                checksums[int(fields[0])].append(fields[-1].strip())
        older, six = checksums
        self.assertEqual((len(older), len(six)), (51, 51))
        self.assertNotEqual(older[0], older[11])
        self.assertNotEqual(six[0], six[11])
        self.assertNotEqual(older[11], older[29])
        self.assertEqual(set(six[11:30]), {six[11]})
        self.assertEqual(set(older[29:]), {older[29]})
        self.assertNotEqual(six[29], six[-1])
        # Matching synthetic inputs make it possible to check that the new panel
        # resumes from its paused source position rather than skipping ahead.
        self.assertEqual(six[30:48], older[12:30])
