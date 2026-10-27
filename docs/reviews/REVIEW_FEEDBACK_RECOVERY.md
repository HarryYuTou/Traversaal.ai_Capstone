# Review feedback recovery

Date: 2026-10-27.

## Reported failure

Web job `75deefb7aa484edbb957ac6e2e6f2e9e` used a normal short prompt about
opening a second checkout counter, with a 60-second target and review enabled.
The closed-counter state was correct. The new failure was an unsupported
three-round versus one-round comparison: the baseline showed only the first
completion. Initial review classified the problem as accuracy and rewrote
its wording without supplying the missing evidence. The final audit identified
sync failures, but there was no recovery path after that audit.

## Change

Planning now sizes short comparisons to their available narration and action
budget. A partial demonstration supports a comparison at a matching visible
milestone; it cannot be presented as a completed full waiting-time example.
Reviewer guidance rejects cosmetic rewording of unsupported counts and asks
for explicit illustrative service-time assumptions.

The first visual-only repair retains its strict narration preservation. If
an immutable audit still reports any sync finding or medium/high accuracy
finding, a separate joint scene revision can correct both narration and
visuals. At most two such rounds are permitted, each followed by another
independent immutable audit of the exact candidate. The auditor sees the
previous findings, user brief and original explanatory scope. It must reassess
the evidence and preserve the teaching mechanism, not accept removal of the
explanation as a fix.

Revisions preserve scene IDs, templates, order and count; narration IDs,
order, count and highlights; quotation wording and attribution; and existing
object identity rules. Unaffected scenes and plan metadata remain unchanged.
Full plan validation, event coverage and the narration word budget run before
audit. Each request retains the existing single validation retry and bounded
template grammar. Credential/network failures propagate without editorial
fallback. A failed visual-only candidate is discarded before the unchanged
draft is audited for possible joint revision.

Only a clean final audit permits promotion. Exhaustion, invalid candidates or
audit errors leave the original `scene-plan.json` untouched. Candidate plans,
findings, rounds and API usage are saved for diagnosis. This is in-job repair,
not automatic resubmission of an entire failed job.

## Automated verification

The complete Python suite passes **317 tests**. New regressions cover
accuracy-first findings that become sync findings at audit, invalid visual
repair recovery, two-round exhaustion, category changes that cannot bypass
acceptance, identity/quote/highlight preservation, atomic multi-scene
replacements, word budgets, audit failures and discarding partial repairs.
The renderer and frontend implementation did not change in this follow-up.

## Live verification

Evidence is retained in the ignored local `runs/` directory. The original
failed job remains unchanged.

- `runs/review-feedback-original-live-20261027`: the exact original draft and
  spec passed real review and immutable audit with three narration edits.
  The comparison is now conditional on equal checkout times. Two low-severity
  editorial notes remain; this run did not require joint revision.
- `runs/review-feedback-qa-20261027/http_pipeline_qa.py`: uses the production
  HTTP server, authentication, readiness, job runner and worker with isolated
  account/job storage. It submits the exact failed request three times
  sequentially and checks completed video and subtitle delivery. No fixture,
  rewritten user prompt or readiness bypass is used. Results and media
  evidence are recorded per session.

The completed HTTP session is
`runs/review-feedback-qa-20261027/session-20261027T234644-ecb207/report.json`.
All **three of three** requests completed, with no failed jobs. Registration,
logout, login, authenticated history, MP4 HEAD/range delivery and WebVTT
delivery passed. The isolated server and runner were stopped afterward.

| Job | MP4 duration | Review behavior | Result |
| --- | --- | --- | --- |
| `77247efd650640b1a5521b7214aff9e4` | 59.200 s | Visual-only repair still left an overbroad “everyone” claim; one joint revision corrected it and the independent final audit found no remaining issues | Passed |
| `41e3c972ced14244962839cbfec37079` | 60.309 s | Ordinary narration review; no blocking findings requiring a separate audit | Passed |
| `0e21014c05dd49409f0d9b633bd2aa54` | 60.501 s | Narration correction followed by an independent final audit with no remaining issues | Passed |

All videos are 1920 × 1080 at 30 fps. Complete video/audio decoding passed,
and all narration inputs and subtitle text match each final plan. Sampled
inspection covered 8, 6 and 5 frames respectively, including the closed
baseline, opening, open result, parallel service and final comparison.
Each output directory contains `visual-verification.json` and the inspected
frames under `qa/`. The first run exercises the new recovery with real model
responses, rather than a forced or mocked finding.

Minor notes remain: the first video's “fourth in line” could more clearly say
“fourth overall,” and the second video's opening has only a short gap before
the next action, although the open state remains visible during service.
Neither was a blocking sampled-frame finding. Full listening and viewing
every animation frame were not performed.

Repeated stochastic trials and sampled-frame inspection provide evidence for
this case, not a guarantee of arbitrary-topic correctness or a completed
seven-minute Level 1 evaluation.
