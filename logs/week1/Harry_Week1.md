# Harry - Week 1 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 7, 2026  
**Focus:** Project foundation and a working local CPU text-to-speech module

## Contribution to the capstone

Completed the first runnable narration module for the Level 1 video pipeline.
It accepts an English text file, generates speech locally using Kokoro on the
CPU, and produces an audio file with measured duration and generation metadata.
This gives the team a working audio component to connect to script generation
and, later, the video timeline and renderer.

The module fits into the planned pipeline as follows:

```text
Topic -> Script and scene plan -> TTS narration -> Timeline and visuals -> Final video
                                ^ Completed foundation
```

## Completed work

### Project setup and reproducibility

- Established the initial project structure in the local `main` working tree.
- Created a Python 3.11 virtual environment and installed the TTS dependencies.
- Added direct dependency requirements and a lock file containing all 94
  installed package entries from the validated environment.
- Added a `doctor` command to check Python, model libraries, and the English
  pronunciation components before synthesis.
- Configured Git to ignore the virtual environment, downloaded models,
  generated audio, local caches, credentials, and operating-system files.
- Added English setup instructions, a usage guide, a verification record,
  sample texts, and this individual progress log.

### Local text-to-speech implementation

- Implemented a command-line interface that reads UTF-8 English text files.
- Integrated Kokoro 0.9.4 with the pinned `hexgrad/Kokoro-82M` model revision
  `f3ff3571791e39611d31c381e3a41a3af07b4987`.
- Fixed the initial configuration to American English, the `af_heart` voice,
  and CPU inference. The default speech speed is 1.0, with two CPU threads.
- Supported offline synthesis after the initial model download.
- Collected every generated audio chunk in order, including automatic
  multi-chunk output for long paragraphs.
- Resampled the model's native 24 kHz output to 48 kHz, mono, PCM 16-bit WAV.
- Read the saved WAV back to verify its format, sample count, and valid audio.

### Output contract and error handling

Each successful run creates a separate directory containing:

| File | Purpose |
| --- | --- |
| `narration.wav` | Speech audio for future video integration |
| `audio-info.json` | Actual duration, sample rate/count, chunks, model configuration, environment, and timings |
| `input.txt` | A snapshot of the narration used for that run |

The duration is calculated from the actual saved audio:

```text
durationSeconds = sampleCount / sampleRate
```

The module rejects empty or unsupported text, invalid settings, missing
pronunciations, oversized phoneme chunks, and invalid audio. Existing output
directories are not overwritten. Failed synthesis does not publish a completed
run or a misleading success report.

## Validation results

The implementation was tested on an Apple Silicon Mac running macOS 15.1 and
Python 3.11.17. The following results came from real CPU synthesis:

| Test input | Audio duration | Chunks | Result |
| --- | ---: | ---: | --- |
| Standard introduction | 23.000 seconds | 1 | Generated successfully in a fresh environment |
| Technical abbreviations | 19.175 seconds | 1 | Generated successfully offline |
| Long paragraph | 73.600 seconds | 3 | All chunks retained; chunk metadata includes the final sentence |
| Harry's custom text | 4.450 seconds | 1 | Harry ran the module with his own text and confirmed it worked |

Additional checks completed:

- **20 automated unit tests passed**, covering concatenation, true resampling,
  duration and pitch preservation, invalid input/audio, phoneme limits, failure
  cleanup, and protection of existing outputs.
- **Six command-line failure scenarios passed**: empty input, missing file,
  non-English input, invalid speed, missing offline cache, and an existing
  output directory.
- A completely new Python environment was installed from the lock file.
  All 94 package entries matched, `pip check` and `doctor` passed, and the new
  environment generated the 23-second sample using cached models offline.
- Independent WAV checks confirmed 48 kHz mono PCM audio, accurate durations,
  and complete text coverage in the recorded chunk metadata.

## Current scope and remaining work

The standalone TTS module and its local setup are working. This is the audio
foundation of the project; script generation, scene-level orchestration,
subtitle timing, visual rendering, final MP4 assembly, and the website still
need to be implemented or integrated by the team.

Model chunks are not sentence-aligned subtitle timings. The next integration
step is to agree on the script/scene input contract and associate generated
audio with `sceneId` and `narrationId` values.

Harry's custom-input test confirms that the module is usable with new text.
A systematic listening review of pronunciation, abbreviations, and long-text
transitions is still pending. Installation and synthesis on another teammate's
computer also remain to be verified; the clean-environment test used the same Mac.

At the time of this update, the implementation and documentation are local
working-tree changes on `main`; they have not been committed or pushed.

## How to run

From the repository root, after setup:

```bash
source .venv/bin/activate
python -m capstone_tts doctor
python -m capstone_tts synthesize --text examples/my-text.txt --output-dir runs/harry-week1-test --offline
python -m unittest discover -s tests -v
```

Use a new output directory for each run. For a fresh clone, use the standard
example `examples/demo.txt` included with the module, or create your own UTF-8 text file.
Omit `--offline` on the first synthesis so the model can be downloaded.

Related documentation: [README](../../README.md),
[TTS usage guide](../../docs/TTS_GUIDE.md),
[verification record](../../docs/TTS_VERIFICATION.md), and
[team week-one plan](../../docs/WEEK_01_PLAN.md).
