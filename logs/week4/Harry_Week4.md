# Harry - Week 4 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation

**Date:** October 27, 2026

**Implementation branch:** `video-generation-refine2`

**Focus:** Narration-to-action consistency, clearer composition, and measured Level 1 duration requirements

## Contribution to the capstone

Built on the Week 3 animation pipeline by addressing three weaknesses found
in the generated videos: narration could describe a change that was not
actually shown, process scenes could feel too small or visually inconsistent,
and a seven-minute target could produce a shorter finished video.

Added explicit causal events and structural visual review, improved process
framing, and introduced a measured minimum-duration requirement with content
extension and audio reuse. Verified the changes through automated tests,
real Claude requests, local Kokoro narration, 1080p rendering, and browser
inspection of the new duration controls.

## Completed work

### Narration, causal events, and review

- Added the `open` process event. A station targeted by this event begins
  closed and cannot serve an actor until its opening completes. Other
  stations retain their existing initially open behavior.
- Added visible **CLOSED → OPENING → OPEN** station states, with timing
  derived from measured narration. Planning instructions place the opening
  alongside its spoken clause and leave time to inspect the result.
- Created a controlled comparison using the same three customers, queue
  order, and equal service rounds at one and two counters. The replay is
  explicitly announced, and the orange customer's waiting rounds are shown
  under both conditions.
- Added structural repair for scenes with narration/action mismatches.
  Repairs preserve the affected narration and scene template while fixing
  visuals and events, then pass full-plan validation and a separate final
  audit that cannot rewrite the plan it assesses.
- Prevented unresolved sync or medium/high accuracy issues from passing
  the final audit. A reviewer cannot make an unsupported comparison
  acceptable merely by changing its category from sync to accuracy.
  Initial medium/high accuracy findings also require a final audit.
- Passed prior object identities and final process state into subsequent
  chapter planning. Continuing objects retain their identity; a reset or
  replay must be explained. Repair records preserve findings, changes,
  affected scenes, and unresolved issues.

### Composition and visual continuity

- Fitted process scenes to their visible content and movement bounds,
  improving object scale and reducing unused space.
- Gave related consecutive process scenes a shared wide view so their
  framing remains stable as the queue changes.
- Added restrained detail views during sufficiently long authored holds.
  The camera returns to the wide view before movement resumes, while
  keeping actors, labels, titles, and captions within their safe areas.
- Preserved authored identity colors and deterministic frame evaluation,
  including when seeking to frames out of order.
- Corrected the title-card duration wording for videos shorter than one
  minute and extended the narration preview to recognize opening events.

### Measured duration and frontend integration

- New requests targeting at least 420 seconds default to a measured
  **420-second minimum**. Shorter requests and sample videos remain exempt;
  users can explicitly disable the minimum. Existing run specifications
  without the new requirement retain their previous behavior.
- When measured narration is too short, request useful additional
  explanation, review the combined plan, and synthesize the added or
  changed lines. Size the extension using the observed speaking rate.
- Limit the workflow to two successfully promoted content extensions.
  Failed attempts retain their evidence and do not consume that successful
  extension allowance. Candidate validation and rollback protect the
  existing run, and replaced media is archived when a new version is accepted.
- Reuse unchanged audio, reject repeated narration, and retain the expanded
  script's measured word budget during review. Include extension and review
  costs in the scorecard without counting the current review twice.
- Check duration on the narrated timeline, the encoded MP4, and web-job
  completion. A video below its required minimum is not marked ready.
- Added the **Level 1 duration check** option and target/actual/pass details
  to the web interface. Browser testing found and fixed a CSS specificity
  conflict that initially hid the new toggle.
- Added `ensure-duration` for existing narrated runs and updated the motion,
  script, quick-start, and web documentation. `--offline` uses cached TTS
  weights; generating additional content still requires the Claude API.

## Validation results

### Automated checks

Recorded during this implementation and verification iteration:

| Check | Result |
| --- | --- |
| Python test suite | 286 passed |
| Renderer motion, state, and duration tests | 42 passed |
| Frontend tests | 24 passed |
| **Total automated tests** | **352 passed** |
| Renderer TypeScript check | Passed |
| Frontend type checking and production build | Passed |
| Change formatting | `git diff --check` passed |

Coverage includes station lifecycle and timing, camera bounds, deterministic
seeking, narration preservation, immutable audits, unresolved factual claims,
duration enforcement, retry accounting, rollback, audio reuse, legacy
compatibility, web-job acceptance, and cost accounting. Affected checks were
rerun after the final review-metadata and station-signage adjustments.

### Real API, narration, and rendering checks

| Check | Recorded result | Verification boundary |
| --- | --- | --- |
| Final authored counter comparison | 70.037 s, 1920 × 1080, 30 fps | Real narration and rendering; opening, result hold, comparison, and caption frames inspected |
| Deliberately missing opening event | Real API detected and repaired it; final audit passed | All 156 narration words stayed unchanged; minor editorial notes remain |
| Automatically repaired comparison | 70.037 s, 1080p MP4; all 12 audio lines reused | Repaired plan compiled and rendered; the authored fixture uses a clearer, longer opening-result hold |
| Positive duration integration | **88.70 → 130.773 s**, one accepted extension | Complete API extension, review, TTS, promotion, and 1080p render against an explicit **120 s** test minimum |
| Seven-minute duration/rendering check | **428.949 s**, 1080p MP4 | Passed the actual **420 s** duration gate; educational/visual quality was not approved |

