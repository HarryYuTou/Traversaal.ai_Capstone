"""Cheap readiness checks; never load models or make a network request."""

import importlib.util
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FIXTURE = Path("fixtures/scene-plan.motion-network.json")
SEEDANCE_FIXTURE = Path("fixtures/scene-plan.seedance-glass.json")
SEEDANCE_SAMPLE = {
    "title": "Why a Cold Glass Gets Wet", "topic": "Why does a cold glass get wet on the outside?",
    "audience": "Curious adults", "durationSeconds": 30,
}
SAMPLE = {
    "title": "How a Message Crosses the Internet",
    "topic": "How does a message travel across the internet?",
    "audience": "Curious adults with no networking background",
    "durationSeconds": 45,
}
PYTHON_MODULES = ("pydantic", "numpy", "scipy", "soundfile", "torch", "kokoro",
                  "misaki", "spacy", "en_core_web_sm", "huggingface_hub")


def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def api_key_available(root=ROOT, names=None):
    names = names or {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
    if any(os.environ.get(name, "").strip() for name in names):
        return True
    path = Path(root) / ".env"
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        # Match the pipeline's environment precedence, including an existing empty variable.
        if key in names and key not in os.environ and value.strip().strip('"').strip("'").strip():
            return True
    return False


def model_cached(root=ROOT):
    from capstone_tts.engine import MODEL_REVISION, VOICE_ID
    snapshot = (Path(root) / ".cache/huggingface/models--hexgrad--Kokoro-82M/snapshots"
                / MODEL_REVISION)
    return all((snapshot / name).is_file()
               for name in ("config.json", "kokoro-v1_0.pth", f"voices/{VOICE_ID}.pt"))


def health(root=ROOT):
    root = Path(root)
    missing = [name for name in PYTHON_MODULES if not has_module(name)]
    fixture = root / SAMPLE_FIXTURE
    try:
        fixture_ok = isinstance(json.loads(fixture.read_text(encoding="utf-8"))["scenes"], list)
    except (OSError, ValueError, KeyError, TypeError):
        fixture_ok = False
    cached = model_cached(root)
    checks = [
        {"id": "python", "label": "Python video dependencies", "ok": not missing,
         "detail": "Installed in this Python environment." if not missing else
         "Missing: " + ", ".join(missing) + ". Install requirements.lock.txt in the project environment."},
        {"id": "node", "label": "Node.js", "ok": shutil.which("node") is not None,
         "detail": "Required for Remotion video rendering."},
        {"id": "renderer", "label": "Remotion renderer", "ok":
         (root / "renderer/node_modules/@remotion/cli/remotion-cli.js").is_file(),
         "detail": "Install with npm --prefix renderer ci. The first render may download a browser."},
        {"id": "sample", "label": "Built-in sample script", "ok": fixture_ok,
         "detail": "Uses the checked-in animated network story; no Claude API call."},
        {"id": "tts_cache", "label": "Local voice model", "ok": cached,
         "detail": "Cached; narration will run offline on CPU." if cached else
         "Not cached yet. The first narration downloads the pinned Kokoro model."},
        {"id": "claude_sdk", "label": "Claude SDK", "ok": has_module("anthropic"),
         "detail": "Required for a new topic. Install requirements.lock.txt."},
        {"id": "claude_key", "label": "Claude API credential", "ok": api_key_available(root),
         "detail": "Read from the server environment or project .env; never sent to the browser."},
        {"id": "seedance_key", "label": "Seedance Fast API credential", "ok": api_key_available(root, {"ARK_API_KEY"}),
         "detail": "ARK_API_KEY stays on the server. Only Doubao-Seedance-2.0-fast is used; paid API usage applies."},
    ]
    flags = {item["id"]: item["ok"] for item in checks}
    sample_ready = all(flags[key] for key in ("python", "node", "renderer", "sample"))
    live_ready = sample_ready and flags["claude_sdk"] and flags["claude_key"]
    return {"status": "ok", "liveReady": live_ready, "seedanceReady": live_ready and flags["seedance_key"],
            "seedanceSampleReady": sample_ready and flags["seedance_key"], "seedanceSample": dict(SEEDANCE_SAMPLE),
            "sampleReady": sample_ready, "checks": checks, "sample": dict(SAMPLE)}
