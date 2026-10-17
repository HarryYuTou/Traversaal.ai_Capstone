# Tong - Week 2 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 16, 2026  
**Branch:** `feat/login-history` (PR #7, awaiting Harry's review)  
**Focus:** Sign-in accounts and a per-account video history for the web studio

## Contribution to the capstone

Level 1 acceptance needs two more things: five full seven-minute videos on
non-AI topics, and login plus history on the website. I took the second one.
Harry's web studio (PR #3) could already generate, play and download a video,
but it had no accounts and remembered only the last job in one browser.

```text
Sign in -> Fill in a brief -> Follow the stages -> Play or download -> Find it again in History
^ new                                                                  ^ new
```

The work extends `capstone_web/` and `web/` without changing the script,
narration or rendering modules. It adds no new dependencies; the server side
uses only the Python standard library. I built it with Claude Code.

## Completed work

### Accounts and sessions

- New `capstone_web/accounts.py`: accounts in `runs/web/accounts.sqlite3`
  (ignored by Git), with passwords stored only as salted PBKDF2-HMAC-SHA256
  hashes (600,000 iterations).
- Sign-in sets an `HttpOnly`, `SameSite=Strict` cookie lasting 14 days. The
  database keeps only a SHA-256 hash of each session token. Sign out ends
  that browser's session.
- New routes: `POST /api/auth/register`, `POST /api/auth/login`,
  `POST /api/auth/logout` and `GET /api/auth/me`. Every other API route now
  needs a session and returns 401 without one.
- A wrong password and an unknown username get the same message, so
  usernames cannot be guessed from sign-in errors.

### Job ownership and history

- Every new job records its owner. Another account's job, video or subtitles
  answer 404, exactly like a missing job.
- New `GET /api/jobs` returns the signed-in account's jobs, newest first.
- New **History** tab: each job with its status, date, length and any failure
  message. **Open** loads it into the workspace, **MP4** downloads it and
  **Try again** resubmits a stopped job's brief. Rows refresh while a job runs.
- The browser now remembers the last job and brief per account, so two people
  sharing one browser never restore each other's work.

### Website

- New sign-in and account-creation page in the studio's existing style, with
  field checks before any request is sent.
- The header now has **Video workspace** and **History** tabs, the signed-in
  username and **Sign out**. On narrow windows the tabs move to their own row.
- `App.tsx` is now the sign-in gate; the existing workspace moved unchanged
  into `Studio.tsx`, plus new `AuthScreen.tsx`, `HistoryPanel.tsx` and
  `Brand.tsx`.

### Documentation

- `docs/WEB_STUDIO.md`: a new "Accounts and history" section, the new routes
  in the HTTP contract, troubleshooting for sign-in, and both verification
  records below.
- README updated: the studio now has accounts and history.

## Validation results

### Automated checks

| Check | Result |
| --- | --- |
| Python tests (macOS, Python 3.13 and the locked 3.11 environment) | 166 passed, including 9 new ones for hashing, sessions, sign-in errors, cross-account 404s and the history list |
| Frontend tests | 19 passed, including 11 new ones for sign-in, sign-out, an ended session, and History open, download and retry |
| Frontend production build | Type checking and Vite build passed |

### Real browser run with the full pipeline

On macOS with the locked Python 3.11 environment, Node 22 and the renderer
installed, I signed in through the website and chose **Try a sample**.

| Measurement | Recorded result |
| --- | --- |
| Job ID | `3ccbe879e9804fed9eecb4e015d4eda9` |
| Narration | Real Kokoro CPU synthesis, 18 of 18 lines |
| Video | 1920 × 1080, Light theme with music, 87.509 seconds, 11,805,904 bytes |

Also checked in the browser:

- The video played, and History listed it with its thumbnail.
- MP4 and subtitle downloads worked for the owner.
- A second account saw an empty History and got 404 for that job and its video.
- A signed-out request got 401.
- After a server restart, the account signed in again and History still
  listed the video.

## Current scope and remaining work

- PR #7 needs Harry's review and merge before the feature is in `main`.
- Generating a video from your own topic was not run through the website,
  because no Claude credential was configured on my machine.
- Jobs saved before this change have no owner, so they are not listed for
  anyone; their files stay in `runs/web/`.
- The server still runs only at `127.0.0.1`. Public hosting would also need
  HTTPS with a `Secure` cookie, a registration policy and sign-in rate
  limiting. There is no password reset.
- The first acceptance item (five seven-minute videos on non-AI topics, with
  success rate and quality scores) is with another teammate.

## How to run

From the repository root, with the Python and renderer dependencies installed:

```bash
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m capstone_web
```

Open [Traversaal Studio](http://127.0.0.1:8000), create an account, then use
**Try a sample** or your own topic. Past videos are under **History**.

Related documentation: [README](../../README.md) and
[web studio guide](../../docs/WEB_STUDIO.md).
