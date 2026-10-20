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
             seconds=434.5, expected=None, draft=False, motion=None, render=True) -> Path:
    run = root / name
    run.mkdir()
    write(run / "scene-plan.json", {"title": f"Title of {name}", "scenes": []})
    if live:
        write(run / "project-spec.json", {"topic": f"Topic {name}", "audience": "Adults", "targetDurationSec": 420})
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

    def test_animation_report_is_read_even_without_a_render(self):
        run = make_run(self.root, "stopped", render=False)
        write(run / "motion-inspection.json", {"status": "geometry-and-timing-checks-passed", "scenes": []})
        self.assertEqual(run_checks(run)["motionInspection"], "geometry-and-timing-checks-passed")

    def test_review_is_optional_and_minimum_length_is_configurable(self):
        checks = run_checks(make_run(self.root, "unreviewed", review=None, seconds=300), min_seconds=240)
        self.assertEqual(checks["stages"]["review"], "not requested")
        self.assertTrue(checks["automaticPass"])
        self.assertIsNone(checks["reviewScores"])

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


if __name__ == "__main__":
    unittest.main()
