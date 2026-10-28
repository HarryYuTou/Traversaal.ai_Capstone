# Tong - Week 4 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 28, 2026  
**Branch:** `feat/render-concurrency` (merged into `main` through PR #12)  
**Focus:** Reliable seven-minute renders on 8 GB laptops, and a working local setup for checking the team's changes

## Contribution to the capstone

Level 1 still needs four or five more seven-minute videos on non-AI topics.
Last week my 8 GB MacBook could only finish a seven-minute render after
Remotion was limited to two browser tabs by hand, because the `render` command
had no option for it. This week I added that option, so whoever renders the
Level 1 videos on a laptop can do it with the normal commands.

```text
Topic -> Script -> Narration -> Render (--concurrency) -> Scorecard -> Level 1 acceptance
                               ^ this week's work
```

None of this work calls the Claude API. I built it with Claude Code.

## Completed work

### Render concurrency (`--concurrency N`)

- `render`, `run --render` and `ensure-duration --render` now accept
  `--concurrency N`, the number of frames Remotion draws at once, each in its
  own headless browser tab. Without the option nothing changes: Remotion keeps
  its default of half the CPU cores, at most 8.
- The value is checked while the command line is parsed. A value such as `0`
  or `two` stops `run --render` immediately, before any Claude API request,
  instead of failing after planning and narration have already been paid for.
- `video-info.json` and `video-draft-info.json` record the value used
  (`null` for Remotion's default), so a render's settings can be traced later.
- Documentation: usage in `docs/RENDERER_GUIDE.md`, an 8 GB tip in
  `docs/QUICKSTART.md`, and the queue video review now states that the option
  exists. This was fix 5 in last week's review.

### Project status check after Harry's week-4 changes

At the start of the week I compared `main` with the remaining Level 1 work
after Harry's PR #11 and his follow-up fixes (52 files). They add causal
process events, structural visual repair with an independent final audit,
camera framing fitted to the scene, and a measured 420-second minimum with
automatic content extension. Harry also extended my scorecard so the cost of
extension and review rounds is counted once.

According to Harry's log, the new framing addresses fix 1 from my queue video
review (action sitting in one half of the frame) and part of fix 4 (object
colours and identities kept across chapters). I have not yet re-rated a video
made with these changes.

### Local setup repair

My local `.venv` had stopped working: it pointed to a temporary Python 3.11
that no longer existed, so no command or test could run. I installed a
permanent Python 3.11 under `~/.local/python311` and repointed the existing
environment with `python3.11 -m venv --upgrade .venv` after removing the three
broken `python` links. The installed packages were reused, `pip check` found
no problems and `capstone_tts doctor` passed. Node.js 22.23.3 was already
installed under `~/.local/node` but was not on `PATH`; the renderer and
frontend checks ran with it added to `PATH`.

If a teammate's `.venv` breaks the same way, the same `venv --upgrade` repair
avoids reinstalling the large dependencies such as PyTorch.

## Validation results

| Check | Result |
| --- | --- |
| Python tests | 321 passed, including 4 new render tests: the Remotion command with and without the option, rejected values, parsing-time checks for all three commands, and the value reaching the renderer |
| Renderer tests | 43 passed; TypeScript check passed |
| Frontend tests | 24 passed; production build passed (no frontend code changed) |
| Real render | The network sample (`fixtures/scene-plan.motion-network.json`) was narrated offline and rendered with `render --draft --concurrency 2`. Remotion reported `Concurrency 2x`; the 47.2 s draft rendered in 72 s, matched its timeline, and `video-draft-info.json` recorded `"concurrency": 2` |
| After merging PR #12 | `main` is identical to the tested commit, and all three suites pass again |

## Current scope and remaining work

- **Five seven-minute videos.** Four or five more seven-minute videos on
  non-AI topics still need a live Claude run with an API key. On an 8 GB
  laptop, add `--concurrency 2` (or `1` if it still crashes).
- **A full seven-minute render with the option.** It has been checked on a
  47-second draft only, not yet on a seven-minute 1080p render.
- **Web studio.** The browser workspace still renders at Remotion's default;
  it does not expose this option yet.
- **Scorecard and the new duration minimum.** The scorecard still applies a
  fixed 420-second limit. It should read each run's own `minimumDurationSec`
  and report extension rounds (length before and after).
- **More raters.** Each video should still have at least one more rater.
- **Visual fixes.** Fixes 2 (keep the counter visible), 3 (definition scenes
  in the illustrated style) and the rest of 4 (station labels on the outer
  side) from the queue video review remain open.

## How to run

```bash
.venv/bin/python -m capstone_script run --topic "..." --duration 420 --review --render --share --concurrency 2 --out runs/l1-...
.venv/bin/python -m capstone_script render --run runs/l1-... --concurrency 2   # re-render an existing run
```

Related documentation: [renderer guide](../../docs/RENDERER_GUIDE.md) and
[queue video review](../../docs/reviews/2026-10-20-queues-7min.md).
