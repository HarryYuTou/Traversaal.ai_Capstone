# Week 1: Local English Narration

This module turns narration text into real speech and provides accurate audio
duration for the rest of the team. It reads a text file and produces
`narration.wav` and `audio-info.json`. It uses Kokoro with the fixed American
English voice `af_heart` and runs inference on the local CPU. Video, subtitles,
LLM script generation, and the website will be connected in later work.

## 1. Run on the current development machine

Open Terminal, enter the repository, and activate the installed project environment:

```bash
cd ~/Desktop/Traversaal.ai_Capstone
source .venv/bin/activate
python -m capstone_tts doctor
```

An output of `"status": "ok"` means that the dependencies and English
pronunciation components are available. This check does not generate speech.
To generate a new recording:

```bash
python -m capstone_tts synthesize --text examples/demo.txt --output-dir runs/my-first-run --offline
```

Use `--offline` after the model has been downloaded on this machine. On another
computer's first run, omit this option to allow the model download. Use a new
output directory each time, such as `runs/my-second-run`, to preserve prior results.

Open the output directory in Finder and play `narration.wav`. Then open
`audio-info.json` in a text editor and check:

- `durationSeconds`: the actual audio duration in seconds.
- `sampleRate`: should be 48000.
- `channels`: should be 1 for mono audio.
- `chunkCount`: the number of generated chunks, all joined in their original order.
- `device`: should be `cpu`.
- `timingsMs`: initialization, synthesis, and file-processing timings in milliseconds.

## 2. Use your own text

Create a UTF-8 `.txt` file in `examples/` and write English narration in it.
The input is plain text. For example, if the filename is `my-topic.txt`:

```bash
python -m capstone_tts synthesize --text examples/my-topic.txt --output-dir runs/my-topic --offline
```

Start with around 50-80 English words. The actual duration depends on the text
and speech speed; use the generated report as the measurement. The default speed
is `1.0`. Append `--speed 0.9` or `--speed 1.1` to adjust it.
This version supports English input up to 20,000 characters. Listen to
abbreviations and proper names; rewrite them as separated letters or full words
if needed.

## 3. Reproduce the setup on a teammate's computer

Clone the repository and follow the README from the repository root: install
Python 3.11, create `.venv`, install `requirements.lock.txt`, then run `doctor`
and a sample synthesis command. Model files are not stored in GitHub; each
person downloads them to their own `.cache/` on first use.

The validated platform is Apple Silicon with macOS 15.1. Installation differences
on Windows, Linux, and Intel Macs have not yet been tested. Record actual results;
providing setup instructions alone does not complete independent reproduction.
The complete dependency environment is larger than the model itself, so allow
several GB of disk space for the Python inference environment.

Record the operating system, Python version, installation result, synthesis
time, and audio duration. Listen to normal sentences, abbreviations, and the
last sentence of the long example, then add the results to the verification record.

## 4. Implementation to understand and explain

1. Read the text and reject empty input, invalid speech speed, and existing output directories.
2. Load the pinned model and voice, explicitly using the CPU.
3. Convert English to phonemes and split it into supported chunks. Reject missing pronunciations or oversized phoneme chunks.
4. Generate every chunk and concatenate them in the original order.
5. Resample the native 24 kHz audio to 48 kHz. The sample count doubles while duration stays the same.
6. Save the WAV and read it back to check actual sample count, channels, format, and valid audio before writing the JSON report.

The key formula is `duration in seconds = sample count / sample rate`.
The video module should use measured duration instead of estimating it from word count.

`engine.py` handles the model, `audio.py` handles audio and reports, and
`__main__.py` provides the command-line interface. The current `chunks` describe
model output chunks; they are not an accurate subtitle timeline.

## 5. Deliverables and next steps

- Code, examples, dependency lock files, instructions, and automated tests are ready for version control.
- `runs/`, `.cache/`, `.venv/`, operating-system icons, and credential files are ignored by Git.
- See [TTS verification](TTS_VERIFICATION.md) for local results. Record listening reviews and teammate reproduction honestly.
- The foundation is being built on `main`. Use feature branches and pull requests when team members begin parallel work.
- Once the team agrees on scene interfaces, extend synthesis to associate audio with `sceneId` and `narrationId`, then integrate with the timeline.

The [full team week-one plan](WEEK_01_PLAN.md) remains a planning document.
The completed individual deliverable is the standalone TTS foundation described here.