The successful duration integration contained 26 narration lines: 17 reused
and 9 synthesized, consisting of 8 new lines and 1 reviewed rewrite. Two
editorial findings were addressed through narration edits; five low-priority
notes remain. Its recorded API cost estimate was **$0.1162**, for this test
run only. The shorter integration exercises the same extension and promotion
path as the seven-minute requirement; the separate long technical render
checks the actual 420-second MP4 threshold.

The browser check used an isolated local account and temporary server. The
duration toggle was visually checked and successfully switched off after
the CSS fix, then the temporary server was stopped. A complete custom-topic
generation submitted and finished through the browser was not recorded;
the live generation checks above used the shared command-line pipeline.

## Issues caught and remaining work

- The old desktop counter script retained an unshown comparison after a
  reviewer relabeled it as an accuracy issue. This exposed the acceptance
  loophole now fixed and covered by regression tests; the earlier diagnostic
  result is not treated as final approval.
- The old lunar video still has pre-existing semantic problems: opacity
  changes do not depict lunar phases, and orbit/color continuity is
  inconsistent. Its automatic extension was not promoted. The 428.949-second
  technical MP4 demonstrates duration and rendering only, and the original
  run remains intact.
- An initial short duration test stopped on an existing fixture's mismatch
  between IP-address narration and a highlighted browser node. The successful
  follow-up corrected that sentence only in its QA input, leaving the
  production fixture and acceptance standard unchanged.
- The animation system still has a bounded object/action vocabulary.
  Sampled-frame inspection and automated checks do not replace full listening
  and editorial review, establish arbitrary-topic reliability, or complete
  the broader target of five accepted seven-minute videos on non-AI topics.

## Evidence and related files

- [Detailed implementation and verification report](../../docs/reviews/VIDEO_GENERATION_REFINE2.md)
- [Controlled counter-comparison fixture](../../fixtures/scene-plan.process-counter-comparison.json)
- [Motion and process guide](../../docs/MOTION_GUIDE.md)
- [Script guide](../../docs/SCRIPT_GUIDE.md) and [web studio guide](../../docs/WEB_STUDIO.md)

Generated videos and detailed run records remain in the local, Git-ignored
`runs/` directory:

```text
runs/refine2-counter-comparison-final-20261027/
runs/refine2-live-review-comparison-20261027/
runs/refine2-auto-repaired-comparison-20261027/
runs/refine2-duration-live-positive-02-20261027/
runs/refine2-lunar-duration-technical-20261027/
```

## Demo follow-up: short-prompt review failure

The one-minute checkout demo exposed a missing station state: a declared
counter could not remain closed for a full scene without a later opening.
The repair therefore either removed its identity or invented an unspoken
opening, and the final audit correctly stopped generation.

Added optional explicit `initialState` for process stations, with legacy
behavior preserved. The planner, reviewer, repair prompt, compiler and chapter
context now agree on this state; the review gates remain strict. Web failures
also explain the quality-check problem in plain language.

The failed original script now passes real API repair and final audit while
preserving its baseline narration and events. A fresh run from the same short
user prompt completed planning, review, TTS and a **60.736-second 1080p MP4**.
Six sampled frames verified the closed baseline, opening and parallel service.
The follow-up passed **296 Python tests and 44 renderer tests**, plus the
renderer TypeScript check. Evidence is recorded in the detailed report above
and `runs/closed-counter-short-prompt-e2e-20261027/verification.json`.

## Demo follow-up: recovery after final review feedback

A second real web attempt exposed a different failure: narration claimed a
complete waiting-time comparison while the baseline showed only part of it.
The first review adjusted wording, but the final audit found the remaining
visual mismatch and had no path to request a substantive correction.

Added up to two joint narration/visual revision rounds after blocking final
feedback, each followed by an independent audit. Revisions preserve scene
structure, quotations and object identity, and validate the complete plan
before promotion. Failed candidates leave the original plan intact. Planner
and reviewer guidance now require comparisons supported by the actions shown
and explicit equal-service assumptions. The quality gate remains enforced.

The complete Python suite passed **317 tests**. The exact original request
then completed **3/3 real HTTP generation runs**, producing **59.200, 60.309
and 60.501-second 1080p videos**. One run actually used the new joint revision
and passed its final audit. Authentication, job completion, video streaming
and subtitle downloads passed; all videos decoded successfully, and sampled
frames and narration/subtitle consistency were checked. These checks did not
include full listening or inspection of every frame.

See the [recovery implementation and verification report](../../docs/reviews/REVIEW_FEEDBACK_RECOVERY.md).
Detailed results remain in
`runs/review-feedback-qa-20261027/session-20261027T234644-ecb207/report.json`.
