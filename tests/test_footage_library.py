import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
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
        with library.db() as conn:
            if library.advance_section(conn, source, index, ""):
                library.store_verified_cuts(conn, source, library.prepare_cuts(cuts, index, 320))

    def test_scan_starts_before_preview_is_ready(self):
        key = "ccccccccccc"
        asset = f"scan_{key}.mp4"
        (config.DOWNLOADS_DIR / asset).touch()
        scan_started = Event()

        def source_status():
            return next(source for source in library.catalogue()["sources"] if source["id"] == key)

        def load_source(video_id, progress_callback, *, build_preview):
            self.assertEqual(video_id, key)
            self.assertFalse(build_preview)
            progress_callback(15, "Downloading source")
            self.assertEqual(source_status()["status_message"], "Downloading source")
            return dict(asset=asset, title="Gameplay", preview_url=None, duration=80, windows=1)

        def prepare_preview(_source):
            self.assertTrue(scan_started.wait(timeout=5))
            return "/browser-preview.mp4"

        def watch(*args):
            status = source_status()
            self.assertIsNone(status["preview_url"])
            self.assertEqual(status["status_message"], "Scanning section 1 of 1…")
            scan_started.set()
            return library.Scan(findings=[], ongoing_story="")

        with (
            patch.object(library, "Thread"),
            patch.object(library.board, "load_source", side_effect=load_source),
            patch.object(library.board, "prepare_browser_preview", side_effect=prepare_preview),
            patch.object(library.ExplainerService, "_watch", side_effect=watch),
        ):
            library.start_scan(library.board.SourceRequest(url=f"https://youtu.be/{key}?si=abc"))
            library.scan_source(key, library.active[key])

        status = source_status()
        self.assertEqual(status["cursor"], 1)
        self.assertEqual(status["preview_url"], "/browser-preview.mp4")
        self.assertEqual(status["clip_choices"], [])
        self.assertFalse(status["active"])
        self.assertEqual(status["error"], "")

    def test_reset_blocks_stale_scan_from_writing_into_recreated_source(self):
        request = library.board.SourceRequest(url=f"https://youtu.be/{self.first}")

        def watch(*args):
            with library.resetting_catalogue():
                pass
            library.start_scan(request)
            return library.Scan(findings=[], ongoing_story="")

        with patch.dict(library.active, clear=True), patch.object(library, "Thread"), patch.object(
            library.ExplainerService, "_watch", side_effect=watch
        ):
            library.start_scan(request)
            old_run = library.active[self.first]
            library.scan_source(self.first, old_run)
            source, = library.catalogue()["sources"]
            self.assertIsNot(library.active[self.first], old_run)
            self.assertEqual(source["cursor"], 0)
            self.assertEqual(source["status_message"], "Starting the scan…")
            self.assertEqual(source["error"], "")

    def test_cached_preview_is_used_for_scouting_and_review_uses_original(self):
        original = config.DOWNLOADS_DIR / f"scan_{self.first}.mp4"
        with patch.object(config, "PROXIES_DIR", config.DOWNLOADS_DIR):
            preview = library.board.browser_preview_path(original)
            preview.touch()
            result = library.Scan(findings=[library.ScoutedFinding(role="highlight", title="Splash",
                reason="The landing throws a wave over the dock.", tags=[], record="", start=12, end=21)],
                ongoing_story="")
            with patch.object(library.ExplainerService, "_watch", return_value=result) as watch, patch.object(
                library, "review_cuts", return_value=[]
            ) as verify, patch.object(library.ExplainerService, "_request", return_value=library.ClipChoices(
                ranked=[library.ClipChoice(candidate=0, why="Visible splash")])):
                library.scan_source(self.first, library.ScanRun())

        self.assertEqual([call.args[0] for call in watch.call_args_list], [preview, preview])
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[1], original)
        self.assertEqual(len(verify.call_args.args[2]), 1)

    def test_moment_without_source_media_returns_a_recovery_message(self):
        self.save(self.first, 0, [("commentary", "Prison visit", 0, 35)])
        moment, = library.catalogue()["moments"]
        with library.db() as conn:
            conn.execute("UPDATE sources SET media='{}' WHERE id=?", (self.first,))

        with self.assertRaises(HTTPException) as error:
            library.selected([moment["id"]])
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("Scan the original link again", error.exception.detail)

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
        with library.db() as conn:
            conn.execute("UPDATE sources SET media=json_set(media,'$.selection_version',?) WHERE id=?",
                         (library.SELECTION_VERSION, self.first))
        with patch.object(library, "Thread") as thread:
            request = library.board.SourceRequest(url=f"https://www.youtube.com/watch?v={self.first}&t=4")
            self.assertEqual(library.start_scan(request), {"id": self.first})
            thread.assert_not_called()

    def test_updated_scan_publishes_only_whole_video_picks_and_reuses_the_previous_id(self):
        self.save(self.first, 0, [("commentary", "Generic introduction", 0, 15),
                                  ("highlight", "Dog drives a truck", 20, 31)])
        self.save(self.first, 1, [])
        old = {m["title"]: m["id"] for m in library.catalogue()["moments"]}
        request = library.board.SourceRequest(url=f"https://youtu.be/{self.first}")
        with patch.dict(library.active, clear=True), patch.object(library, "Thread") as thread:
            library.start_scan(request)
            self.assertEqual(library.catalogue()["moments"], [])
            self.save(self.first, 0, [("highlight", "Dog drives the truck", 20, 31),
                                      ("commentary", "Dog behind the wheel", 21, 31),
                                      ("highlight", "Routine jump", 40, 50)])
            library.review_saved_clips(self.first, Mock())
            self.assertEqual(library.catalogue()["moments"], [])
            self.save(self.first, 1, [])
            answers = library.ClipChoices(ranked=[library.ClipChoice(candidate=i, why="Dog at the wheel")
                                                  for i in (0, 1)])
            verdict = library.PlaybackVerdict(keep=True, title="Dog drives the truck", setup="A truck pulls up.",
                                              payoff="The dog is at the wheel.", payoff_second=5)
            checked = Mock(_request=Mock(return_value=answers), _watch=Mock(return_value=verdict))
            library.review_saved_clips(self.first, checked)
            self.assertEqual(checked._watch.call_args.args[1], [(20, 11)])
            self.assertNotIn("Dog drives", checked._watch.call_args.args[3])
            kept, = library.catalogue()["moments"]
            self.assertEqual(kept["id"], old["Dog drives a truck"])
            self.assertEqual(kept["title"], "Dog drives the truck")
            library.active.pop(self.first)
            library.start_scan(request)
            self.assertEqual(thread.call_count, 1)
            self.assertEqual(library.selected([old["Generic introduction"]])[0]["title"], "Generic introduction")

    def test_final_playback_rejects_payoff_outside_saved_cut(self):
        candidate = dict(id="a", start=1105, end=1115, role="highlight")
        verdict = library.PlaybackVerdict(keep=True, title="The aftermath", setup="He approaches.",
                                          payoff="The aftermath is visible.", payoff_second=14)
        service = Mock(_watch=Mock(return_value=verdict))
        self.assertEqual(library.check_playback(service, Path("raw"), [candidate], [candidate]), [])

    def test_shortlist_survives_review_failure_and_can_publish_zero_clips(self):
        cut = library.Finding(role="highlight", title="A surprising landing", reason="Proposed payoff",
                              start=10, end=20, tags=[], record="")
        with library.db() as conn:
            conn.execute("UPDATE sources SET media=json_set(media,'$.candidate_ids',json('[]'),'$.visible_ids',json('[]')) WHERE id=?",
                         (self.first,))
        library.stage_section(self.first, 0, [cut], "", None)
        library.stage_section(self.first, 0, [cut], "", None)
        service = Mock()
        service._request.return_value = library.ClipChoices(ranked=[library.ClipChoice(candidate=0, why="Check the landing")])
        library.review_saved_clips(self.first, service)
        service._request.assert_not_called()
        library.stage_section(self.first, 1, [], "", None)
        with patch.object(library, "review_cuts", side_effect=[RuntimeError("Interrupted"), [None]]) as check:
            with self.assertRaisesRegex(RuntimeError, "Interrupted"):
                library.review_saved_clips(self.first, service)
            self.assertEqual(library.catalogue()["moments"], [])
            library.review_saved_clips(self.first, service)
            self.assertEqual(len(check.call_args.args[2]), 1)
        index = library.catalogue()
        source = next(s for s in index["sources"] if s["id"] == self.first)
        self.assertEqual(source["clip_choices"], [])
        self.assertEqual(index["moments"], [])

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

    def test_partial_finds_cannot_be_ranked_or_start_a_whole_story(self):
        self.save(self.first, 0, [("commentary", "Opening scene", 5, 45)])
        with library.db() as conn:
            conn.execute("UPDATE sources SET media=json_set(media,'$.clip_choices',json('[]')) WHERE id=?", (self.first,))
        with patch.object(main, "queue_job") as queue:
            service = Mock()
            library.review_saved_clips(self.first, service)
            partial = next(s for s in library.catalogue()["sources"] if s["id"] == self.first)
            self.assertFalse(partial["scan_complete"])
            self.assertNotIn("clip_choices", partial)
            service._request.assert_not_called()
            with self.assertRaises(HTTPException) as pending:
                asyncio.run(main.build_source_story(self.first))
            self.assertEqual(pending.exception.status_code, 409)
            queue.assert_not_called()

            self.save(self.first, 1, [])
            complete = next(s for s in library.catalogue()["sources"] if s["id"] == self.first)
            self.assertTrue(complete["scan_complete"])
            self.assertNotIn("clip_choices", complete)
            asyncio.run(main.build_source_story(self.first))
            request, media = queue.call_args.args
            self.assertEqual(request.video_format, "explainer")
            self.assertEqual(request.cut_start_time, "00:00:00")
            self.assertEqual(Path(media["raw_path"]).name, f"scan_{self.first}.mp4")

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
            library.scan_source(self.first, library.ScanRun())
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

    def test_lineup_retries_invalid_scene_boundaries_before_creating_draft(self):
        self.save(self.first, 0, [("commentary", "Story", 5, 40)])
        key = library.catalogue()["moments"][0]["id"]
        good = self.verified()
        too_long = good.model_copy(update={"scenes": [good.scenes[0].model_copy(update={"end": 35})]})
        with patch.object(library.ExplainerService, "_watch", side_effect=[too_long, good]) as watch:
            draft = library.make_job(library.Lineup(kind="commentary", ids=[key]))

        self.assertEqual(watch.call_count, 2)
        self.assertIn("previous scene list could not be used", watch.call_args.args[3])
        self.assertEqual(draft["clips"][0]["beats"][0]["duration"], 4)

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
