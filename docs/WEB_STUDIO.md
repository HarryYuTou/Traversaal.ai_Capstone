# Traversaal Studio: Local Web Workspace

Frontend-v1 connects a browser workspace to the existing explainer-video
pipeline. Enter a topic, audience, and target length, follow the generation
stages, then play or download the finished MP4. A built-in sample provides a
way to exercise real narration and rendering without making a Claude request.

This version runs on one computer at `127.0.0.1`. Each person signs in with a
local account, and a **History** page lists every video that account has made.
Accounts and jobs are stored on the computer running the server. There is no
public deployment configuration yet; see [Accounts and history](#accounts-and-history)
for what would change before hosting it.

## Install and start

Run these commands from the repository root on macOS with Python 3.11 and
Node.js available. If `.venv` already exists, use that environment instead of
creating it again.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm --prefix renderer ci
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m capstone_web
```

Open [Traversaal Studio](http://127.0.0.1:8000). Keep the server terminal open
while a job is running. Press Ctrl+C to stop it. The built site is served from
`web/dist`; rebuild after changing the frontend. An alternative local server
port can be selected with `--port`, for example
`.venv/bin/python -m capstone_web --port 8001`.

The Python lock file records the previously tested macOS environment. This
guide does not claim that the web server's process management has been
verified on Windows. The standalone TTS Windows reproduction is a separate
record in [TTS_WINDOWS_REPRODUCTION.md](TTS_WINDOWS_REPRODUCTION.md).

For **Your topic**, configure `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` in
the server environment or the repository's ignored `.env` file. Credentials
are read by Python and are never sent to the frontend. API charges apply when
generating a new topic, including its optional review. Keep credentials out
of screenshots, shared logs, and commits.

For **Try a sample**, no Claude credential or Claude request is needed. It
uses `fixtures/scene-plan.valid.json`, then runs the same real Kokoro CPU
narration, timeline construction, and Remotion render. It is not a prerecorded
video or a simulated generation.

The first narration may download the pinned Kokoro model and voice into
`.cache/huggingface`; the first render may download Remotion's browser.
Once the expected voice files are cached, the worker selects offline TTS
automatically. The setup dialog checks installed dependencies, the sample,
model-cache presence, and credential presence without making network calls.
These checks do not verify API credit, credential validity, or successful
model inference. An uncached voice model is advisory and does not prevent
starting a job that can download it.

## Make a video

1. Choose **Your topic** or **Try a sample**. A new topic accepts 1–500
   characters and an audience description of 1–200 characters.
2. For a topic, select a target from 30 seconds to ten minutes. Outputs use
   English narration; plans over three minutes are created chapter by chapter.
   The final length is determined by real speech, pauses, and title cards.
3. Open **Video settings** to choose Light or Night, background music,
   optional script review, and a 540p quick draft. Full output is 1080p.
   Sample generation uses the fixed sample script and skips planning/review.
4. Select **Generate video** or **Generate sample video**. Setup problems
   appear before a job is accepted. The workspace shows the actual stage and,
   during narration, the number of completed lines.
5. When generation succeeds, play the video, download the MP4, or download
   WebVTT subtitles. Review facts, pronunciation, and layout before sharing.

The image shown before completion is an illustrative preview. It is not a
live frame from the renderer. The workspace reports stages rather than an
estimated overall completion percentage.

Refreshing the page reconnects to the most recently remembered job for the
signed-in account in that browser. The brief and job ID are stored in
browser local storage under the account's ID; task status and media remain
on the server's disk. Closing the browser does not
stop generation while the local server remains running. Different browser
origins, such as the development and built-site ports, have separate local
storage.

## Accounts and history

The first page asks you to sign in or create an account. A username has 3–32
letters, numbers, dots, dashes, or underscores and is not case-sensitive for
sign-in; a password has 8–128 characters. Creating an account signs you in.

- **Storage:** accounts live in `runs/web/accounts.sqlite3` (ignored by Git).
  Passwords are stored only as salted PBKDF2-HMAC-SHA256 hashes with 600,000
  iterations, using Python's standard library. No outside sign-in service is
  used.
- **Sessions:** signing in sets an `HttpOnly`, `SameSite=Strict` cookie that
  lasts 14 days. The database keeps only a SHA-256 hash of each session token.
  **Sign out** ends that browser's session; other browsers stay signed in.
  When a session ends, the next request returns the page to sign-in.
- **Ownership:** every new job records its owner's account ID. Job status,
  media, and the job list are served only to the owner. Another account's job
  ID answers exactly like a missing one (404).
- **History:** the **History** tab lists your jobs, newest first, with status,
  date, length, and any failure message. **Open** shows a job in the video
  workspace (not available for other jobs while one is being created),
  **MP4** downloads a finished video, and **Try again** submits a stopped job's
  brief as a new job. Rows refresh while a job is in progress.
- **Jobs from before accounts:** jobs saved by an earlier version have no owner
  and are not listed for anyone. Their files remain under `runs/web/`.

Anyone who can reach the server can create an account. Before hosting it
beyond `127.0.0.1`, serve it over HTTPS and add `Secure` to the session
cookie, decide who may register, and add sign-in rate limiting; none of these
are part of this version. There is no password reset: a forgotten password
needs a new account, or removal of that user from the database by whoever
runs the server.

## Job lifecycle and files

One worker runs jobs serially. The API accepts at most eight queued/running
jobs combined; the UI keeps one active job in its workspace. Each submission
gets its own ID and output directory:

```text
runs/web/<job-id>/
  job.json                # Saved request, status, stage, result, or error
  worker.log              # Local pipeline and renderer diagnostics
  output/
    scene-plan.json
    audio-manifest.json
    narration-preview.wav
    video.mp4              # video-draft.mp4 for a quick draft
    video-info.json        # video-draft-info.json for a quick draft
    thumbnail.png          # Optional; full renders only
    video/
      timeline.json
      narration.wav
      subtitles.srt
      subtitles.vtt
```

Topic runs also retain planning metadata and, if selected, review metadata
and the original script. Long plans include chapter data. See the
[script guide](SCRIPT_GUIDE.md) and [renderer guide](RENDERER_GUIDE.md) for
the underlying artifacts. All files under `runs/` are ignored by Git.

The lifecycle is `queued` → `running` → `completed` or `failed`. Running
stages are `planning`, optional `reviewing`, `narrating`, and `rendering`.
Sample runs start at narration. A job is completed only after the worker
returns successfully, including the existing renderer checks; finding an MP4
on disk is not sufficient. Partial files from a failed run are retained for
diagnosis but are not published through the media endpoints.

Stopping the server interrupts active generation. On startup, previously
queued or running jobs are marked failed rather than restarted. Completed
jobs remain available by ID. **Try again with this brief** creates a new job;
the server does not automatically resubmit failed or interrupted jobs and
incur another full generation charge. The existing planner's bounded format
repair and SDK request behavior still apply within a running job. There is
no in-place resume or per-job cancel control in this version.

## HTTP contract

`web/src/api.ts` is the frontend's single HTTP boundary. UI components use
its request and response types rather than importing pipeline details.
This is the place to adapt the frontend when a later service replaces the
local Python API.

| Method and path | Result |
| --- | --- |
| `POST /api/auth/register` | Create an account from `{username, password}` and sign in (201) |
| `POST /api/auth/login` | Sign in with `{username, password}`; sets the session cookie |
| `POST /api/auth/logout` | End this browser's session and clear the cookie |
| `GET /api/auth/me` | The signed-in account, or 401 |
| `GET /api/jobs` | `{jobs: [...]}`: the signed-in account's jobs, newest first |
| `GET /api/health` | Readiness flags, individual checks, and sample metadata |
| `POST /api/jobs` | Validate and queue a video request; return the job with HTTP 202 |
| `GET /api/jobs/<id>` | Read the saved job, stage, error, and result |
| `GET /api/jobs/<id>/files/video.mp4` | Stream a completed job's full or draft MP4 |
| `GET /api/jobs/<id>/files/video.mp4?download=1` | Download the completed MP4 |
| `GET /api/jobs/<id>/files/thumbnail.png` | Optional full-render thumbnail |
| `GET /api/jobs/<id>/files/subtitles.vtt` | Completed job's WebVTT subtitles |

A topic request has this shape:

```json
{
  "source": "topic",
  "topic": "How does GPS know where you are?",
  "audience": "Curious adults with no technical background",
  "durationSeconds": 90,
  "review": true,
  "theme": "light",
  "music": true,
  "draft": false
}
```

`topic`, `audience`, and `durationSeconds` are required. Duration must be a
whole number between 30 and 600. Defaults are `source: "topic"`,
`review: true`, `theme: "light"`, `music: true`, and `draft: false`.
Allowed themes are `light` and `night`. Unknown fields are rejected, and
requests must use JSON with a body no larger than 16,384 bytes.

For `source: "sample"`, supply the same required fields; the server replaces
them with its fixed sample values and sets `review` to false. The UI obtains
those values from `/api/health`. File uploads, reference URLs, arbitrary
output paths, and custom voices are not accepted by this API.

Every route except the four `/api/auth/` routes requires a signed-in session
and returns 401 (`not_signed_in`) without one. An account is returned as
`{id, username, createdAt}`; the password hash is never returned.

A job includes `id`, `status`, `stage`, `message`, `createdAt`, `updatedAt`,
`request`, `error`, `result`, and `owner` (the account ID). Narration can add
`lineProgress: {current, total}`. A successful result includes the title,
video/download URLs, nullable thumbnail/subtitle URLs, measured duration,
width, height, and byte count. Error responses use
`{"error":{"code":"...","message":"..."}}`.

Typical errors are invalid input (400), not signed in or wrong password
(401), disallowed host/origin (403), unknown job or artifact (404), a taken
username (409), an unfinished job's media (409), oversized request
(413), non-JSON input (415), a full queue (429), and incomplete setup (503).
Media serving supports single byte ranges for video seeking. The server
only serves allowlisted media from completed jobs; local metadata and logs
are not exposed as downloadable artifacts.

## Frontend development

`web/` is the React/TypeScript/Vite website. `renderer/` is the separate
Remotion project that produces videos. They have separate package manifests,
lock files, and dependencies; installing one does not install the other.
`capstone_web/` supplies the local API, persistent job store, and worker
adapter, using the existing `capstone_script` and `capstone_tts` modules.

Keep the Python server on port 8000 in one terminal:

```bash
.venv/bin/python -m capstone_web
```

In another terminal, start Vite:

```bash
npm --prefix web run dev
```

Open [the development workspace](http://127.0.0.1:5173). Vite proxies `/api`
to `http://127.0.0.1:8000`; the configured port is strict. This mode updates
the UI without rebuilding `web/dist`. Use the Python-served build on port
8000 to check the packaged frontend. The server intentionally binds only to
`127.0.0.1`; it is not a production server or a LAN sharing endpoint.

## Verification

Run the frontend checks and the complete Python test suite from the
repository root:

```bash
npm --prefix web run build
npm --prefix web test
.venv/bin/python -m unittest discover -s tests -v
```

Frontend tests exercise the browser UI with mocked HTTP responses. Backend
tests cover validation, readiness, persistence, serial execution, worker
failure handling, and HTTP/media behavior with isolated fixtures. These
tests do not make paid Claude calls or establish real TTS/render performance.
A passing frontend build confirms type checking and bundling, not a finished
video.

For real local verification, use **Try a sample**, wait for completion, play
the entire result, seek within it, and download the MP4 and subtitles. Record
the job ID, environment, actual duration, and any observed issues separately.
A real topic run additionally verifies Claude access and script generation;
it incurs API usage. Do not substitute mock-test results for either check.

### Frontend-v1 local verification — 2026-10-12

- On the macOS development machine, all 147 Python tests and all eight frontend
  component tests passed. The frontend production build and the existing
  Remotion project's TypeScript check also passed.
- Submitted a real sample from the desktop browser. Job
  `350c75c6b36d4d27925532beacc28434` completed local CPU narration and a full
  Light-theme render with background music: 1920 × 1080, 30 fps, 87.509 seconds,
  11,822,874 bytes. The render report recorded 60.6 seconds for rendering.
- Verified browser playback, seeking, MP4 and subtitle download initiation,
  and restoration of the completed job after a page reload and server restart.
  This was not a full listening or
  editorial review of the generated content.
- No Claude credential was configured, so custom-topic generation was not
  exercised against the live API. Its API/UI integration is covered by mocked
  tests. This delivery focuses on the desktop web workflow; mobile acceptance
  testing is deferred.

### Accounts and history check — 2026-10-16

- On macOS with Python 3.13 and Node 22, all 166 Python tests and all 19
  frontend tests passed, and the production build succeeded. The new tests
  cover password hashing, sessions, sign-in errors, ownership checks on jobs
  and media, the history list, and the sign-in and history pages.
- In a desktop browser, the built site ran against the real server code with
  a stand-in worker in place of the pipeline (Kokoro, torch, and Remotion were
  not installed on that machine). Checked: account creation, a wrong-password
  message, sign-out and sign-in, the session cookie hidden from page scripts,
  two jobs (one finished, one stopped) in History, **Open** in the workspace,
  and a second account seeing no jobs and getting 404 for the first account's
  job and video. No real video was generated in this check.

## Troubleshooting

- **Setup needed:** open the setup dialog and address the listed dependency
  or credential issue, then select **Check again**. The sample does not need
  Claude, but it still needs the real Python video dependencies and Remotion.
- **Frontend not built:** run `npm --prefix web run build`, or use the Vite
  development server with the Python API running on port 8000.
- **Connection interrupted:** leave the server running; the UI reconnects to
  the current task automatically. Reconnection does not submit another job.
- **Generation stopped:** inspect `runs/web/<job-id>/worker.log` locally.
  Fix the cause before choosing a new attempt. Partial files remain in the
  old output directory and do not become a completed video automatically.
- **The server was restarted:** queued/running jobs become failed to avoid
  silently repeating paid work. Submit a new job when ready.
- **Signed out unexpectedly:** sessions last 14 days and end on sign-out.
  Sign in again; your jobs and history are kept.
- **Forgot a password:** there is no reset. Create a new account, or ask
  whoever runs the server to remove the old one from
  `runs/web/accounts.sqlite3`.
- **Video no longer available:** the local artifact may have been moved or
  deleted. Job metadata alone cannot restore the media; create a new video.

Retain logs locally when investigating failures and check them before
sharing. They can contain prompts, generated content, and provider error
details. The website exposes a short failure message rather than raw logs.
