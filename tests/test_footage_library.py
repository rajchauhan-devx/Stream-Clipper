import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from backend import config, main
from backend.services import footage_library as library
from backend.services.explainer import provider_schema


class FootageLibraryTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(config, "WORKSPACE_DIR", root))
        self.enterContext(patch.object(config, "DOWNLOADS_DIR", root))
        for source in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
            asset = f"scan_{source}.mp4"
            (root / asset).touch()
            media = dict(
                asset=asset,
                title=source,
                preview_url="/preview",
                duration=320,
                windows=2,
                extraction_review=1,
            )
            with library.db() as conn:
                conn.execute(
                    "INSERT INTO sources(id, title, media) VALUES(?, ?, ?)",
                    (source, source, json.dumps(media)),
                )
        self.first, self.second = "aaaaaaaaaaa", "bbbbbbbbbbb"

    def save(self, source, index, findings):
        cuts = [
            library.Finding(
                role=role,
                title=title,
                start=start,
                end=end,
                reason="Visible landing",
                tags=["seaplane"],
                record="Land on water" if role == "comparison" else "",
            )
            for role, title, start, end in findings
        ]
        library.save_section(source, index, library.prepare_cuts(cuts, index, 320), "")

    def test_resume_empty_windows_and_multiple_independent_roles(self):
        self.save(
            self.first,
            0,
            [("highlight", "Splash", 158, 160), ("comparison", "How does it land?", 155, 165)],
        )
        self.save(self.first, 0, [("support", "Already inspected", 8, 16)])
        self.save(
            self.first, 1, [("highlight", "Splash", 158, 160), ("commentary", "Complete flight", 51, 215)]
        )
        self.save(self.second, 0, [])
        result = library.catalogue()
        self.assertCountEqual(
            [m["role"] for m in result["moments"]], ["highlight", "comparison", "commentary"]
        )
        sources = {s["id"]: s for s in result["sources"]}
        self.assertEqual(sources[self.first]["coverage"], 320)
        self.assertEqual(sources[self.second]["coverage"], 170)
        library.review_saved_clips(
            self.first, Mock(_request=Mock(return_value=library.ClipChoices(ranked=[])))
        )
        with patch.object(library, "Thread") as thread:
            request = library.board.SourceRequest(url=f"https://www.youtube.com/watch?v={self.first}&t=4")
            self.assertEqual(library.start_scan(request), {"id": self.first})
            thread.assert_not_called()

    def test_one_strong_cut_can_lead_other_roles_are_saved_and_cache_reopens(self):
        self.save(
            self.first,
            0,
            [
                ("commentary", "Escape", 0, 60),
                ("comparison", "Repeat chase", 1, 20),
                ("comparison", "Test crash", 30, 40),
                ("highlight", "Spin", 55, 66),
                ("support", "Wheel detail", 42, 46),
            ],
        )
        self.save(self.first, 1, [])
        self.save(self.second, 0, [("highlight", "Different source", 5, 20)])
        service = Mock()
        service._request.return_value = library.ClipChoices(
            ranked=[
                library.ClipChoice(candidate=0, why="The chase has a setup and a visible escape."),
                library.ClipChoice(candidate=99, why="Unknown cut"),
                library.ClipChoice(candidate=0, why="Duplicate"),
                library.ClipChoice(candidate=3, why="The spin has a clear payoff."),
            ]
        )
        library.review_saved_clips(self.first, service)
        library.review_saved_clips(self.first, service)
        service._request.assert_called_once()
        index = library.catalogue()
        result = next(s for s in index["sources"] if s["id"] == self.first)["clip_choices"]
        self.assertEqual([p["role"] for p in result], ["commentary", "highlight"])
        self.assertEqual(len(index["moments"]), 6)
        by_id = {m["id"]: m for m in index["moments"]}
        self.assertEqual(by_id[result[0]["id"]]["title"], "Escape")
        self.assertEqual(by_id[result[1]["id"]]["title"], "Spin")
        library.edit(result[0]["id"], library.Edit(dismissed=True))
        self.assertNotIn(
            "clip_choices", next(s for s in library.catalogue()["sources"] if s["id"] == self.first)
        )

    def test_only_supporting_footage_is_saved_without_promoting_it(self):
        self.save(self.first, 0, [("support", "Water detail", 2, 9)])
        self.save(self.first, 1, [])
        service = Mock()
        library.review_saved_clips(self.first, service)
        service._request.assert_not_called()
        index = library.catalogue()
        self.assertEqual(next(s for s in index["sources"] if s["id"] == self.first)["clip_choices"], [])
        self.assertEqual(index["moments"][0]["role"], "support")

    def test_completed_legacy_scan_reviews_saved_observations_without_rescanning(self):
        self.save(self.first, 0, [("comparison", "How does it land?", 10, 20)])
        self.save(self.first, 1, [])
        choice = library.ClipChoices(
            ranked=[library.ClipChoice(candidate=0, why="The landing can be recreated.")]
        )
        with library.db() as conn:
            conn.execute(
                "UPDATE sources SET media=json_remove(media,'$.extraction_review') WHERE id=?",
                (self.first,),
            )
        with (
            patch.object(library.ExplainerService, "_request", return_value=choice),
            patch.object(library, "review_cuts", side_effect=lambda service, path, cuts: cuts) as cut_check,
            patch.object(library.ExplainerService, "_watch") as watch,
            patch.object(library.board, "open_source") as download,
        ):
            library.scan_source(self.first)
        cut_check.assert_called_once()
        watch.assert_not_called()
        download.assert_not_called()
        source = next(s for s in library.catalogue()["sources"] if s["id"] == self.first)
        self.assertFalse(source["error"])
        self.assertEqual(source["clip_choices"][0]["role"], "comparison")

    def test_schema_preserves_finding_title(self):
        schema = provider_schema(library.Finding.model_json_schema())
        self.assertTrue(set(schema["required"]).issubset(schema["properties"]))

    @staticmethod
    def verified():
        return library.Verified(
            editorial_score=85,
            fits=True,
            reason="Visible",
            scenes=[
                library.Scene(
                    start=0.5,
                    end=4.5,
                    label="Landing",
                    narration="Watch the landing.",
                    evidence="Water splash",
                )
            ],
            wide=True,
            focus_x=0.4,
            radio_music=False,
        )

    def test_reuse_source_offsets_order_and_history(self):
        self.save(self.first, 0, [("highlight", "A", 20, 34), ("commentary", "Story", 40, 66)])
        self.save(self.second, 0, [("highlight", "B", 75, 86), ("support", "Detail", 11, 20)])
        moments = {m["title"]: m for m in library.catalogue()["moments"]}
        ids = [moments[k]["id"] for k in ("A", "B")]
        self.assertEqual(library.selected(ids)[0]["title"], "A")
        with patch.object(library.ExplainerService, "_watch", return_value=self.verified()):
            job = library.make_job(library.Lineup(kind="highlight", ids=ids, title="Two landings"))
            story = library.make_job(library.Lineup(kind="commentary", ids=[moments["Story"]["id"]]))
            draft = library.with_support(
                story, story["clips"][0], library.Insert(moment_id=moments["Detail"]["id"], after=0)
            )
        beats = job["clips"][0]["beats"]
        self.assertEqual(
            [(b["rank"], b["start_time"], b["library_id"]) for b in beats],
            [(2, 75.5, ids[1]), (1, 20.5, ids[0])],
        )
        self.assertNotEqual(beats[0]["source_asset"], beats[1]["source_asset"])
        self.assertEqual(draft["clips"][0]["beats"][0]["library_id"], moments["Detail"]["id"])
        self.assertEqual(len(story["clips"][0]["beats"]), 1)
        with (
            patch.dict(main.JOBS_DB, {job["job_id"]: job}, clear=True),
            patch.object(main, "COMPARISONS_DB", []),
        ):
            self.assertFalse(any(m["uses"] for m in main.get_library()["moments"]))
            job["clips"][0].update(used_library_ids=ids, preview_url="/test.mp4")
            used = {m["id"] for m in main.get_library()["moments"] if m["uses"]}
            self.assertEqual(used, set(ids))

    def test_unsuitable_cut_and_dismissed_cut_cannot_create_draft(self):
        self.save(self.first, 0, [("commentary", "Story", 5, 35)])
        key = library.catalogue()["moments"][0]["id"]
        review = self.verified().model_copy(update={"fits": False, "reason": "No visible outcome"})
        with (
            patch.object(library.ExplainerService, "_watch", return_value=review),
            self.assertRaises(HTTPException) as exc,
        ):
            library.make_job(library.Lineup(kind="commentary", ids=[key]))
        self.assertIn("No visible outcome", exc.exception.detail)
        library.edit(key, library.Edit(dismissed=True))
        with self.assertRaises(HTTPException):
            library.selected([key])
        library.edit(key, library.Edit(dismissed=False, role="support"))
        with patch.object(library, "review_cuts", side_effect=lambda svc, path, cuts: cuts) as checked:
            self.assertEqual(library.selected([key])[0]["role"], "support")
            library.selected([key])
        checked.assert_called_once()

    def test_cached_note_only_winner_is_hidden_and_replaced_after_footage_review(self):
        self.save(self.first, 0, [("commentary", "Invented crash", 3, 16), ("highlight", "Splash", 30, 45)])
        self.save(self.first, 1, [])
        rows = {m["title"]: m for m in library.catalogue()["moments"]}
        old = [{"id": rows["Invented crash"]["id"], "role": "commentary", "why": "Scout's claim"}]
        with library.db() as conn:
            conn.execute(
                "UPDATE sources SET media=json_set(json_remove(media,'$.extraction_review'),'$.clip_choices',json(?)) WHERE id=?",
                (json.dumps(old), self.first),
            )
        self.assertNotIn(
            "clip_choices", next(s for s in library.catalogue()["sources"] if s["id"] == self.first)
        )
        service = Mock()
        service._request.return_value = library.ClipChoices(
            ranked=[library.ClipChoice(candidate=0, why="Visible splash")]
        )
        with patch.object(library, "review_cuts", side_effect=lambda svc, path, cuts: [None, cuts[1]]):
            library.review_saved_clips(self.first, service)
        cat = library.catalogue()
        source = next(s for s in cat["sources"] if s["id"] == self.first)
        self.assertEqual(source["clip_choices"][0]["id"], rows["Splash"]["id"])
        self.assertTrue(next(m for m in cat["moments"] if m["title"] == "Invented crash")["dismissed"])
