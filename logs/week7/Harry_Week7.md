# Harry - Week 7 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation

**Date:** November 19, 2026

**Implementation branch:** `level2-v1`

**Focus:** Seedance video generation, full-video composition, and the integrated studio workflow

## Contribution to the capstone

Extended the existing explainer pipeline with a Level 2 video-generation mode.
Claude prepares the explanation and shot directions, Seedance generates the
visual footage, and Remotion assembles the footage with local narration,
captions, and optional background music into a downloadable MP4.

Completed the provider integration, composition, and recovery work together
across M1–M3. The initial implementation combined generated footage with
animated explanations. Following product feedback, revised new Seedance jobs
to use generated footage for every visual scene, with one target-length
setting and one quality setting. The separate Animated explanations mode
retains its existing controls and rendering behavior.

## Completed work

### M1: fixed-model provider integration and cost controls

- Added the `capstone_video` package for Ark authentication, task submission,
  polling, download, shot planning, and resumable sample generation.
- Restricted every video request to **Doubao-Seedance-2.0-fast**, exact ID
  `doubao-seedance-2-0-fast-260128`. Conflicting model configuration is rejected,
  and completed tasks must identify the expected model. No more expensive
  model is selected as a fallback.
- Supported silent, 16:9 video generation at 480p or 720p. The local pipeline
  supplies its own narration and music instead of using generated audio.
- Kept credentials on the backend. Media downloads use a separate HTTP client
  so the Ark authorization header is not forwarded to storage hosts.
- Recorded submission attempts, provider usage, and estimated generation cost.
  Missing usage remains unavailable rather than being reported as zero cost.
- Disabled the provider's visible watermark for new submissions after feedback
  on the first sample. Resume continues to reuse existing clips; it does not
  remove embedded watermarks or silently regenerate paid footage.
- Added a CLI sample with `--prepare-only` for local narration and shot planning
  without an Ark request, and `--resume` to continue saved work.

### M2: continuous generated footage and final composition

- Added a dedicated full-video timeline and Remotion composition. New Seedance
  jobs cover every frame with generated footage, including intervals previously
  occupied by title and chapter cards. No separate animated cards, diagrams,
  progress bars, or scene backgrounds are inserted into this mode.
- Preserved absolute narration and caption timing while assigning the former
  card intervals to generated scenes. Quotations use normal captions rather
  than separate quotation cards.
- Required the director to supply a prompt for every scene and timed slot.
  Scientific cutaways and qualitative visualizations can illustrate hidden
  mechanisms; exact labels and numbers remain in narration and captions.
- Split scenes into balanced shots no longer than ten seconds. Provider request
  durations round up to whole seconds with a four-second minimum. Longer films
  are assembled from multiple requests rather than one long model output.
- Batched longer shot plans while maintaining a shared visual style. Full-video
  coverage checks reject missing scenes, gaps, or overlaps before paid requests.
- Normalized downloaded footage to the 30 fps timeline, removed provider audio,
  and trimmed each clip to its required frame count. Short or corrupt clips fail
  validation rather than being frozen, looped, or slowed to fill the timeline.
- Matched final export dimensions to the selected quality: 854 × 480 or
  1280 × 720. Captions scale proportionally at both sizes. Seedance jobs no longer
  combine low-resolution source footage with a separately selected 1080p export.
- Preserved previously saved hybrid jobs through versioned job and plan formats.
  Existing paid clips and completed outputs are not silently converted.

### M3: studio workflow, persistence, and recovery

- Integrated Seedance into the existing browser workflow for custom topics and
  the authored sample, including setup checks, shot-planning progress, generated
  clip progress, playback, downloads, and per-account history.
- Simplified the Seedance form to one **Target length** and one **Video quality**
  selector. Removed the separate generated-footage limit and hid animation-only
  draft, theme, and minimum-duration controls in this mode.
- Kept the animation controls available when switching back to Animated
  explanations. Backend normalization prevents a hidden draft selection from
  overriding Seedance export quality.
- Added duration/quality-based cost estimates and completed-result metadata for
  the fixed model, resolution, clip count, and usage-based generation estimate.
- Persisted narration checkpoints, plan hashes, submission intents, task IDs,
  clip states, usage, and verified media hashes. Ready clips and saved tasks are
  reused after a download or rendering failure.
- Added owner-checked Resume behavior, active-job guards, and process locking.
  A definite failed shot permits at most one explicit retry. There are no
  automatic paid submission retries or paid restarts when the server starts.
- Saved submission intent before contacting Ark. If a task ID is lost, the
  ambiguous outcome blocks automatic resubmission to avoid duplicate charges.
- Detected changes to saved settings, narration, plans, or media before reuse.
  Partial local renders are preserved before a resumed render starts.
- Updated setup, sample, recovery, and full-video documentation.

### Credential troubleshooting and repository checks

- Diagnosed a custom-topic failure as Claude authentication being rejected before
  any Seedance request. Distinguished the Claude script credential from the Ark
  video credential, and clarified why the authored sample can run without Claude.
