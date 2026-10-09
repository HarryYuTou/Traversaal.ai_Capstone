"""Reference URL tests: text extraction and the plan command, with the download patched out."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.__main__ import _reference_for, main
from capstone_script.evaluate import evaluate
from capstone_script.planner import make_spec, write_plan_run
from capstone_script.reference import fetch_reference, html_text
from test_planner import TOPIC, FakeClient, model_output, response

PAGE = """<html><head><title>How DNS works</title><style>p {color: red}</style></head>
<body><nav><a href="/">Home</a> | <a href="/about">About</a></nav>
<header>Site banner</header>
<h1>How DNS works</h1>
<p>DNS turns a name like example.com into an IP address.</p>
<ul><li>Your browser asks a resolver.</li><li>The resolver asks name servers.</li></ul>
<script>console.log("tracking")</script>
<footer>Copyright notice</footer></body></html>"""
REFERENCE = "Source: https://example.org/dns\n\n" + "DNS turns names into addresses. " * 10 + "\n"


class ReferenceTests(unittest.TestCase):
    def test_html_keeps_readable_text_and_drops_page_chrome(self):
        self.assertEqual(html_text(PAGE), "# How DNS works\n## How DNS works\n"
                         "DNS turns a name like example.com into an IP address.\n"
                         "- Your browser asks a resolver.\n- The resolver asks name servers.")

    def test_titles_inside_skipped_parts_are_ignored(self):
        page = "<html><head><title>Real title</title></head><body><svg><title>Search icon</title></svg><p>Text</p>"
        self.assertEqual(html_text(page), "# Real title\nText")

    def test_binary_responses_are_refused(self):
        class Response:
            def __init__(self):
                self.headers = Headers()
            def read(self, size):
                return b"%PDF-1.7 binary"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        class Headers:
            def get_content_charset(self):
                return None
            def get_content_type(self):
                return "application/pdf"

        with patch("capstone_script.reference.urlopen", return_value=Response()), \
                self.assertRaisesRegex(ValueError, "application/pdf, not a web page or text file"):
            fetch_reference("https://example.org/paper.pdf")

    def test_a_run_keeps_its_own_copy_of_the_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            facts = Path(temporary) / "facts.md"
            facts.write_text(REFERENCE, encoding="utf-8")
            spec, text = make_spec(TOPIC, "Students", 75, facts)
            out = Path(temporary) / "run"
            write_plan_run(out, spec, FakeClient(response(model_output())), text)
            facts.unlink()  # Moving or deleting the original must not break a later review.
            self.assertEqual(_reference_for(out), REFERENCE)
            self.assertEqual(json.loads((out / "project-spec.json").read_text(encoding="utf-8"))["referenceCopy"],
                             "reference.md")

    def test_only_web_addresses_are_fetched(self):
        with self.assertRaisesRegex(ValueError, "must start with http"):
            fetch_reference("file:///etc/passwd")

    def test_plan_command_saves_and_records_the_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "run"
            client = FakeClient(response(model_output()))
            with patch("capstone_script.__main__.fetch_reference", return_value=REFERENCE), \
                    patch("capstone_script.__main__._client", return_value=client), \
                    patch("capstone_script.__main__.load_env_file"), redirect_stdout(io.StringIO()):
                code = main(["plan", "--topic", TOPIC, "--out", str(out),
                             "--reference-url", "https://example.org/dns"])
            self.assertEqual(code, 0)
            self.assertEqual((out / "reference.md").read_text(encoding="utf-8"), REFERENCE)
            spec = json.loads((out / "project-spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["referenceUrl"], "https://example.org/dns")
            self.assertEqual(spec["referenceSha256"], hashlib.sha256(REFERENCE.encode("utf-8")).hexdigest())
            self.assertIn("<reference>\nSource: https://example.org/dns", client.calls[0]["messages"][0]["content"])

    def test_file_and_url_references_together_are_refused_before_downloading(self):
        with tempfile.TemporaryDirectory() as temporary, patch("capstone_script.__main__.fetch_reference") as fetch, \
                redirect_stdout(io.StringIO()):
            code = main(["plan", "--topic", TOPIC, "--out", str(Path(temporary) / "run"), "--reference",
                         "fixtures/reference-primary.md", "--reference-url", "https://example.org/dns"])
        self.assertEqual(code, 1)
        fetch.assert_not_called()

    def test_evaluation_records_a_topic_whose_reference_cannot_be_downloaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            topics = [{"topic": TOPIC, "audience": "Students", "duration": 75,
                       "referenceUrl": "https://example.org/missing"}]
            with patch("capstone_script.evaluate.fetch_reference", side_effect=OSError("404")):
                results = evaluate(topics, Path(temporary) / "eval", FakeClient())
            self.assertEqual(results["runs"][0]["planStatus"], "not started")
            self.assertIn("404", results["runs"][0]["error"])
            self.assertEqual(results["summary"]["planned"], 0)


if __name__ == "__main__":
    unittest.main()
