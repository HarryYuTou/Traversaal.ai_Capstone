"""ScenePlan -> one narration WAV per line, using Harry's capstone_tts module.

Each line goes through capstone_tts.audio.write_run, so it gets the same checks
and audio-info.json as any TTS run, and the Kokoro model loads once per plan.
The manifest records real sample counts. The concatenated preview track uses
fixed pauses for listening; it is not the frame-accurate timeline. Lines whose
text is unchanged from an earlier run with the same voice, model and speed can
reuse that run's audio instead of being synthesized again.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from time import perf_counter

from .planner import write_json
from .scene_plan import dump_plan

# The week-one pauses (6/3/6 frames at 30 fps): scene lead, gap between lines, scene tail.
LEAD_SECONDS, GAP_SECONDS, TAIL_SECONDS = 0.2, 0.1, 0.2


class NarrationError(RuntimeError):
    pass


def reusable_lines(previous_run: Path, model_revision: str, voice_id: str, speed: float) -> dict:
    """Completed lines of an earlier run, keyed by text, if it used the same model, voice and speed."""
    manifest = json.loads((Path(previous_run) / "audio-manifest.json").read_text(encoding="utf-8"))
    same_voice = (manifest.get("status") == "completed" and manifest.get("modelRevision") == model_revision
                  and manifest.get("voiceId") == voice_id and manifest.get("speed") == speed)
    return {block["text"]: block for block in manifest["blocks"]} if same_voice else {}


def narrate_plan(plan, run_dir: Path, engine_factory, speed: float = 1.0, threads: int = 2,
                 offline: bool = False, progress=lambda message: None, reuse_from: Path | None = None) -> dict:
    """Write audio/<narrationId>/, audio-manifest.json and narration-preview.wav into run_dir.

    With reuse_from, lines whose text matches a line of that earlier run copy its audio; the model
    loads only if some line still needs synthesis.
    """
    import numpy as np
    import soundfile as sf
    from capstone_tts.audio import write_run
    from capstone_tts.engine import MODEL_ID, MODEL_REVISION, OUTPUT_RATE, VOICE_ID

    run_dir = Path(run_dir)
    audio_dir = run_dir / "audio"
    if audio_dir.exists() or (run_dir / "audio-manifest.json").exists():
        raise FileExistsError(f"Narration already exists in {run_dir}. Choose a new output directory.")
    started = perf_counter()
    manifest = {"schemaVersion": "1", "status": "failed", "projectId": plan.project_id,
                "planSha256": hashlib.sha256(dump_plan(plan).encode("utf-8")).hexdigest(),
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "modelId": MODEL_ID, "modelRevision": MODEL_REVISION, "voiceId": VOICE_ID,
                "device": "cpu", "speed": speed, "sampleRate": OUTPUT_RATE, "channels": 1, "blocks": []}
    reuse = reusable_lines(reuse_from, MODEL_REVISION, VOICE_ID, speed) if reuse_from else {}
    if reuse_from:
        manifest["reusedFrom"] = Path(reuse_from).as_posix()
    engine, load_ms = None, 0.0

    def shared_engine():
        nonlocal engine, load_ms
        if engine is None:
            progress("Loading English speech model on CPU (first run downloads model files)...")
            loading = perf_counter()
            engine = engine_factory()
            load_ms = (perf_counter() - loading) * 1000
        return engine

    audio_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="capstone-lines-") as temporary:
        for scene in plan.scenes:
            for line in scene.narration:
                cached = reuse.get(line.text)
                if cached is not None:
                    info = _copy_line(Path(reuse_from) / Path(cached["audioPath"]).parent, audio_dir / line.id,
                                      cached["sampleCount"])
                    if info is not None:
                        manifest["blocks"].append(_block(scene, line, info, cache_hit=True))
                        progress(f"{line.id}: {info['durationSeconds']:.2f} s (reused)")
                        continue
                text_path = Path(temporary) / f"{line.id}.txt"
                text_path.write_text(line.text + "\n", encoding="utf-8")
                try:
                    info = write_run(text_path=text_path, output_dir=audio_dir / line.id,
                                     engine_factory=shared_engine, speed=speed,
                                     offline=offline, threads=threads)
                except Exception as exc:
                    manifest.update(failedSceneId=scene.id, failedNarrationId=line.id,
                                    error=f"{type(exc).__name__}: {exc}")
                    write_json(run_dir / "audio-manifest.json", manifest)
                    raise NarrationError(f"Narration failed at {scene.id}/{line.id}: {exc}") from exc
                manifest["blocks"].append(_block(scene, line, info, cache_hit=False))
                progress(f"{line.id}: {info['durationSeconds']:.2f} s")

    # Listening preview: real line audio separated by the fixed pauses above.
    blocks = iter(manifest["blocks"])
    pieces, cursor = [], 0

    def pause(seconds):
        nonlocal cursor
        pieces.append(np.zeros(round(seconds * OUTPUT_RATE), dtype=np.float32))
        cursor += pieces[-1].size

    for scene in plan.scenes:
        pause(LEAD_SECONDS)
        for index in range(len(scene.narration)):
            if index:
                pause(GAP_SECONDS)
            block = next(blocks)
            samples, _ = sf.read(run_dir / block["audioPath"], dtype="float32")
            block["previewStartSeconds"] = cursor / OUTPUT_RATE
            pieces.append(samples)
            cursor += samples.size
        pause(TAIL_SECONDS)
    track = np.concatenate(pieces)
    sf.write(run_dir / "narration-preview.wav", track, OUTPUT_RATE, subtype="PCM_16")
    if sf.info(run_dir / "narration-preview.wav").frames != track.size:
        raise NarrationError("The preview track failed verification.")

    synthesis_ms = sum(block["synthesisMs"] for block in manifest["blocks"])
    manifest.update(
        status="completed",
        totalSpeechSeconds=sum(block["sampleCount"] for block in manifest["blocks"]) / OUTPUT_RATE,
        preview={"audioPath": "narration-preview.wav", "leadSeconds": LEAD_SECONDS,
                 "gapSeconds": GAP_SECONDS, "tailSeconds": TAIL_SECONDS, "sampleCount": int(track.size),
                 "durationSeconds": track.size / OUTPUT_RATE,
                 "note": "Listening preview with fixed pauses; not the frame-accurate timeline."},
        reusedLines=sum(block["cacheHit"] for block in manifest["blocks"]),
        timingsMs={"modelLoad": round(load_ms, 2), "synthesis": round(synthesis_ms, 2),
                   "total": round((perf_counter() - started) * 1000, 2)},
    )
    write_json(run_dir / "audio-manifest.json", manifest)
    return manifest


def _copy_line(source: Path, target: Path, sample_count: int):
    """Copy an earlier line's folder and return its audio info, or None (and no folder) if it is unusable."""
    import soundfile as sf

    try:
        shutil.copytree(source, target)
        info = json.loads((target / "audio-info.json").read_text(encoding="utf-8"))
        if sf.info(target / "narration.wav").frames == sample_count == info["sampleCount"]:
            info["timingsMs"]["phonemizationAndSynthesis"] = 0.0
            return info
    except (OSError, ValueError, KeyError, RuntimeError):
        pass  # Missing or damaged earlier audio: synthesize the line instead.
    shutil.rmtree(target, ignore_errors=True)
    return None


def _block(scene, line, info: dict, cache_hit: bool) -> dict:
    return {"sceneId": scene.id, "narrationId": line.id, "text": line.text,
            "audioPath": f"audio/{line.id}/narration.wav",
            "sampleRate": info["sampleRate"], "channels": info["channels"],
            "sampleCount": info["sampleCount"], "durationSeconds": info["durationSeconds"],
            "device": info["device"], "voiceId": info["voiceId"], "speed": info["speed"],
            "synthesisMs": info["timingsMs"]["phonemizationAndSynthesis"], "cacheHit": cache_hit}
