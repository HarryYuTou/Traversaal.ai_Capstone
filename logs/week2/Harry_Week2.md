# Harry - Week 2 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 12, 2026  
**Branch:** `Frontend-v1`  
**Focus:** A desktop web workspace connected to the existing video pipeline

## Contribution to the capstone

Completed the first browser-based workflow for creating an explainer video:

```text
Fill in a brief -> Submit generation -> Follow the stages -> Play or download the video
```

The project already had command-line script planning, optional script review,
Kokoro CPU narration, timeline construction, and Remotion video rendering.
This contribution adds the website and the local API needed to use those
components from a browser. It reuses the existing pipeline rather than
reimplementing the team's script, speech, or rendering modules.

## Completed work

### Desktop web workspace

- Created `web/` as a separate React, TypeScript, and Vite project. The
  website and the existing `renderer/` Remotion project keep separate
  dependencies and build commands.
- Added a brief form for the topic, target audience, and target length,
  covering 30 seconds to ten minutes.
- Added video settings for Light or Night theme, background music, optional
  script review, and a 540p quick draft or full 1080p output.
- Added input validation, clear field errors, and a submission guard to
  prevent repeated clicks from creating duplicate requests.
- Added setup checks and guidance when a required dependency or Claude
  credential is missing. Credentials remain on the Python server.
- Added an explicit **Try a sample** mode that uses the existing sample
  script and performs real narration and rendering without a Claude call.

### Generation progress and results

- Connected the interface to real job states: queued, running, completed,
  and failed. Running jobs report planning, optional review, narration,
  and rendering stages.
- Displayed actual completed-line counts during narration. The interface
  does not invent an overall completion percentage.
- Added browser video playback, seeking, MP4 download, and WebVTT subtitle
  download after a successful render.
- Displayed the completed video's title, measured duration, dimensions,
  and file size. The pre-generation illustration is labeled as a preview,
  not presented as an actual rendered frame.
- Saved the brief and latest job ID in browser local storage, allowing a
  page refresh to reconnect to the same task.
- Added connection recovery, failed-job messages, and an explicit retry
  using the original brief. A retry creates a new job.
- Fixed stale connection and readiness messages so a missing task or an
  unsuccessful service check does not leave a misleading status visible.

### Local API and pipeline integration

- Added `capstone_web/`, using Python's standard-library HTTP server to
  serve the built website and expose health, job, and media endpoints.
- Isolated frontend HTTP calls and types in `web/src/api.ts`, providing
  one integration boundary for future backend changes.
- Added persistent job records under `runs/web/<job-id>/`, with a serial
  worker that invokes the existing pipeline in a separate process.
- Preserved requests, status, output files, and local diagnostic logs for
  each job. Failed or interrupted jobs are not automatically resubmitted.
- Required successful worker completion before publishing a video result;
  a partial MP4 on disk does not count as success.
- Added worker cleanup and storage-error handling so a failed task does
  not leave an orphan process or prevent later queued work from running.
- Restricted the service to `127.0.0.1`, validated requests, and limited
  downloads to approved media files from completed jobs. Byte-range
  support allows seeking in the generated video.

### Documentation and handoff

- Added `docs/WEB_STUDIO.md` with installation, startup, development,
  API contracts, job lifecycle, troubleshooting, and verification details.
- Updated the README to describe the web workspace and distinguish it
  from the standalone TTS module and the video renderer.
- Kept documentation and interface text in English, following the
  project's language convention.

## Validation results

### Automated checks

| Check | Result |
| --- | --- |
| Complete Python test suite | 147 tests passed, including 24 new web/API tests |
| Frontend component tests | 8 Vitest/jsdom tests passed with mocked API-client methods |
| Frontend production build | Type checking and Vite build passed |
| Existing Remotion project | TypeScript check passed |
| Change formatting | `git diff --check` passed |

The new tests cover request validation, readiness, job persistence, queue
execution, worker failures, media access and ranges, form behavior, duplicate
submission prevention, sample mode, restoration, retries, and connection
recovery. Mocked checks do not make paid Claude requests.

### Real desktop-browser workflow

Submitted **Try a sample** from the website and completed real local CPU
narration and Remotion rendering. The sample uses
`fixtures/scene-plan.valid.json`; it is not a prerecorded video.

| Measurement | Recorded result |
| --- | --- |
| Job ID | `350c75c6b36d4d27925532beacc28434` |
| Video title | From an Address to a Web Page |
| Resolution | 1920 × 1080 |
| Frame rate | 30 fps |
| Actual duration | 87.509 seconds |
| MP4 size | 11,822,874 bytes |
| Render time | 60.6 seconds, excluding earlier pipeline stages |
| Settings | Light theme, background music, full render |

Verified browser playback and seeking, MP4 and subtitle download initiation,
and recovery of the completed job after a page reload and server restart.
The generated files remain in the ignored local run directory:

```text
runs/web/350c75c6b36d4d27925532beacc28434/output/
```

## Current scope and remaining work

The desktop web workflow is working locally. No Claude credential was
configured during this implementation, so a new custom topic has not yet
been tested through a live Claude request from the website. The integration
and missing-credential behavior were tested; a real topic run remains the
next acceptance check after configuring the server credential.

The sample verification was not a full listening, factual, or editorial
review of the generated video. The web integration was verified on the
local macOS environment; cross-platform verification remains pending.

The agreed focus is the desktop website. Further mobile adaptation and
mobile acceptance testing are deferred. Accounts, a history browser,
multi-user hosting, public deployment, per-job cancellation, and in-place
resume are outside this first version. Restarting the server preserves
completed jobs but marks unfinished jobs as failed instead of silently
repeating generation.

At the time of this update, the implementation and documentation are local
working-tree changes on `Frontend-v1`; they have not been committed or pushed.

## How to run

From the repository root, with Python and renderer dependencies installed:

```bash
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m capstone_web
```

Open [Traversaal Studio](http://127.0.0.1:8000). Keep the server running while
generating or accessing media. Choose **Try a sample** to test without a
Claude credential. For **Your topic**, configure `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN` in the server environment or the ignored project
`.env` file; custom-topic generation incurs API usage.

For frontend development, keep the Python server running and use
`npm --prefix web run dev` in another terminal, then open
`http://127.0.0.1:5173`.

Related documentation: [README](../../README.md),
[web studio guide](../../docs/WEB_STUDIO.md),
[script planner guide](../../docs/SCRIPT_GUIDE.md), and
[video renderer guide](../../docs/RENDERER_GUIDE.md).
