# TTS Verification - October 7, 2026

Local automated acceptance checks passed. Harry also generated speech from his
own text and confirmed that it worked. A systematic listening review and
reproduction on another teammate's computer remain pending.
This record covers the local CPU TTS module, not the full video project.

## Environment

- Apple Silicon (`arm64`), macOS 15.1, Python 3.11.17.
- Kokoro 0.9.4, Misaki 0.9.4, PyTorch 2.8.0, Transformers 4.51.3.
- NumPy 2.2.6, SciPy 1.15.3, SoundFile 0.13.1.
- spaCy 3.8.16 / en_core_web_sm 3.8.0.
- Model: `hexgrad/Kokoro-82M`, revision `f3ff3571791e39611d31c381e3a41a3af07b4987`.
- Fixed American English voice `af_heart`, `speed=1.0`, two CPU threads.
- Model, configuration, and voice files total 327,738,002 bytes, stored in the ignored local `.cache/` directory.

## Real synthesis

| Example | Output directory | Audio duration | Chunks | Initialization | Text processing and synthesis | Output samples |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Standard introduction, fresh environment | `runs/demo-verified/` | 23.000 s | 1 | 3.362 s | 4.057 s | 1,104,000 |
| Technical abbreviations | `runs/acronyms/` | 19.175 s | 1 | 3.755 s | 4.030 s | 920,400 |
| Long paragraph | `runs/long/` | 73.600 s | 3 | 3.473 s | 13.157 s | 3,532,800 |

All three rows are real Kokoro inference results. Timings come from each run's
`audio-info.json`. Initialization includes dependency imports, cache lookup,
and model loading. All three runs reused downloaded model files, so these
initialization values do not measure a first download. Function timings exclude
Python command startup and final JSON publication. These measurements represent
a small set of examples on one machine, not a cross-platform performance guarantee.

The first download and synthesis used a shorter introduction: 19.575 seconds of
audio, 10.695 seconds of initialization including download, and 3.158 seconds of
text processing and synthesis. That development result remains in `runs/demo/`.
The final `examples/demo.txt` adds a sentence; its 23-second recording is in
`runs/demo-verified/`.

Each of the three final samples was independently read with Python's standard
`wave` library to confirm:

- 48,000 Hz, mono, PCM 16-bit, with the WAV sample count exactly matching the JSON report.
- `durationSeconds = sampleCount / sampleRate`.
- The output sample count equals twice the sum of all native chunk sample counts, following real 24 kHz to 48 kHz resampling.
- Concatenated chunk text matches the input snapshot when whitespace is ignored.
- The long example has three chunks, with the last chunk retaining the final sentence:
  `This is the final sentence of the long paragraph test.`

These checks establish data and text coverage. They do not certify perceptual
quality, phoneme accuracy, or abbreviation pronunciation.

## Automated tests and failure paths

Executed from the completed repository:

```bash
python -m unittest discover -s tests -v
```

Result: **20/20 passed**. Unit tests use synthetic audio and model test doubles;
they do not download or invoke the real model. Coverage includes:

- All chunks retained in order, with duration and pitch preserved through resampling.
- Odd sample counts, empty results, None, NaN, Inf, incorrect channel shape, and entirely silent audio.
- Model initialization, later-chunk, and file-write failures without a completed output directory.
- Existing outputs preserved; input, speed, and thread settings checked before model loading.
- The 510/511 phoneme boundary, missing pronunciation in a later paragraph, punctuation, and UTF-8 BOM handling.

Six failure scenarios were also exercised through the command-line interface:
empty text, a missing input file, non-English text, invalid speed, missing offline
cache, and an existing output directory. Each returned exit code 1. The first
five produced no completed output directory, and the existing WAV's SHA-256
remained unchanged after the overwrite attempt.

## Clean environment reproduction on the same Mac

A separate Python 3.11 environment was created at
`/private/tmp/capstone-tts-clean-check` and installed from `requirements.lock.txt`:

1. Installation completed and `pip check` reported no dependency conflicts.
2. All 94 entries from `pip freeze --all` exactly matched the lock file.
3. `doctor` passed, including the actual English pronunciation component check.
4. The final demo was synthesized with `--offline` using cached model files, producing the 23-second recording in the table.
5. Its audio and report were copied unchanged to `runs/demo-verified/` in the repository.

This verifies a fresh environment on the same Mac. It does not establish
reproduction by a second team member or on another operating system.
Other members can run the following on their own machines:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip check
python -m capstone_tts doctor
python -m capstone_tts synthesize --text examples/demo.txt --output-dir runs/reproduction
python -m capstone_tts synthesize --text examples/long.txt --output-dir runs/reproduction-long --offline
python -m unittest discover -s tests -v
```

See the README for Python and Homebrew prerequisites. Choose a new output
directory if the requested one already exists.

## User smoke test

Harry created `examples/my-text.txt`, generated `runs/my-text-01/narration.wav`,
and confirmed that the custom-text workflow worked. The report records CPU inference
and one chunk. An independent WAV read confirms 4.450 seconds of 48 kHz mono audio. This is a successful custom-input smoke test; it does not replace the
systematic listening checks below.

## Remaining human review

| Item | Status | How to complete |
| --- | --- | --- |
| Naturalness and clear opening/ending of the standard introduction | Pending | Play `runs/demo-verified/narration.wav` |
| Pronunciation of AI, CPU, API, DNS, and HTTPS | Pending | Play `runs/acronyms/narration.wav` and revise the narration if necessary |
| Long-paragraph transitions and the final sentence | Pending | Play `runs/long/narration.wav` |
| Reproduction on another teammate's computer | Pending | Clone, install, generate speech, and record the environment and results |

Each generated report initializes `listeningReview` to `pending`; the program
does not claim that someone has listened. The current upstream model emits
PyTorch RNN dropout and weight_norm deprecation warnings; all recorded
synthesis runs completed normally.
LLM generation, scene interfaces, subtitle timing, visual rendering, and the
website remain future integration work.
