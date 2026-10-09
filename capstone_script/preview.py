"""Build preview.html: a browser slideshow of a narrated scene plan.

The page draws each scene with its template, highlights the current point or
node and shows the current line as a subtitle, all driven by the preview
track's clock. It is a quick check of script and narration, not the renderer.
"""

import json
from pathlib import Path

from .scene_plan import load_plan

TEMPLATE = Path(__file__).with_name("preview.html")


def build_preview(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    plan = load_plan(run_dir / "scene-plan.json")
    manifest = json.loads((run_dir / "audio-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise ValueError(f"Narration in {run_dir} is not complete; run narrate again in a new directory.")
    data = {
        "plan": plan.model_dump(mode="json", by_alias=True, exclude_none=True),
        "blocks": [{key: block[key] for key in
                    ("sceneId", "narrationId", "text", "previewStartSeconds", "durationSeconds")}
                   for block in manifest["blocks"]],
        "audio": manifest["preview"]["audioPath"],
        "lead": manifest["preview"]["leadSeconds"],
        "tail": manifest["preview"]["tailSeconds"],
        "speechSeconds": manifest["totalSpeechSeconds"],
    }
    # "</" inside a script element would end it early, whatever the JSON says.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    output = run_dir / "preview.html"
    output.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__PREVIEW_DATA__", payload),
                      encoding="utf-8", newline="\n")
    return output
