"""Reference URL tests: text extraction and the plan command, with the download patched out."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.__main__ import main
from capstone_script.evaluate import evaluate
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
