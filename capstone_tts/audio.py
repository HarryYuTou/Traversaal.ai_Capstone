"""Write a complete run, publishing it only after the WAV has been verified."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import tempfile
from time import perf_counter
import unicodedata

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from .engine import MODEL_ID, MODEL_REVISION, VOICE_ID, SOURCE_RATE, OUTPUT_RATE


def validate_text(text: str) -> str:
    text = text.strip()
    if not text or not any(c.isalnum() for c in text):
        raise ValueError("Input must contain spoken text, not just whitespace or punctuation.")
    if len(text) > 20_000:
        raise ValueError("This prototype accepts at most 20,000 characters per run.")
    if any(c.isalpha() and "LATIN" not in unicodedata.name(c, "") for c in text):
        raise ValueError("This first version supports English narration only.")
    return text


def write_run(*, text_path: Path, output_dir: Path, engine_factory, speed: float = 1.0,
              offline: bool = False, threads: int = 2, progress=lambda message: None):
    started = perf_counter()
    if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
        raise ValueError("Speed must be between 0.5 and 2.0.")
    if not 1 <= threads <= 16:
        raise ValueError("CPU threads must be between 1 and 16.")
    text = validate_text(text_path.read_text(encoding="utf-8-sig"))
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"Output already exists: {output_dir}. Choose a new output directory.")
    output_dir = output_dir.resolve()

    progress("Loading English speech model on CPU (first run downloads model files)...")
    init_started = perf_counter()
    engine = engine_factory()
    initialization_ms = (perf_counter() - init_started) * 1000
    synth_started = perf_counter()
    blocks, chunks = [], []
    source_count = 0
    for index, (words, block) in enumerate(engine.chunks(text, speed), start=1):
        block = np.asarray(block, dtype=np.float32)
        if block.ndim != 1 or block.size == 0 or not np.isfinite(block).all():
            raise ValueError(f"Chunk {index} contains empty, non-mono, or non-finite audio.")
        if float(np.max(np.abs(block))) == 0:
            raise ValueError(f"Chunk {index} is entirely silent.")
        blocks.append(block)
        chunks.append({"index": index, "text": words, "sourceStartSample": source_count,
                       "sourceSampleCount": int(block.size)})
        source_count += int(block.size)
        progress(f"Synthesized chunk {index}: {block.size / SOURCE_RATE:.2f} seconds")
    synthesis_ms = (perf_counter() - synth_started) * 1000
    if not blocks:
        raise ValueError("The speech engine generated no audio.")

    # Real resampling preserves duration; changing a WAV header alone does not.
    processing_started = perf_counter()
    samples = resample_poly(np.concatenate(blocks), OUTPUT_RATE // SOURCE_RATE, 1)
    peak = float(np.max(np.abs(samples)))
    if not math.isfinite(peak) or peak == 0:
        raise ValueError("Resampling produced invalid audio.")
    # Reduce only if needed to avoid PCM clipping. Do not amplify quiet speech.
    gain = min(1.0, 0.99 / peak)
    samples *= gain
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tts-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        wav_path = staging / "narration.wav"
        sf.write(wav_path, samples, OUTPUT_RATE, subtype="PCM_16")
        saved, actual_rate = sf.read(wav_path, dtype="float32")
        info = sf.info(wav_path)
        if (actual_rate != OUTPUT_RATE or info.channels != 1 or info.subtype != "PCM_16"
                or info.frames != source_count * 2 or not np.isfinite(saved).all()
                or not np.any(saved)):
            raise RuntimeError("Written WAV failed verification.")
        (staging / "input.txt").write_text(text + "\n", encoding="utf-8")
        processing_ms = (perf_counter() - processing_started) * 1000
        metadata = {
            "schemaVersion": "1.0", "status": "completed", "audioSource": "kokoro",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "inputFile": text_path.name, "inputSnapshot": "input.txt",
            "inputTextSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
            "langCode": "a", "voiceId": VOICE_ID, "device": "cpu", "speed": speed,
            "cpuThreads": threads, "offlineRequested": offline,
            "audioPath": "narration.wav", "format": "WAV", "subtype": info.subtype,
            "sampleRate": info.samplerate, "channels": info.channels,
            "sampleCount": info.frames, "durationSeconds": info.frames / info.samplerate,
            "sourceSampleRate": SOURCE_RATE, "sourceSampleCount": source_count,
            "chunkCount": len(chunks), "chunks": chunks, "appliedGain": gain,
            "peakAmplitude": float(np.max(np.abs(saved))),
            "rmsAmplitude": float(np.sqrt(np.mean(saved.astype(np.float64) ** 2))),
            "timingsMs": {
                "initializationIncludingDownloads": round(initialization_ms, 2),
                "phonemizationAndSynthesis": round(synthesis_ms, 2),
                "resampleWriteVerify": round(processing_ms, 2),
                "totalThroughAudioVerification": round((perf_counter() - started) * 1000, 2),
            },
            "environment": {"python": platform.python_version(), "os": platform.system(),
                            "osRelease": platform.release(), "architecture": platform.machine(),
                            "packages": {name: version(name) for name in
                                         ("kokoro", "misaki", "torch", "transformers", "numpy", "scipy", "soundfile", "spacy", "en-core-web-sm")}},
            "listeningReview": "pending",
        }
        (staging / "audio-info.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        # Publish the pair together. A failed synthesis never creates a completed run.
        if output_dir.exists():
            raise FileExistsError(f"Output appeared during synthesis: {output_dir}")
        staging.rename(output_dir)
    return metadata
