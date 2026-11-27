import unittest
from unittest.mock import Mock, patch

from backend.services import story_scan


class StoryTimelineTests(unittest.TestCase):
    def test_last_window_covers_tail_and_preserves_uncertain_speaker(self):
        service = Mock()
        service._watch.return_value = story_scan.Section(
            speech=[story_scan.Utterance(start=168, end=170, speaker="unknown", text="Made it!")],
            visuals=[],
        )
        result = story_scan.read_section(service, "original", 1, 320)
        self.assertEqual(service._watch.call_args.args[1], [(150, 170)])
        self.assertEqual(
            result["speech"], [{"start": 318, "end": 320, "speaker": "unknown", "text": "Made it!"}]
        )

    def test_resumed_scan_keeps_silent_visual_evidence_in_source_order(self):
        checkpoint = {
            "0": {"speech": [], "visuals": [{"start": 5, "end": 12, "evidence": "An objective appears."}]}
        }
        media = {"windows": 2, "duration": 310, "timeline_sections": checkpoint}
        later = {"speech": [], "visuals": [{"start": 301, "end": 309, "evidence": "Objective complete."}]}
        save = Mock()
        with patch.object(story_scan, "read_section", return_value=later) as read:
            sections = story_scan.collect(None, "source", media, save, lambda _: None)
        read.assert_called_once_with(None, "source", 1, 310)
        save.assert_called_once_with(1, later)
        self.assertEqual([e["start"] for e in story_scan.whole_timeline(sections)], [5, 301])

    def test_story_citations_resolve_to_actual_evidence_instead_of_a_guessed_time(self):
        events = [
            {"start": 10, "end": 14, "text": "Turn on the radio.", "speaker": "streamer"},
            {"start": 450, "end": 455, "text": "I went back for him.", "speaker": "game"},
        ]
        service = Mock()
        pitch = story_scan.StoryPitch(
            role="commentary",
            title="Why she returned",
            why="A promise",
            citations=[story_scan.Citation(near=10, excerpt="went back for him")],
        )
        service._request.return_value = story_scan.Pitches(proposals=[pitch], other_finds=[])
        result = story_scan.recommend(service, events)
        self.assertEqual(result.proposals[0].anchors, [1])
        pitch.citations[0].excerpt = "Words that were never said"
        with self.assertRaisesRegex(ValueError, "could not be matched"):
            story_scan.recommend(service, events)

    def test_unverified_out_of_window_scene_is_never_published(self):
        service = Mock()
        service._watch.return_value = story_scan.StoryReview(
            keep=True,
            title="Win",
            why="Result",
            scenes=[story_scan.CheckedScene(window=0, start=10, end=90, purpose="Win", original_line="")],
        )
        idea = story_scan.Proposal(title="The dragon races the clock", why="Result", role="highlight", anchors=[0])
        self.assertIsNone(story_scan.verify(service, "source", 30, [{"start": 12, "end": 15}], idea))
        self.assertNotIn(idea.title, service._watch.call_args.args[3])
