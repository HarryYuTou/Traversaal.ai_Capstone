"""Narrated run -> MP4, using the Remotion project in renderer/.

The run's timeline is built first if it does not exist yet. The Remotion
command line then renders the Explainer composition with the timeline as its
input props and the run's video folder as the public folder, which is where
the renderer reads narration.wav. Rendering needs Node.js and `npm install` in
renderer/; the first render also downloads a headless Chrome for Remotion.
"""

import json
from pathlib import Path
import shutil
import subprocess
from time import perf_counter

from .planner import write_json
from .timeline import VIDEO_DIR, write_timeline

RENDERER = Path(__file__).resolve().parents[1] / "renderer"
REMOTION_CLI = RENDERER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"


class RenderError(RuntimeError):
    pass


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        raise RenderError("Rendering needs Node.js; install it from https://nodejs.org and try again.")
    if not REMOTION_CLI.is_file():
        raise RenderError(f"The renderer is not installed; run `npm install` in {RENDERER}.")
    return node


def render_command(timeline_path: Path, output: Path, draft: bool = False) -> list[str]:
    command = [_node(), str(REMOTION_CLI), "render", "src/index.ts", "Explainer", str(output),
               f"--props={timeline_path}", f"--public-dir={timeline_path.parent}", "--codec=h264"]
    return command + (["--scale=0.5"] if draft else [])


# The title card is fully faded in by this frame.
THUMBNAIL_FRAME = 30
# A 720p copy at this quality is about a quarter of the full file and still sharp for slides.
SHARE_ENCODING = ["-vf", "scale=1280:720", "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-tune", "stillimage",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]


def still_command(timeline_path: Path, output: Path, frame: int = THUMBNAIL_FRAME) -> list[str]:
    return [_node(), str(REMOTION_CLI), "still", "src/index.ts", "Explainer", str(output), f"--frame={frame}",
            f"--props={timeline_path}", f"--public-dir={timeline_path.parent}"]


def share_command(video: Path, output: Path) -> list[str]:
    return [_node(), str(REMOTION_CLI), "ffmpeg", "-v", "error", "-y", "-i", str(video), *SHARE_ENCODING, str(output)]


def probe_seconds(video: Path) -> float:
    """Duration of a rendered file, read with the ffprobe that ships with Remotion."""
    result = subprocess.run([_node(), str(REMOTION_CLI), "ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
                            cwd=RENDERER, capture_output=True, text=True, check=True)
    return float(result.stdout.strip().splitlines()[-1])


def render_video(run_dir: Path, draft: bool = False, share: bool = False, progress=lambda message: None) -> dict:
    """Render video.mp4 (or video-draft.mp4 at half size) into run_dir and describe it in video-info.json.

    A full render also writes thumbnail.png from the title card; `share` adds video-720p.mp4, a smaller
    copy for uploads and email.
    """
    if draft and share:
        raise ValueError("--share makes a 720p copy of a full render; a draft is already smaller than that.")
    run_dir = Path(run_dir).resolve()
    name = "video-draft" if draft else "video"
    output = run_dir / f"{name}.mp4"
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}. Remove it to render again.")
    timeline_path = run_dir / VIDEO_DIR / "timeline.json"
    if not timeline_path.exists():
        progress("Building the frame timeline, aligned narration and subtitles...")
        write_timeline(run_dir)
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    command = render_command(timeline_path, output, draft)
    progress(f"Rendering {timeline['durationInFrames']} frames with Remotion...")
    started = perf_counter()
    result = subprocess.run(command, cwd=RENDERER)
    seconds = perf_counter() - started
    if result.returncode != 0 or not output.is_file():
        raise RenderError("Remotion did not finish the video; see its messages above.")
    duration = probe_seconds(output)
    scale = 0.5 if draft else 1
    info = {"schemaVersion": "1", "videoPath": output.name, "draft": draft,
            "width": round(timeline["width"] * scale), "height": round(timeline["height"] * scale),
            "fps": timeline["fps"], "frames": timeline["durationInFrames"],
            "expectedSeconds": timeline["durationSeconds"], "probedSeconds": duration,
            "bytes": output.stat().st_size, "renderSeconds": round(seconds, 1),
            "subtitles": [f"{VIDEO_DIR}/subtitles.srt", f"{VIDEO_DIR}/subtitles.vtt"]}
    if not draft:
        progress("Rendering the thumbnail...")
        if subprocess.run(still_command(timeline_path, run_dir / "thumbnail.png"), cwd=RENDERER).returncode == 0:
            info["thumbnail"] = "thumbnail.png"
    if share:
        progress("Encoding a 720p copy for sharing...")
        copy = run_dir / "video-720p.mp4"
        subprocess.run(share_command(output, copy), cwd=RENDERER, check=True)
        info["shareCopy"] = {"path": copy.name, "bytes": copy.stat().st_size}
    write_json(run_dir / f"{name}-info.json", info)
    if abs(duration - timeline["durationSeconds"]) > 0.2:
        raise RenderError(f"{output.name} lasts {duration:.2f} s, but the timeline is "
                          f"{timeline['durationSeconds']:.2f} s.")
    return info
