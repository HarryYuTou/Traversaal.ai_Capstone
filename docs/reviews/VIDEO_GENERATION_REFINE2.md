# Video generation refinement 2

Date: 2026-10-27. Branch: `video-generation-refine2`.

## Changes

1. **Causal evidence and review.** Process plans can author an `open` event. A targeted station starts closed and cannot serve until opening completes. Planning and repair prompts place openings in their spoken clause and retain a visible result hold. The renderer shows CLOSED / OPENING / OPEN states. Reviews repair visuals while preserving the affected narration, then audit the exact result. Unresolved sync or medium/high accuracy issues prevent publication, including when a reviewer changes the issue category. Medium/high accuracy findings in the first review also require an audit. Chapter planning receives prior identities and final process state.
2. **Composition and continuity.** Related process scenes share a fitted wide view. Long authored holds may use a restrained detail shot; the camera returns wide before movement. Object colors remain authored. Captions and title space remain protected. The new comparison fixture shows the same three customers with equal service rounds at one and two counters.
3. **Measured duration.** New requests targeting at least 420 seconds require at least 420 measured seconds by default. Short runs receive up to two successfully promoted content extensions, reviewed and voiced before acceptance; existing audio is reused. Failed candidates and original outputs are retained. Checks run on the narrated timeline, the final MP4, and job completion. The website exposes the minimum requirement and target/actual/pass results. Older specs without an explicit minimum remain compatible.

## Automated verification

| Check | Result |
| --- | --- |
| Python suite | 286 passed |
| Renderer motion/state/duration suite | 42 passed |
| Frontend suite | 24 passed |
| Renderer TypeScript check | Passed |
| Frontend TypeScript and production build | Passed |
| Whitespace/diff check | Passed |

Coverage includes station lifecycle and timing; camera bounds and deterministic seeking; narration preservation; audit-only reviews; unresolved factual claims; duration retry accounting and rollback; duplicate content rejection; cache reuse; post-render enforcement; job acceptance; legacy behavior; and review cost accounting.

The browser check used an isolated local account and temporary server. It exposed a CSS specificity conflict that hid the duration toggle. The corrected toggle was visually checked and switched off successfully. The temporary server was stopped. Screenshot: `runs/refine2-counter-comparison-final-20261027/qa-duration-ui.jpg`.

## Actual media and model checks

- `runs/refine2-counter-comparison-final-20261027`: real local narration, 1080p/30fps MP4, 70.037 seconds. Opening and comparison frames were inspected, including the OPENING sign, longer OPEN result hold and readable captions. The final opening midpoint screenshot is `qa-opening-final.png` in that run.
- `runs/refine2-live-review-comparison-20261027`: a deliberately missing opening event was detected and repaired by the real API. The final audit passed with no remaining sync or medium/high accuracy issues. All 156 narration words stayed unchanged; minor editorial suggestions remain recorded. This is a controlled semantic-repair regression, not a claim that every generated topic is correct.
- `runs/refine2-auto-repaired-comparison-20261027`: the real repaired plan compiled against all 12 reused audio lines and rendered to a 70.037-second 1080p MP4. The API restored a full-line opening; the checked-in comparison fixture uses an earlier opening plus a longer result hold for clearer presentation.
- `runs/refine2-lunar-duration-technical-20261027`: an API-generated extension was voiced locally, reusing 85 of 94 lines. The 1080p MP4 measures 428.949 seconds and passes the 420-second gate. This is explicitly a duration/rendering technical test, not an approved educational video.

- `runs/refine2-duration-live-positive-02-20261027`: positive end-to-end integration of real API content extension, review, local TTS, promotion and 1080p rendering. The explicit 120-second test minimum was met in one successful round: 88.70 seconds before, 130.7667 seconds on the timeline, and **130.773 seconds in the final MP4**. All 26 narration lines were checked; 17 were reused and 9 synthesized (8 new lines and 1 reviewed rewrite). The rendered duration check passed. The review had no blocking sync/factual issues; two editorial findings were edited and five low-priority notes remain. Recorded API cost was $0.1162. `technical-verification.json` preserves these measurements. This shorter integration exercises the same repair/promotion path as the 420-second gate; the separate lunar technical test verifies the actual seven-minute MP4 threshold.

## Rejected cases and limitations

The earlier desktop counter script's unshown comparison was reclassified by the reviewer as an accuracy issue. This exposed the acceptance loophole now covered by regression tests. The older diagnostic result in `runs/refine2-live-review-counter-20261027-05` must not be treated as final approval.

The old lunar plan still has pre-existing semantic problems: opacity changes do not depict lunar phases, and some orbit/color continuity is inconsistent. Its automatic extension was not promoted. The technical MP4 is not presented as a factual or visual-quality acceptance. The original run remains intact.

An initial short duration integration also stopped on a pre-existing fixture highlight mismatch: a line about IP addresses highlighted the browser without explaining its role. The second positive test corrects that line only in its QA input, preserving the production fixture and the strict acceptance gate.

API credit failures encountered during testing are preserved as failed attempts. Once credits were restored, actual repair and audit calls resumed. Automated checks and sampled-frame inspection do not establish universal correctness or replace a content/listening review of each final video.
