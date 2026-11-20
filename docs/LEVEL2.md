# Level 2: Seedance Fast full video

New Seedance jobs generate **every visual scene**, from the first frame to the
last, with **Doubao-Seedance-2.0-fast**. The exact model ID is
`doubao-seedance-2-0-fast-260128`, through
`https://ark.cn-beijing.volces.com/api/v3`. There is no alternate video model or
animation fallback. Narration, captions and optional music are added locally.
The separate **Animated explanations** mode retains its existing behavior.

## Setup and settings

1. Enable this exact model in Ark and fund the account.
2. Put `ARK_API_KEY` in the project's ignored `.env`. Never put credentials in
   frontend code, a `VITE_*` variable, a commit or a screenshot.
3. Install the Python environment and renderer dependencies. `httpx` is already
   pinned in `requirements.lock.txt`. Seedance job locking supports macOS/Linux.

```sh
npm --prefix renderer ci
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m capstone_web
```

Choose **Seedance Fast · full video** under **Visuals**. Enter a topic or choose
**Try a sample**.

| Setting | Behavior |
| --- | --- |
| Target length | Desired final duration, 30 seconds to 10 minutes. Actual duration follows measured narration. The authored sample is fixed at about 30 seconds. |
| Video quality | 480p (default) or 720p for both model requests and final export. Output is 854 × 480 or 1280 × 720. |
| Background music | Optional local soundtrack under narration. |
| Review the script | Optional review of custom-topic narration before speech and video generation. |

There is no separate generated-footage limit, Quick draft, animation style or
minimum-duration toggle in Seedance mode. Switching back to Animated explanations
restores its controls and the form's animation settings. New-topic scripts and
shot directions use Claude; the authored sample needs no Claude request.

## Sample and preparation

Generate an approximately 30-second sample (incurs Ark charges):

```sh
.venv/bin/python -m capstone_video --out runs/my-full-seedance-sample --resolution 480p
```

Alternatively, add `--prepare-only` to create real local speech, subtitles, the
original timeline and a full-coverage shot plan **without contacting Ark or
rendering**. Then continue that same output directory with `--resume`:

```sh
.venv/bin/python -m capstone_video --out runs/my-full-seedance-preview --resolution 480p --prepare-only
.venv/bin/python -m capstone_video --out runs/my-full-seedance-preview --resume
```

Choose a fresh directory for each new job. Resume uses saved settings; changing
CLI resolution does not change an existing job. The completed video is
`<out>/output/video.mp4`. Local `runs/` artifacts are ignored by Git.

## M1: provider and cost controls

The provider supports preflight, submission, polling and download. Requests are
silent 16:9 text-to-video at 480p or 720p. A conflicting `ARK_VIDEO_MODEL` is rejected
before a request. Completed tasks must report the exact Fast model to be accepted.
Signed media URLs use a separate HTTP client so storage hosts never receive the
API credential. Downloads are bounded, atomic and copied locally immediately.

New requests set `watermark: false`, using the official
[watermark parameter](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh).
Resuming a previously watermarked clip preserves it; it does not remove embedded
watermarks or submit a replacement.

Price reference checked 2026-11-19: Fast without video input costs **CNY 37 per
million completion tokens**. Official 16:9 examples estimate CNY 1.86 per 5 seconds
at 480p and CNY 4.00 at 720p. The form estimates the first generation from selected
duration and quality. A nominal minute therefore estimates CNY 22.32 / 48.00.
Actual narration length, per-shot whole-second rounding and four-second minimum
requests can increase submitted footage beyond the final video's length.
Manual retries may add usage. These are estimates, not fixed prices or spending
caps; the Ark bill controls. Missing usage yields unavailable cost, not zero.

There are no automatic POST retries. Each shot has at most two submission
attempts, with the second requiring explicit Resume after a definite failure.
The internal retry allowance is derived from all planned shots, rather than an
independent user-entered seconds limit that could leave part of the video blank.
Local download or render failures reuse successful tasks and clips.

