"""Offline tests for the Level 1 scorecard. Runs are synthetic directories; nothing is planned or rendered."""

import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from capstone_script.__main__ import main
from capstone_script.scorecard import (
    HUMAN_CRITERIA, ScorecardError, build, markdown, read_ratings, run_checks, write_report, write_template,
)

REVIEW = {"clarity": 4, "flow": 4, "accuracy": 5, "engagement": 3, "audienceFit": 4}


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def make_run(root: Path, name: str, *, live=True, plan="completed", review="completed", narration="completed",
             seconds=434.5, expected=None, draft=False, motion=None, render=True, minimum=None) -> Path:
    run = root / name
    run.mkdir()
    write(run / "scene-plan.json", {"title": f"Title of {name}", "scenes": []})
    if live:
        spec = {"topic": f"Topic {name}", "audience": "Adults", "targetDurationSec": 420}
        if minimum is not None:
            spec["minimumDurationSec"] = minimum
        write(run / "project-spec.json", spec)
        write(run / "llm-response.json", {"status": plan, "estimatedCostUsd": 1.25, "attempts": [],
                                          **({"error": "Outline failed validation"} if plan != "completed" else {})})
        if plan != "completed":
            return run
        if review:
            write(run / "review.json", {"status": review, "estimatedCostUsd": 0.25,
                                        **({"scores": REVIEW} if review == "completed" else {"error": "timeout"})})
    if narration:
        write(run / "audio-manifest.json", {"status": narration})
        if narration != "completed":
            return run
    if render:
        info = {"probedSeconds": seconds, "expectedSeconds": seconds if expected is None else expected, "draft": draft}
        if motion:
            info["motionInspection"] = {"path": "motion-inspection.json", "status": motion}
        write(run / "video-info.json", info)
    return run


