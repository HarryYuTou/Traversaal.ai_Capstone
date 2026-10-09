# TTS Reproduction on Windows - October 8, 2026

Charles reproduced Harry's local CPU TTS module on a second computer running a
different operating system. No code changes were needed. This record covers the
TTS module only, not the full video pipeline.

## Environment

- Windows 11 Home 10.0.26200, AMD Ryzen 7 5800HS, 15.4 GB RAM.
- Python 3.11.9 from the Python install manager, in a project `.venv`.
- Dependencies from `requirements.lock.txt`; PyTorch reports `2.8.0+cpu`.

## Commands

Run from the repository folder in PowerShell:

```powershell
pymanager install 3.11
& "$env:LOCALAPPDATA\Python\pythoncore-3.11-64\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m capstone_tts doctor
.venv\Scripts\python.exe -m capstone_tts synthesize --text examples/demo.txt --output-dir runs/charles-windows-demo
.venv\Scripts\python.exe -m capstone_tts synthesize --text examples/long.txt --output-dir runs/charles-windows-long --offline
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Results

| Check | Windows | Mac record (`TTS_VERIFICATION.md`) |
| --- | --- | --- |
| Install | Completed in 7.2 minutes; `pip check` found no broken requirements | Completed; `pip check` passed |
| `doctor` | `ok`: Python 3.11.9, AMD64, CPU, English phonemizer ok | `ok` |
| Unit tests | 20/20 passed | 20/20 passed |
| `demo.txt` | 23.000 s, 1,104,000 samples, 1 chunk | 23.000 s, 1,104,000 samples, 1 chunk |
| `long.txt`, offline | 73.600 s, 3,532,800 samples, 3 chunks | 73.600 s, 3,532,800 samples, 3 chunks |

Both WAV files were read back with Python's `wave` module: 48,000 Hz, mono,
16-bit, and the frame count matches `sampleCount` in `audio-info.json`.

Timings from `audio-info.json`, with the default two CPU threads:

| Run | Initialization | Text processing and synthesis |
| --- | ---: | ---: |
| `demo.txt`, first run including model download | 84.3 s | 14.3 s |
| `long.txt`, cached model, offline | 18.6 s | 49.7 s |

Synthesis took about 3.5 to 3.8 times as long as on the Apple Silicon Mac
(4.1 s and 13.2 s), but it is still faster than real time: 73.6 seconds of
audio took 49.7 seconds.

## Differences from the Mac setup

- pip installed two Windows-only packages that are not in the lock file:
  `colorama 0.4.6` and `win32-setctime 1.2.0`. They are platform dependencies of
  packages already in the lock file.
- Python came from the Python install manager instead of Homebrew. It provided
  3.11.9; the Mac used 3.11.17.
- The same upstream PyTorch warnings appear (RNN dropout and `weight_norm`).

## Still pending

- Listening review of the Windows output, as on the Mac.
- More than two CPU threads has not been tried.