Sources: [official model list](https://docs.volcengine.com/docs/ark/model-list),
[video generation tutorial](https://docs.volcengine.com/docs/ark/video-generation-tutorial),
[official model prices](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh).

## M2: continuous footage and composition

Script review and narration finish before any video request. The original
measured timeline is preserved in `video/timeline.base.json`. Full-video
composition absorbs former title and chapter-card intervals into generated
scenes, preserving all absolute speech and caption timing. There are no separate
animated cards, diagrams, progress bars or scene backgrounds in the final video.
Quotes use normal captions. The original animation timeline is not modified.

The director must provide footage for every scene and slot, including concepts
that were previously protected as exact diagrams in hybrid mode. Hidden mechanisms
can use stylized scientific cutaways; exact numbers and labels remain in narration
and captions. All batches share one visual style. A missing scene or frame gap
stops the job before paid requests rather than falling back to animation.

Scenes are split into balanced slots no longer than ten seconds. Provider request
durations round up to whole seconds with a four-second minimum. Clips are decoded,
stripped of provider audio, converted to the 30 fps timeline and trimmed to exact
frames. Short or corrupt clips fail validation; they are not stretched or looped.
The final composition verifies continuous generated coverage from frame zero to
the end. Video quality controls both source requests and final MP4 dimensions;
caption typography scales proportionally at each output size.

## M3: persistence and recovery

New web requests use `visualMode`, `durationSeconds` and `videoResolution`.
Animation-only settings cannot reduce Seedance export resolution or enable
duration extension. A stale browser submitting `maxGeneratedSeconds` receives a
refresh instruction before generation begins. `storyboarding` and
`generating_video` stages expose real clip progress. Completed results include
the model, resolution, full-coverage marker, clip count and usage-based cost.

Only the owner can resume a failed job through `POST /api/jobs/:id/resume` with
an empty object. The job ID and output directory are retained. Active jobs reject
duplicate resume requests, and process locking prevents concurrent submissions.

| File in a job's `output/` | Purpose |
| --- | --- |
| `pipeline-checkpoint.json` | Hashes of request settings, speech, subtitles and original timeline |
| `video-plan.json` | Fixed model, prompts, seeds, frame coverage, request durations and derived retry allowance |
| `video-planning.json` | Custom-topic director attempts and estimated Claude cost |
| `video-generation.json` | Submission intents, task IDs, states, attempts, usage and verified media hashes |
| `video/generated/` | Original downloads and frame-aligned render clips |
| `video/timeline.json` | Complete generated-video composition with unchanged narration timing |

Recovery rules:

- Verified clips are reused, including offline; saved active task IDs are polled.
  Download and render failures do not submit replacement tasks.
- Server restart alone never starts paid work. Definite failed shots require
  explicit Resume and allow at most one retry. Provider expiry can prevent late
  recovery of files that have not yet been downloaded.
- Submission intent is saved before POST. If the response/task ID is lost, the
  outcome is ambiguous and resubmission is disabled. Inspect Ark task history and
  the local manifest; automatic reconciliation/import is not implemented.
- Changed request, narration, plan or media is detected. Corrupt normalized media
  can be regenerated from a saved task without another POST.
- Failures before the finalized narration checkpoint cannot resume in place;
  no Seedance request has occurred at that point. Partial renders are preserved
  as `.interrupted.mp4` before local rendering resumes.

New jobs carry `pipelineVersion: 2` and video-plan schema version `2`. Saved jobs
without this marker retain their original hybrid behavior, quality settings and
seconds cap. They are never silently upgraded or regenerated. Start a **new job**
to use full-video mode; existing completed videos remain available.

## Verification record

The earlier hybrid sample, **Why a Cold Glass Gets Wet**, completed via the real
Ark API from the user's terminal. Its saved render report measures 30.635 seconds,
with four requests of 9, 9, 6 and 6 seconds and estimated video cost CNY 11.2107.
The user reported good visual results. That original sample had visible
watermarks and verifies the previous hybrid pipeline, not this full-video change.
It remains at `runs/level2-seedance-30s/output/video.mp4` on this machine.

Full-video verification covers per-frame coverage, inclusion of formerly protected
scenes, 10-minute planning without the old cap, shared style across director
batches, request normalization, bounded retries and render recovery without
repeat submissions. Frontend tests check one length/quality selector, matching
requests and unchanged animation controls. Renderer tests reject cards, frame
gaps, animation fallback and mismatched output quality.

Current checks (2026-11-19):

| Check | Result |
| --- | --- |
| Python suite | 412 passed; 12 HTTP tests blocked by sandbox `socket.bind` permissions |
| Seedance coverage | 31 tests, including 8 new full-video tests, passed within the suite |
| Renderer | 193 tests passed; TypeScript check passed |
| Frontend | 29 workflow tests passed; production build passed |
| Real local sample preparation | Passed: 30.633-second narration timeline, 5 shots, 33 requested seconds, fixed Fast model; no Ark request |

The full-video preparation is saved at `runs/level2-full-video-preview`. It is a
prepared job, not a completed MP4. Resume would start paid video generation.

No paid Ark request is made by these tests. A new full-video MP4 and live browser
playback still need acceptance testing in an environment with localhost and API
access; passing tests does not establish generated content quality.

```sh
.venv/bin/python -m unittest discover -s tests
npm --prefix renderer run typecheck
npm --prefix renderer run test:motion
npm --prefix web test
npm --prefix web run build
```
