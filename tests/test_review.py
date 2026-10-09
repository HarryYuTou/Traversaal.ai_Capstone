"""Script review tests with a scripted fake client: no network calls and no API key."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.__main__ import main
from capstone_script.planner import PlannerError, make_spec, write_json
from capstone_script.review import speech_notes, write_review
from capstone_script.scene_plan import load_plan
from test_planner import TOPIC, FakeClient, model_output, response

ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "fixtures" / "scene-plan.valid.json"
FIRST_LINE = "scene-01-line-01"
NEW_TEXT = "Picture typing a web address and watching a page appear in about a second."


def review_output(edits=None, scores=None):
    return {"scores": scores or {"clarity": 4, "flow": 3, "accuracy": 5, "engagement": 3, "audienceFit": 4},
            "issues": [{"location": FIRST_LINE, "category": "clarity", "severity": "medium",
                        "problem": "The opening line does not set up the question."}],
            "edits": [{"lineId": FIRST_LINE, "text": NEW_TEXT}] if edits is None else edits}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capstone-review-test-")
        self.addCleanup(temporary.cleanup)
        self.run_dir = Path(temporary.name) / "run"
        self.run_dir.mkdir()
        shutil.copy(VALID, self.run_dir / "scene-plan.json")
        spec, _ = make_spec(TOPIC, "University students with no networking background", 75)
        write_json(self.run_dir / "project-spec.json", spec)

    def saved(self, name):
        return json.loads((self.run_dir / name).read_text(encoding="utf-8"))

    def test_edits_are_applied_and_the_draft_is_kept(self):
        client = FakeClient(response(review_output()))
        _, changes = write_review(self.run_dir, client)
        plan = load_plan(self.run_dir / "scene-plan.json")
        self.assertEqual(plan.scenes[0].narration[0].text, NEW_TEXT)
        self.assertEqual(plan.scenes[0].narration[0].highlight_point_index,
                         load_plan(VALID).scenes[0].narration[0].highlight_point_index)
        self.assertEqual(self.saved("scene-plan.draft.json"), json.loads(VALID.read_text(encoding="utf-8")))
        record = self.saved("review.json")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["scores"]["audienceFit"], 4)
        self.assertEqual(changes, record["changes"])
        self.assertEqual(changes[0]["after"], NEW_TEXT)
        self.assertEqual(record["attempts"][0]["step"], "review")
        request = client.calls[0]["messages"][0]["content"]
        self.assertIn("<plan>", request)
        self.assertIn("the draft has 214 words", request)

    def test_invalid_edits_get_one_repair_request(self):
        bad = [{"lineId": "scene-09-line-01", "text": "Fine."},
               {"lineId": FIRST_LINE, "text": " ".join(["word"] * 26)}]
        client = FakeClient(response(review_output(bad, {"clarity": 6, "flow": 3, "accuracy": 5,
                                                         "engagement": 3, "audienceFit": 4})),
                            response(review_output()))
        write_review(self.run_dir, client)
        repair = client.calls[1]["messages"][2]["content"]
        self.assertIn("scores.clarity: 6 is not between 1 and 5", repair)
        self.assertIn("edits[0].lineId: 'scene-09-line-01' is not a narration line in this plan", repair)
        self.assertIn("edits[1].text: has 26 words", repair)

    def test_edits_that_shrink_the_script_too_much_are_sent_back(self):
        plan = load_plan(VALID)
        short = [{"lineId": line.id, "text": "Short line."} for scene in plan.scenes for line in scene.narration]
        client = FakeClient(response(review_output(short)), response(review_output(short)))
        with self.assertRaisesRegex(PlannerError, "the edited script has 36 words"):
            write_review(self.run_dir, client)
        self.assertEqual(self.saved("review.json")["status"], "failed")
        self.assertFalse((self.run_dir / "scene-plan.draft.json").exists())

    def test_narrated_runs_are_not_reviewed(self):
        (self.run_dir / "audio-manifest.json").write_text("{}", encoding="utf-8")
        client = FakeClient()
        with self.assertRaisesRegex(FileExistsError, "already narrated"):
            write_review(self.run_dir, client)
        self.assertEqual(client.calls, [])

    def test_speech_notes_flag_symbols_abbreviations_and_acronyms(self):
        data = json.loads(VALID.read_text(encoding="utf-8"))
        data["scenes"][0]["narration"][0]["text"] = "About 90% of DNS lookups, e.g. for HTTPS sites, are cached."
        path = self.run_dir / "noisy.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        notes = [note["note"] for note in speech_notes(load_plan(path)) if note["lineId"] == FIRST_LINE]
        self.assertEqual(len(notes), 3, notes)
        self.assertIn("%", notes[0])
        self.assertIn("'e.g.'", notes[1])
        self.assertIn("DNS, HTTPS", notes[2])

    def test_plan_command_with_review(self):
        out = self.run_dir.parent / "planned"
        client = FakeClient(response(model_output()), response(review_output()))
        stdout = io.StringIO()
        with patch("capstone_script.__main__._client", return_value=client), \
                patch("capstone_script.__main__.load_env_file"), redirect_stdout(stdout):
            code = main(["plan", "--topic", TOPIC, "--out", str(out), "--review"])
        self.assertEqual(code, 0)
        self.assertIn("1 issues | 1 lines rewritten", stdout.getvalue())
        self.assertEqual(load_plan(out / "scene-plan.json").scenes[0].narration[0].text, NEW_TEXT)


if __name__ == "__main__":
    unittest.main()