def write_ratings(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run", "rater", *HUMAN_CRITERIA, "notes"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def rating(run, rater, scores=(4, 4, 4, 4, 4), notes=""):
    return {"run": run, "rater": rater, **dict(zip(HUMAN_CRITERIA, scores)), "notes": notes}


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_live_run_passes_every_check(self):
        checks = run_checks(make_run(self.root, "good", motion="clean"))
        self.assertTrue(checks["automaticPass"])
        self.assertTrue(checks["live"])
        self.assertEqual(checks["stages"], {"plan": "passed", "review": "passed", "narration": "passed",
                                            "render": "passed"})
        self.assertEqual(checks["topic"], "Topic good")
        self.assertEqual(checks["costUsd"], 1.5)
        self.assertEqual(checks["reviewScores"], REVIEW)
        self.assertEqual(checks["motionInspection"], "clean")
        self.assertEqual(checks["failures"], [])

    def test_each_stage_failure_is_reported_with_its_reason(self):
        cases = {
            "plan": (dict(plan="failed"), "plan: Outline failed validation"),
            "review": (dict(review="failed"), "review: timeout"),
            "narration": (dict(narration="failed"), "narration: did not complete"),
            "render": (dict(render=False), "render: no output; the run stopped before this stage"),
            "draft": (dict(draft=True), "render: only a draft (960x540) was rendered"),
            "drift": (dict(seconds=434.5, expected=430.0), "render: MP4 lasts 434.50 s but the timeline is 430.00 s"),
            "short": (dict(seconds=390.0), "length: 390.0 s is under the 420 s minimum"),
        }
        for name, (options, reason) in cases.items():
            with self.subTest(name):
                checks = run_checks(make_run(self.root, name, **options))
                self.assertFalse(checks["automaticPass"])
                self.assertIn(reason, checks["failures"])

    def test_duration_repair_costs_include_all_reviews_without_double_counting(self):
        run = make_run(self.root, "extended")
        write(run / "duration-extension.json", {"initialReviewCostUsd": 0.25, "estimatedCostUsd": 0.8})
        self.assertEqual(run_checks(run)["costUsd"], 2.3)

    def test_old_duration_record_keeps_original_and_candidate_review_costs(self):
        run = make_run(self.root, "old-extended")
        (run / "attempt-01").mkdir()
        write(run / "attempt-01/review.json", {"estimatedCostUsd": 0.1})
        write(run / "duration-extension.json", {"estimatedCostUsd": 0.2,
                                                "rounds": [{"directory": "attempt-01"}]})
        self.assertEqual(run_checks(run)["costUsd"], 1.8)

    def test_animation_report_is_read_even_without_a_render(self):
        run = make_run(self.root, "stopped", render=False)
        write(run / "motion-inspection.json", {"status": "geometry-and-timing-checks-passed", "scenes": []})
        self.assertEqual(run_checks(run)["motionInspection"], "geometry-and-timing-checks-passed")

    def test_failed_spatial_preflight_is_reported_before_render_and_over_stale_success(self):
        for rendered in (False, True):
            with self.subTest(rendered=rendered):
                run = make_run(self.root, f"spatial-{rendered}", render=rendered)
                if rendered:
                    info = json.loads((run / "video-info.json").read_text())
                    info["spatialInspection"] = {"path": "spatial-inspection.json", "status": "spatial-checks-passed"}
                    write(run / "video-info.json", info)
                write(run / "spatial-inspection.json", {"status": "needs-review"})
                checks = run_checks(run)
                self.assertFalse(checks["automaticPass"])
                self.assertEqual(checks["spatialInspection"], "needs-review")
                self.assertIn("spatial: needs-review; contact or camera checks did not pass", checks["failures"])

    def test_spatial_status_in_video_metadata_is_respected_without_full_report(self):
        run = make_run(self.root, "spatial-metadata")
        info = json.loads((run / "video-info.json").read_text())
        info["spatialInspection"] = {"path": "spatial-inspection.json", "status": "needs-review"}
        write(run / "video-info.json", info)
        self.assertFalse(run_checks(run)["automaticPass"])
        write(run / "spatial-inspection.json", {})
        self.assertEqual(run_checks(run)["spatialInspection"], "unknown")
        self.assertFalse(run_checks(run)["automaticPass"])

    def test_passed_spatial_check_is_exported_without_changing_motion_warning_policy(self):
        run = make_run(self.root, "spatial-passed", motion="needs-review")
        write(run / "spatial-inspection.json", {"status": "spatial-checks-passed"})
        checks = run_checks(run)
        self.assertTrue(checks["automaticPass"])
        self.assertEqual(checks["motionInspection"], "needs-review")
        self.assertEqual(checks["spatialInspection"], "spatial-checks-passed")
        self.assertEqual(checks["failures"], [])
        out = write_report(build([run]), self.root / "spatial-scorecard")
        self.assertIn("Spatial check", (out / "scorecard.md").read_text())
        self.assertIn("spatial-checks-passed", (out / "scorecard.md").read_text())
        with (out / "scorecard.csv").open(newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["spatial_check"], "spatial-checks-passed")

    def test_review_is_optional_and_minimum_length_is_configurable(self):
        checks = run_checks(make_run(self.root, "unreviewed", review=None, seconds=300), min_seconds=240)
        self.assertEqual(checks["stages"]["review"], "not requested")
        self.assertTrue(checks["automaticPass"])
        self.assertIsNone(checks["reviewScores"])

    def test_each_run_is_held_to_the_minimum_it_was_generated_with(self):
        # A one-minute demo (no minimum), a 120 s test minimum, and an older run without the field.
        demo = run_checks(make_run(self.root, "demo", seconds=61.0, minimum=0))
        self.assertTrue(demo["automaticPass"])
        self.assertEqual((demo["minSeconds"], demo["minimumSource"]), (0, "run"))
        tested = run_checks(make_run(self.root, "tested", seconds=130.8, minimum=120))
        self.assertTrue(tested["automaticPass"])
        self.assertEqual((tested["minSeconds"], tested["minimumSource"]), (120, "run"))
        short = run_checks(make_run(self.root, "short-of-own", seconds=110.0, minimum=120))
        self.assertIn("length: 110.0 s is under the 120 s minimum", short["failures"])
        legacy = run_checks(make_run(self.root, "legacy", seconds=400.0))
        self.assertEqual((legacy["minSeconds"], legacy["minimumSource"]), (420, "default"))
        self.assertFalse(legacy["automaticPass"])

    def test_explicit_minimum_overrides_every_run(self):
        checks = run_checks(make_run(self.root, "demo", seconds=61.0, minimum=0), min_seconds=420)
        self.assertEqual((checks["minSeconds"], checks["minimumSource"]), (420, "command line"))
        self.assertIn("length: 61.0 s is under the 420 s minimum", checks["failures"])
        self.assertFalse(checks["automaticPass"])

    def test_content_extension_rounds_and_lengths_are_reported(self):
        run = make_run(self.root, "extended", seconds=428.9, minimum=420)
        write(run / "duration-extension.json", {"status": "passed", "estimatedCostUsd": 0.2, "rounds": [
            {"round": 1, "promoted": True, "beforeSeconds": 412.4, "afterSeconds": 418.0},
            {"round": 2, "promoted": False, "beforeSeconds": 418.0},  # A failed attempt is not a round.
            {"round": 2, "promoted": True, "beforeSeconds": 418.0, "afterSeconds": 428.9},
        ]})
        self.assertEqual(run_checks(run)["extension"],
                         {"status": "passed", "rounds": 2, "beforeSeconds": 412.4, "afterSeconds": 428.9})
        # Older records have no "promoted" flag; an accepted round is one with afterSeconds.
        old = make_run(self.root, "old-format")
        write(old / "duration-extension.json", {"status": "passed", "rounds": [
            {"directory": "duration-attempt-01", "beforeSeconds": 88.7, "afterSeconds": 130.8}]})
        self.assertEqual(run_checks(old)["extension"]["rounds"], 1)
        unneeded = make_run(self.root, "long-enough")
        write(unneeded / "duration-extension.json", {"status": "passed", "rounds": []})
        self.assertEqual(run_checks(unneeded)["extension"],
                         {"status": "passed", "rounds": 0, "beforeSeconds": None, "afterSeconds": None})
        self.assertIsNone(run_checks(make_run(self.root, "no-record"))["extension"])

    def test_report_shows_each_minimum_and_extension(self):
        extended = make_run(self.root, "l1-extended", seconds=426.0, minimum=420)
        write(extended / "duration-extension.json", {"status": "passed", "rounds": [
            {"promoted": True, "beforeSeconds": 412.4, "afterSeconds": 426.0}]})
        demo = make_run(self.root, "demo", seconds=61.0, minimum=0)
        failed = make_run(self.root, "l1-failed", seconds=405.0, minimum=420)
        write(failed / "duration-extension.json", {"status": "failed", "rounds": []})
        out = write_report(build([extended, demo, failed]), self.root / "report")
        text = (out / "scorecard.md").read_text(encoding="utf-8")
        self.assertIn("(minimum set per run)", text)
        self.assertIn("**Runs lengthened by a content extension:** 1", text)
        self.assertIn("| `l1-extended` | Topic l1-extended | 7:06 | 7:00 | 6:52 → 7:06 (1 round) |", text)
        self.assertIn("| `demo` | Topic demo | 1:01 | none | — |", text)
        self.assertIn("| `l1-failed` | Topic l1-failed | 6:45 | 7:00 | failed |", text)
        with (out / "scorecard.csv").open(newline="") as handle:
            rows = {row["run"]: row for row in csv.DictReader(handle)}
        self.assertEqual((rows["l1-extended"]["min_seconds"], rows["l1-extended"]["minimum_source"]), ("420", "run"))
        self.assertEqual((rows["l1-extended"]["extension_rounds"], rows["l1-extended"]["seconds_before_extension"]),
                         ("1", "412.4"))
        self.assertEqual(rows["demo"]["extension_rounds"], "")
        shared = build([extended, failed], min_seconds=420)["summary"]
        self.assertEqual(shared["minSeconds"], 420)
        self.assertIn("(minimum 7:00)", markdown(build([extended, failed])))
        self.assertIn("(no minimum)", markdown(build([demo])))

    def test_saved_plan_reproduction_is_marked_and_not_live(self):
        checks = run_checks(make_run(self.root, "replay", live=False))
        self.assertFalse(checks["live"])
        self.assertEqual(checks["stages"]["plan"], "reproduction")
        self.assertEqual(checks["topic"], "Title of replay")
        self.assertTrue(checks["automaticPass"])

    def test_missing_directory_is_an_error(self):
        with self.assertRaises(ScorecardError):
            run_checks(self.root / "nowhere")


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_rejects_bad_scores_unknown_runs_missing_raters_and_repeats(self):
        bad = {
            "out of range": [rating("a", "tong", (6, 4, 4, 4, 4))],
            "not a number": [rating("a", "tong", ("good", 4, 4, 4, 4))],
            "unknown run": [rating("zzz", "tong")],
            "no rater": [rating("a", "")],
            "repeat": [rating("a", "Tong"), rating("a", "tong")],
        }
        for name, rows in bad.items():
            with self.subTest(name), self.assertRaises(ScorecardError):
                read_ratings(write_ratings(self.root / f"{name}.csv", rows), {"a"})
        with self.assertRaises(ScorecardError):
            (self.root / "columns.csv").write_text("run,rater,accuracy\n", encoding="utf-8")
            read_ratings(self.root / "columns.csv", {"a"})

    def test_blank_and_template_rows_are_skipped(self):
        path = write_ratings(self.root / "sheet.csv", [rating("a", "", ("", "", "", "", "")),
                                                       rating("", "", ("", "", "", "", "")),
                                                       rating("a", "tong", (5, "", 4, 4, 3), "03:10 label overlaps")])
        ratings = read_ratings(path, {"a"})
        self.assertEqual(len(ratings["a"]), 1)
        self.assertIsNone(ratings["a"][0]["scores"]["clarity"])
        self.assertEqual(ratings["a"][0]["notes"], "03:10 label overlaps")


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runs = [make_run(self.root, "01-good"), make_run(self.root, "02-low"),
                     make_run(self.root, "03-unrated"), make_run(self.root, "04-failed", plan="failed"),
                     make_run(self.root, "05-replay", live=False)]
        self.ratings = write_ratings(self.root / "ratings.csv", [
            rating("01-good", "tong", (5, 4, 4, 4, 4)), rating("01-good", "harry", (4, 4, 3, 4, 5)),
            rating("02-low", "tong", (4, 4, 2, 4, 4), "visuals static for a minute"),
            rating("03-unrated", "tong", (4, "", 4, 4, 4)),
            rating("05-replay", "tong", (5, 5, 5, 5, 5)),
        ])

    def tearDown(self):
        self.temporary.cleanup()

    def test_verdicts_success_rate_and_quality(self):
        results = build(self.runs, self.ratings)
        verdicts = {run["run"]: run["verdict"] for run in results["runs"]}
        self.assertEqual(verdicts, {"01-good": "accepted", "02-low": "below quality bar",
                                    "03-unrated": "needs rating", "04-failed": "failed", "05-replay": "reproduction"})
        good = results["runs"][0]["quality"]
        self.assertEqual(good["criteria"], {"accuracy": 4.5, "clarity": 4, "visuals": 3.5, "audio": 4, "sync": 4.5})
        self.assertEqual(good["score"], 4.1)
        summary = results["summary"]
        # Reproductions are listed and rated but never counted as live attempts.
        self.assertEqual((summary["liveAttempts"], summary["automaticSuccesses"], summary["successRate"]), (4, 3, 0.75))
        self.assertEqual(summary["accepted"], 1)
        # Live runs only: 01-good 4.1 and 02-low 3.6. The replay's 5.0 and the incomplete rating are left out.
        self.assertEqual(summary["meanQualityScore"], 3.85)
        self.assertEqual(summary["humanCriteria"]["visuals"], 2.75)
        self.assertEqual(summary["reviewCriteria"]["accuracy"], 5)
        self.assertEqual(summary["costUsd"], 5.75)

    def test_report_files_and_markdown(self):
        results = build(self.runs, self.ratings)
        out = write_report(results, self.root / "report")
        self.assertEqual(sorted(path.name for path in out.iterdir()), ["scorecard.csv", "scorecard.json", "scorecard.md"])
        text = (out / "scorecard.md").read_text(encoding="utf-8")
        self.assertIn("**Success rate (live attempts):** 3 of 4 (75%)", text)
        self.assertIn("`04-failed`: plan: Outline failed validation", text)
        self.assertIn("`02-low` tong: visuals static for a minute", text)
        with (out / "scorecard.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["verdict"] for row in rows][:2], ["accepted", "below quality bar"])
        with self.assertRaises(FileExistsError):
            write_report(results, out)
        self.assertEqual(markdown(results), text)

    def test_duplicate_run_names_are_rejected(self):
        other = self.root / "elsewhere"
        other.mkdir()
        with self.assertRaises(ScorecardError):
            build([self.runs[0], make_run(other, "01-good")])

    def test_template_lists_each_run_once(self):
        path = write_template(self.runs[:2], self.root / "sheet.csv")
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["run", "rater", *HUMAN_CRITERIA, "notes"])
        self.assertEqual([row[0] for row in rows[1:]], ["01-good", "02-low"])
        self.assertEqual(read_ratings(path, {"01-good", "02-low"}), {})
        with self.assertRaises(FileExistsError):
            write_template(self.runs[:2], path)

    def test_command_line_template_and_report(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["scorecard", "--runs", *map(str, self.runs), "--template",
                                   str(self.root / "blank.csv")]), 0)
            self.assertEqual(main(["scorecard", "--runs", *map(str, self.runs), "--ratings", str(self.ratings),
                                   "--out", str(self.root / "cli-report")]), 0)
        self.assertIn("3 of 4 live runs succeeded (75%) | 1 accepted | mean quality 3.85", output.getvalue())
        self.assertTrue((self.root / "cli-report" / "scorecard.md").is_file())
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(["scorecard", "--runs", str(self.root / "missing"), "--out",
                                   str(self.root / "x")]), 1)
        self.assertIn("is not a run directory", errors.getvalue())

    def test_command_line_minimum_applies_to_every_run(self):
        demo = make_run(self.root, "06-demo", seconds=61.0, minimum=0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["scorecard", "--runs", str(demo), "--out", str(self.root / "own")]), 0)
            self.assertEqual(main(["scorecard", "--runs", str(demo), "--min-seconds", "420",
                                   "--out", str(self.root / "level1")]), 0)
        own = json.loads((self.root / "own" / "scorecard.json").read_text(encoding="utf-8"))
        level1 = json.loads((self.root / "level1" / "scorecard.json").read_text(encoding="utf-8"))
        self.assertTrue(own["runs"][0]["automaticPass"])
        self.assertEqual(level1["runs"][0]["verdict"], "failed")
        self.assertEqual(level1["summary"]["minSeconds"], 420)


if __name__ == "__main__":
    unittest.main()
