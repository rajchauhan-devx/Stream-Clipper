import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.services import (
    extraction_review as review,
)
from backend.services import (
    footage_library as library,
)
from backend.services import (
    ranked_highlight as ranked,
)


class ExtractionReviewTests(unittest.TestCase):
    def setUp(self):
        self.cut = review.Finding(
            role="comparison",
            title="Does the plane sink?",
            start=150,
            end=164,
            reason="It sinks after landing.",
            record="Land in water.",
            tags=[],
        )
        self.timeline = review.Timeline(
            events=[
                review.Event(start=2, end=5, observation="Approaches the waves."),
                review.Event(start=5, end=11.5, observation="Touches down and sinks."),
            ]
        )
        self.service = Mock()
        self.service._watch.return_value = self.timeline

    @staticmethod
    def decision(index, accepted=True, first=0, last=1):
        return review.Decision(
            index=index,
            fits=accepted,
            first_event=first,
            last_event=last,
            evidence="The landing and sinking are visible.",
        )

    def test_blind_viewing_shared_across_roles_and_trim_anchored_to_source(self):
        alternative = self.cut.model_copy(update={"role": "highlight", "title": "Shark attack"})
        self.service._request.return_value = review.Decisions(
            cuts=[self.decision(1, False), self.decision(0)]
        )
        kept, rejected = review.review_cuts(self.service, Path("raw.mp4"), [self.cut, alternative])
        self.assertIsNone(rejected)
        self.assertEqual((kept.start, kept.end), (152, 161.5))
        self.service._watch.assert_called_once()
        _, windows, fps, prompt, _ = self.service._watch.call_args.args
        self.assertEqual((windows, fps), ([(150, 14)], 5))
        self.assertNotIn(self.cut.title, prompt)
        self.assertNotIn(alternative.title, prompt)

    def test_missing_decisions_do_not_advance_scan_and_bad_anchors_do_not_pass(self):
        self.service._request.return_value = review.Decisions(cuts=[])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            review.review_cuts(self.service, Path("raw"), [self.cut])
        self.service._request.return_value = review.Decisions(cuts=[self.decision(0, last=10)])
        self.assertEqual(review.review_cuts(self.service, Path("raw"), [self.cut]), [None])
        self.service._watch.return_value = review.Timeline(events=[])
        self.service._request.reset_mock()
        self.assertEqual(review.review_cuts(self.service, Path("raw"), [self.cut]), [None])
        self.service._request.assert_not_called()

    def test_window_offsets_are_applied_once_and_only_stories_can_use_carry(self):
        def finding(role, prior):
            return library.ScoutedFinding(
                **{**self.cut.model_dump(), "role": role, "start": 3, "end": 16}, prior_story_start=prior
            )

        scan = library.Scan(
            findings=[finding("comparison", 20), finding("commentary", 20)], ongoing_story=""
        )
        cuts = list(library.source_coordinates(scan, 150, 30, "Earlier briefing starts at 20s."))
        self.assertEqual([(c.start, c.end) for c in cuts], [(153, 166), (20, 166)])
        cuts = list(library.source_coordinates(scan, 150, 30, ""))
        self.assertEqual(cuts[1].start, 153)

    def test_highlight_rejects_a_different_event_in_the_context_padding(self):
        moment = ranked.Moment(
            start=10,
            end=15,
            score=90,
            label="Splash",
            setup="Watch the water.",
            payoff="Hits the water.",
            wide=True,
            focus_x=0.5,
            radio_music=False,
        )
        other = self.cut.model_copy(update={"start": 121, "end": 129})
        with patch.object(ranked, "review_cuts", return_value=[other]) as checked:
            self.assertIsNone(ranked.verify_moment(None, Path("raw"), 120, 30, moment, 15))
        self.assertEqual(checked.call_args.args[2][0].role, "highlight")