- Confirmed `.env` is ignored and untracked, the committed example contains blank
  credential fields, and local accounts, job logs, and generated media remain
  under ignored output directories.
- Scanned the 249 then-current tracked/untracked eligible files and file contents
  reachable from 107 commits, including exact matches against the two locally
  configured credentials. No matching credentials or historical sensitive
  configuration/database paths were found. The local frontend build also had
  no matching credentials.
- Identified an existing local-user directory path in `docs/WEEK_01_PLAN.md` as a
  non-secret privacy detail. The remaining manual confidentiality review was
  interrupted by an environment disconnect; this is not a comprehensive security
  certification or a scan of the live GitHub repository.

## Validation results

### Automated checks

| Check | Latest recorded result |
| --- | --- |
| Python test suite | 412 passed; 12 HTTP tests blocked by sandbox `socket.bind` permissions |
| Seedance tests within the Python suite | 31 passed, including 8 full-video tests |
| Renderer tests | 193 passed |
| Frontend workflow tests | 29 passed |
| Renderer TypeScript check | Passed |
| Frontend production build | Passed |

The Seedance count is included in the Python total, not an additional suite to
add to it. Coverage includes fixed-model requests, provider errors, missing
usage, lost responses, explicit retries, saved-task recovery, media normalization,
frame coverage, director batching, and unchanged animation settings. A ten-minute
shot-plan test verifies that full-video planning is not truncated by the previous
120-second footage cap; it does not establish a completed ten-minute live render.

### Real generation and local media verification

| Run | Recorded result | What it establishes |
| --- | --- | --- |
| Initial cold-glass sample, legacy hybrid mode | 30.635-second MP4; 4 generated clips; 30 submitted seconds; estimated CNY 11.2107 | Real Fast-model generation, download, narration, and final rendering |
| Full-video sample preparation | 30.633-second timeline; 5 planned shots; 33 requested seconds; no Ark request | Real local TTS and complete shot coverage before paid generation |
| Custom topic: **Why Does Popcorn Pop?**, full-video mode | 56.704-second MP4 container; 56.700-second picture; 854 × 480; 7 generated clips; 59 submitted seconds; estimated CNY 22.0343 | A completed custom-topic studio job through the full-video pipeline |

The latest popcorn job completed with the exact Fast model and a full-coverage
marker. Rechecked its saved plan and timeline, verified all seven clip hashes,
and probed the actual MP4: 1,701 video frames and one audio stream. All three
scenes use generated footage, their shots cover all 1,701 frames, and the timeline
contains no separate title or chapter cards.

The original glass sample received positive visual feedback and exposed the
visible-watermark issue addressed in subsequent requests. The popcorn evidence
establishes a completed file, continuous planned coverage, matching assets, and
the expected output dimensions. It does **not** claim a complete human viewing,
listening, scientific-accuracy review, or browser playback/download acceptance.
Reported costs are estimates from provider usage, not final billing guarantees.

## Current scope and remaining work

- Seedance supports short clips per request; seven-minute films use multiple
  generated shots and local composition. The current Seedance Target length is
  a goal, not a guaranteed minimum: the 60-second popcorn request produced about
  56.7 seconds. A strict seven-minute delivery requires measured narration
  extension and an explicit final MP4 check of at least 420 seconds.
- Complete a seven-minute real generation and review visual consistency,
  scientific accuracy, caption readability, narration, and sound. Shared prompt
  style does not by itself guarantee consistency between independently generated
  shots.
- Complete full browser playback, seeking, download, and interruption/resume
  acceptance for the new mode; rerun the 12 blocked HTTP tests where localhost
  binding is available.
- Generation time and cost grow with shot count and resolution. Whole-second
  rounding, short-slot minimums, and explicit retries can increase submitted
  footage beyond the final edited duration.
- Ambiguous submissions still require checking Ark task history; automatic
  reconciliation or task import is not implemented. Provider expiry can limit
  recovery of results that have not yet been downloaded.

## Evidence and related files

- [Level 2 integration and recovery guide](../../docs/LEVEL2.md)
- [Web studio guide](../../docs/WEB_STUDIO.md)
- [Seedance provider](../../capstone_video/provider.py)
- [Full-video timeline](../../capstone_video/composition.py)
- [Full-video director instructions](../../prompts/full-video-director.txt)
- [Full-video Remotion composition](../../renderer/src/FullSeedanceVideo.tsx)
- [Seedance tests](../../tests/test_seedance.py)
- [Full-video regression tests](../../tests/test_seedance_full.py)
- [Studio workflow tests](../../web/tests/studio.test.tsx)

Detailed task records and generated media remain in Git-ignored local directories:

```text
runs/level2-seedance-30s/output/
runs/level2-seedance-no-watermark/output/
runs/level2-full-video-preview/output/
runs/web/<job-id>/output/
```

At the time of this log, the implementation and documentation remain local
working-tree changes on `level2-v1`; this work has not been committed or pushed.
