"""Render wrapper tests: the Remotion command and its preconditions, without running Node."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.render import RenderError, inspect_motion, render_command, render_video, share_command, still_command

TIMELINE = Path("runs") / "demo" / "video" / "timeline.json"
OUTPUT = Path("runs") / "demo" / "video.mp4"


class RenderCommandTests(unittest.TestCase):
    def test_motion_inspection_keeps_warnings_reviewable_and_skips_slides(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            timeline = run_dir / "video" / "timeline.json"
            report = run_dir / "motion-inspection.json"
            report.write_text(json.dumps({"status": "needs-review"}), encoding="utf-8")
            messages = []
            with patch("capstone_script.render._node", return_value="node"), \
                    patch("capstone_script.render.subprocess.run") as run:
                run.return_value.returncode = 0
                self.assertIsNone(inspect_motion(timeline, {"scenes": [{"template": "concept"}]}))
                run.assert_not_called()
                result = inspect_motion(timeline, {"scenes": [{"template": "motion"}]}, messages.append)
                self.assertEqual(result, {"path": report.name, "status": "needs-review"})
                self.assertEqual(run.call_args.args[0][-2:], [str(timeline), str(report)])
                self.assertIn("possible contacts", messages[-1])

    def test_command_passes_the_timeline_and_its_folder(self):
        with patch("capstone_script.render.shutil.which", return_value="node"), \
                patch("capstone_script.render.REMOTION_CLI", Path(__file__)):
            command = render_command(TIMELINE, OUTPUT)
            draft = render_command(TIMELINE, OUTPUT, draft=True)
        self.assertEqual(command[0], "node")
        self.assertEqual(command[2:6], ["render", "src/index.ts", "Explainer", str(OUTPUT)])
        self.assertIn(f"--props={TIMELINE}", command)
        self.assertIn(f"--public-dir={TIMELINE.parent}", command)
        self.assertNotIn("--scale=0.5", command)
        self.assertEqual(draft[-1], "--scale=0.5")
        self.assertFalse(any(part.startswith("--concurrency") for part in command))

    def test_concurrency_is_passed_to_remotion_only_when_set(self):
        with patch("capstone_script.render.shutil.which", return_value="node"), \
                patch("capstone_script.render.REMOTION_CLI", Path(__file__)):
            limited = render_command(TIMELINE, OUTPUT, concurrency=2)
            limited_draft = render_command(TIMELINE, OUTPUT, draft=True, concurrency=1)
        self.assertIn("--concurrency=2", limited)
        self.assertIn("--concurrency=1", limited_draft)
        self.assertEqual(limited_draft[-1], "--scale=0.5")

    def test_bad_concurrency_is_refused_before_rendering(self):
        for value in (0, -1, 1.5, "2", True):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary, \
                    patch("capstone_script.render.subprocess.run") as run, \
                    self.assertRaisesRegex(ValueError, "Concurrency must be"):
                render_video(Path(temporary), concurrency=value)
            run.assert_not_called()

    def test_command_line_checks_concurrency_while_parsing(self):
        from capstone_script.__main__ import main
        for command in (["render", "--run", "runs/x"], ["ensure-duration", "--run", "runs/x"],
                        ["run", "--topic", "Queues", "--out", "runs/x", "--render"]):
            for value in ("0", "two"):
                with self.subTest(command=command[0], value=value), \
                        patch("capstone_script.__main__.render_video") as render, \
                        patch("sys.stderr"), self.assertRaises(SystemExit) as stopped:
                    main([*command, "--concurrency", value])
                self.assertEqual(stopped.exception.code, 2)
                render.assert_not_called()

    def test_render_command_line_passes_concurrency_through(self):
        from capstone_script.__main__ import main
        info = {"videoPath": "video.mp4", "width": 1920, "height": 1080, "probedSeconds": 1.0,
                "bytes": 1, "renderSeconds": 1}
        with patch("capstone_script.__main__.render_video", return_value=info) as render, patch("builtins.print"):
            self.assertEqual(main(["render", "--run", "runs/x", "--concurrency", "2"]), 0)
            self.assertEqual(render.call_args.kwargs["concurrency"], 2)
            main(["render", "--run", "runs/x"])
            self.assertIsNone(render.call_args.kwargs["concurrency"])

    def test_look_reaches_the_renderer_props_and_unknown_looks_are_refused(self):
        from capstone_script.__main__ import main
        from capstone_script.render import render_props
        info = {"videoPath": "video.mp4", "width": 1920, "height": 1080, "probedSeconds": 1.0,
                "bytes": 1, "renderSeconds": 1}
        with patch("capstone_script.__main__.render_video", return_value=info) as render, patch("builtins.print"):
            main(["render", "--run", "runs/x", "--look", "sketch"])
            self.assertEqual(render.call_args.kwargs["look"], "sketch")
            main(["render", "--run", "runs/x"])
            self.assertEqual(render.call_args.kwargs["look"], "vector")
        with tempfile.TemporaryDirectory() as temporary:
            timeline = Path(temporary) / "timeline.json"
            timeline.write_text(json.dumps({"scenes": []}), encoding="utf-8")
            props = json.loads(render_props(timeline, music=False, look="sketch").read_text(encoding="utf-8"))
            self.assertEqual(props["look"], "sketch")
            with self.assertRaisesRegex(ValueError, "Unknown look"):
                render_props(timeline, music=False, look="watercolour")
        with tempfile.TemporaryDirectory() as temporary, patch("capstone_script.render.subprocess.run") as run,                 self.assertRaisesRegex(ValueError, "Unknown look"):
            render_video(Path(temporary), look="watercolour")
        run.assert_not_called()

    def test_thumbnail_and_sharing_commands(self):
        with patch("capstone_script.render.shutil.which", return_value="node"),                 patch("capstone_script.render.REMOTION_CLI", Path(__file__)):
            still = still_command(TIMELINE, Path("thumbnail.png"))
            share = share_command(OUTPUT, Path("video-720p.mp4"))
        self.assertEqual(still[2:6], ["still", "src/index.ts", "Explainer", "thumbnail.png"])
        self.assertIn("--frame=30", still)
        self.assertIn(f"--public-dir={TIMELINE.parent}", still)
        self.assertEqual(share[2], "ffmpeg")
        self.assertEqual(share[share.index("-i") + 1], str(OUTPUT))
        self.assertIn("scale=1280:720", share)
        self.assertEqual(share[-1], "video-720p.mp4")

    def test_missing_node_or_renderer_is_explained(self):
        with patch("capstone_script.render.shutil.which", return_value=None), \
                self.assertRaisesRegex(RenderError, "needs Node.js"):
            render_command(TIMELINE, OUTPUT)
        with patch("capstone_script.render.shutil.which", return_value="node"), \
                patch("capstone_script.render.REMOTION_CLI", Path("missing") / "remotion-cli.js"), \
                self.assertRaisesRegex(RenderError, "npm install"):
            render_command(TIMELINE, OUTPUT)

    def test_a_draft_cannot_get_a_sharing_copy(self):
        with tempfile.TemporaryDirectory() as temporary, patch("capstone_script.render.subprocess.run") as run, \
                self.assertRaisesRegex(ValueError, "a draft is already smaller"):
            render_video(Path(temporary), draft=True, share=True)
        run.assert_not_called()

    def test_existing_video_is_refused_before_rendering(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "video.mp4").write_bytes(b"")
            with patch("capstone_script.render.subprocess.run") as run, self.assertRaises(FileExistsError):
                render_video(Path(temporary))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
