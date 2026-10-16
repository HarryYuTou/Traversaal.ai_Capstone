# Script Planner Guide

`capstone_script` turns a topic into a scene-by-scene script and voices every
line with the `capstone_tts` module. Each scene says what the viewer sees (one
of four slide templates) and what the narrator says, one short line at a time.

```text
Topic -> scene-plan.json -> one WAV per line + audio-manifest.json -> narration-preview.wav + preview.html
         (Claude API)        (capstone_tts, local CPU)                 (listening and visual check)
```

## Setup

Use the same Python 3.11 `.venv` as the TTS module and install
`requirements.lock.txt`; it now includes the `anthropic` SDK.

Only the `plan`, `run` and `review` commands call the Claude API. Create a file named
`.env` in the repository folder containing `ANTHROPIC_API_KEY=...`. Git ignores
`.env`; never commit or paste the key. A Claude subscription does not include
API usage. Each call's token usage is saved in `llm-response.json`; the list
price for Claude Opus 5.5 is $4 per million input tokens and $20 per million
output tokens.

## Commands

```bash
# Check a plan against the contract
python -m capstone_script validate --plan fixtures/scene-plan.valid.json

# Topic -> scene plan (Claude API)
python -m capstone_script plan --topic "What happens after you enter a website address?" \
  --audience "University students with no networking background" --duration 75 \
  --reference fixtures/reference-primary.md --out runs/plan-01

# Ground the script in a web page instead of a facts file; its text is saved as reference.md
python -m capstone_script plan --topic "How does GPS work?" --duration 90 \
  --reference-url https://en.wikipedia.org/wiki/Global_Positioning_System --out runs/plan-02

# Scene plan -> narration and preview (local CPU, no API key)
python -m capstone_script narrate --plan fixtures/scene-plan.valid.json --out runs/narration-01 --offline

# Narrate an edited plan, copying the audio of every unchanged line from an earlier run
python -m capstone_script narrate --plan edited-plan.json --out runs/narration-02 --reuse runs/narration-01 --offline

# Topic -> scene plan -> narration and preview in one run directory
python -m capstone_script run --topic "How do noise-cancelling headphones work?" --out runs/run-01 --offline

# A seven-minute video, planned chapter by chapter, then reviewed and edited
python -m capstone_script plan --topic "How AI search engines find answers" --duration 420 --out runs/long-01 --review

# Review an existing plan before narrating it (Claude API)
python -m capstone_script review --run runs/plan-01

# Plan and review a list of topics and summarize the results (Claude API)
python -m capstone_script evaluate --topics fixtures/evaluation-topics.json --out runs/eval-01 --narrate --offline

# Rebuild preview.html, or regenerate the JSON Schema after changing the models
python -m capstone_script preview --run runs/narration-01
python -m capstone_script schema

python -m unittest discover -s tests -v
```

`--duration` accepts 30–600 seconds. Up to 180 seconds, one request writes the
whole plan; longer videos are planned chapter by chapter (see below).
`--offline` uses the cached Kokoro model; omit it on the first narration. Every
command refuses an existing output directory.

## The ScenePlan contract

| Template | Visual fields | Narration highlight |
| --- | --- | --- |
| `concept` | `title` (≤60 chars), `statement` (≤120), up to 3 `points` (≤60 each) | `highlightPointIndex` |
| `flow` | `title` (≤60), 2–4 `nodes` with `id` and `label` (≤24) | `highlightNodeId` |
| `comparison` | `title` (≤60), `left` and `right` columns, each a `label` (≤24) and 1–3 `points` (≤48 each) | `highlightSide` (`left` or `right`) |
| `definition` | `title` (≤60), `term` (≤40), `definition` (≤140), optional `example` (≤100) | `highlightPart` (`term`, `definition` or `example`) |
| `timeline` | `title` (≤60), 2–5 `events` with `id`, `date` (≤20) and `label` (≤48), in time order | `highlightEventId` |
| `stat` | `title` (≤60), 1–3 `stats`, each a number `value`, optional `prefix` and `unit` (≤12), and a `label` (≤60); optional `note` (≤120) | `highlightStatIndex` |
| `quote` | `title` (≤60), `quote` (≤220), `author` (≤60), optional `context` (≤80) | `highlightQuote` (`true` on the line that reads the quotation) |
| `map` | `title` (≤60), a `region` from `schemas/map-regions.json`, up to 3 `areas` (an `id`, a `label` and up to 40 country names, with today's borders), up to 8 `places` (`id`, `label`, `lon`, `lat`) and `route` (connect the places in order) | `highlightId` (a place or an area) |

Every scene has an `id`, a `purpose`, a `template`, a `visual` and 1–8
narration lines of at most 25 English words. IDs use lowercase letters, digits
and hyphens because narration IDs become file names. Python also checks what
JSON Schema cannot: unique scene, line and node IDs, highlights that point to
an existing point or node, the word limit and English-only text.
The planner's prompt describes all eight templates, and its output shape, id
clean-up, icon filter and coverage check (every event, number, place and area
gets a highlighting line; a quote scene has a line that reads the quotation)
cover the four newer ones too. This has only been tested offline with a fake
client: before relying on it, run a real plan to confirm that the model picks
the new templates well. Without reference material, the prompt allows only
famous, widely documented dates and numbers, and only quotations it can give
word for word; the reviewer never rewrites a line that reads a quotation.
Concept and definition visuals, flow nodes, comparison columns, timeline
events and stats can also have an optional `icon`, one of the Lucide icon names in `schemas/icons.json`
(139 icons such as `database`, `credit-card` or `calendar`). Renderers draw
them; a plan with an icon outside the list is invalid, but the planner simply
drops unknown icons from Claude's answer instead of asking for a repair.

A long plan also has `chapters`: each has an `id`, a `title` and the `sceneIds`
it covers, and together they list every scene once, in order. Plans without
chapters are unchanged. A plan holds at most 60 scenes and 10 chapters.
`schemas/scene-plan.schema.json` is generated from the models for other
languages; the Python check remains the reference.

The voice reads unknown names by English spelling rules, so a few names it gets
wrong are respelled for the voice only in `schemas/pronunciations.json` (for
example `Qian` is read as `Chee-en`). Captions and subtitles keep the real
spelling, and reused audio is matched on the respelled text. A plan never contains audio
paths, durations or frames; later stages measure those from real audio.

## How the planner works

1. `prompts/scene-planner.txt` sets the rules; the request gives the topic,
   audience, word target (and asks to stay within 5% of it) and optional
   reference facts. `--reference-url` downloads a page, keeps its readable
   text (headings, paragraphs, lists and tables, without menus, scripts or
   footers) and caps it at 20,000 characters. Every run with a reference saves
   its own copy as `reference.md`.
2. Claude Opus 5.5 (effort `high`) answers with structured JSON output in its
   own output shape, not the ScenePlan schema: the full schema, a union of
   scene types, was already rejected as too large to compile with four types,
   and structured outputs accept at most 24 optional and 16 union-typed (`anyOf`,
   which is how an optional `| None` field is written) parameters per request.
   So every scene has one kind of `visual` with a `title` and one part per
   template (`visual.flow` for a flow scene, and so on), each narration line
   has one `highlight` text whose meaning depends on the template (a point or
   number position such as `"0"`, an id, `left`/`right`, `term`/`definition`/
   `example`, or `quote`), and optional texts such as icons take `""` for
   "none". That is 8 optional and no union-typed parameters; a test keeps every
   request schema under both limits. The program turns the answer into a
   ScenePlan, renumbers scene and line IDs and makes node IDs path-safe, and
   validation then applies each template's rules.
3. The plan must pass validation and fit the length: the word target assumes
   2.6 words per second, and a plan outside 80–120% of the target words counts
   as a problem. Asking for ±5% centered the real speech length on the target
   in testing; see [PLANNER_EVALUATION.md](PLANNER_EVALUATION.md). A plan must use at least two different templates, and every
   point, node, column and example must be highlighted by at least one
   narration line, so the visuals follow the narration.
4. If anything fails, one repair request (`prompts/repair-scene-plan.txt`)
   lists every problem, named by the output shape's fields (such as
   `scenes[2].visual.timeline.events[0].label`). A second failure stops the run; `llm-response.json`
   keeps both raw responses. API errors are retried by the SDK.

### Long videos

One request cannot write a seven-minute script well: it would run past a
dozen scenes and lose track of what it already explained. Videos over 180
seconds are planned in two stages.

1. **Outline.** `prompts/outline-planner.txt` asks for chapters: a title, a
   one-sentence goal, two to four key points and a length for each. There is
   about one chapter per 75 seconds (3–8 chapters), each 40–150 seconds, and
   the lengths must add up to within 10% of the target. The program then
   scales them to add up exactly.
2. **Chapters.** Each chapter is planned like a short video, in order, with the
   same validation, length and highlight checks. The request carries the whole
   outline, the chapter's key points and the previous chapter's last three
   lines, and `prompts/chapter-planner.txt` adds the rules for chapters: only
   the first chapter opens the video, only the last one ends with the summary,
   and every other chapter starts with one line that links to the one before.
   The rule of at least two templates applies to the video, not to each
   chapter.

The chapter plans are merged into one plan with chapters. Every request,
including the outline, gets at most one repair. A chapter that fails twice
stops the run, and `llm-response.json` keeps every response up to that point.

### Script review

`--review` (or the `review` command) sends the finished plan back to Claude
with `prompts/script-reviewer.txt`, which reads it the way a listener hears it
once. The reviewer scores the draft from 1 to 5 on clarity, flow, accuracy,
engagement and audience fit, lists the issues it finds (repetition, flow,
clarity, accuracy, speech and highlight sync) and rewrites the lines that need
it. Edits replace the text of existing lines only: ids, highlights and visuals
stay, so the reviewed plan has the same structure and passes the same checks,
and its word count must stay within the video's range. A local scan for
symbols and abbreviations the voice may misread is sent along as hints. The
voice's phonemizer reads common acronyms correctly (AI, LLM, DNS, HTTPS, GPU,
API, URL and PDF letter by letter, SQL as "sequel", NASA as a word) and reads
numbers and "10%" as words, but it says "e.g." as "ee-jee" and "vs." as
"viz", so the scan flags abbreviations, not acronyms. Invalid edits get one repair request. Review a plan before narrating
it; a narrated run is refused because its audio would no longer match.

### Evaluation

`evaluate` runs `plan --review` for every topic in a JSON list (topic,
audience, duration), optionally voices the plans of up to three minutes, and
writes `results.json` and `results.md` with first-request pass rate, length
against target, templates, review scores, rewritten lines, speech length and
cost. A topic that fails is recorded and the batch continues. The first batch
of eight topics is written up in [PLANNER_EVALUATION.md](PLANNER_EVALUATION.md).

### Reusing narration

`narrate --reuse <earlier run>` copies the audio of every line whose text is
unchanged, as long as the earlier run used the same voice, model revision and
speed, and synthesizes only the rest; the model is not even loaded when every
line matches. Each block in `audio-manifest.json` says whether it was reused
(`cacheHit`), and the manifest counts `reusedLines`. Re-narrating the
unchanged seven-minute plan this way took 4 seconds instead of about 4
minutes.

## Run outputs

| File | Written by | Contents |
| --- | --- | --- |
| `project-spec.json` | `plan`, `run` | Topic, audience, target duration, reference hash |
| `reference.md` | `plan`, `run` (with a reference) | The run's own copy of the reference text, which `review` reads |
| `llm-response.json` | `plan`, `run` | Model, request IDs, token usage, latency, problems and raw text for every request, plus a list-price cost estimate |
| `outline.json` | `plan`, `run` (long videos) | The chapter outline, with the length each chapter was planned for |
| `review.json` | `review`, `--review` | Scores, issues, each rewritten line before and after, speech hints, word counts, cost |
| `scene-plan.draft.json` | `review`, `--review` | The plan as the planner wrote it, before review edits |
| `scene-plan.json` | all | The validated plan used for narration (after review edits, if any) |
| `audio/<narrationId>/` | `narrate`, `run` | `capstone_tts` output for one line: WAV, `audio-info.json`, input |
| `audio-manifest.json` | `narrate`, `run` | Per line: scene, text, audio path, real sample count, duration, synthesis time |
| `narration-preview.wav` | `narrate`, `run` | All lines with fixed 0.2 / 0.1 / 0.2 s scene pauses, for listening only |
| `preview.html` | `narrate`, `run`, `preview` | Slides, highlights and subtitles driven by the preview track |

Open `preview.html` from the run folder in a browser. The preview pauses are
not the frame-accurate timeline; that stays with the timeline module.

## Measured results

On Windows 11 (Ryzen 7 5800HS, two CPU threads) the fixture plan's 18 lines and
214 words produced 81.0 seconds of speech (2.64 words per second) and an
84.3-second preview. Model loading took 19.6 seconds and synthesis 78.2 seconds.
Whole paragraphs read faster (about 2.9 words per second), so per-line timing
is the basis for the planner's word target. At this rate the week-one plan's
140–180 words would produce a 57–72 second video.

First real planner runs (October 8, 2026, Claude Opus 5.5, effort `high`). Each
plan passed on the first request, with no repair needed:

| Topic | Target | Scenes, lines, words | Real speech | Preview | Tokens in / out | Latency |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Entering a website address, with `reference-primary.md`* | 75 s | 7, 16, 195 | not narrated | — | 2,853 / 5,393 | 48 s |
| How noise-cancelling headphones work | 75 s | 5, 16, 191 | 71.1 s | 74.2 s | 2,462 / 2,609 | 24 s |
| Retrieval-augmented generation for business users | 90 s | 5, 18, 228 | 89.3 s | 92.6 s | 2,475 / 3,235 | 29 s |

\* Prompt v1. It left some points and nodes without a highlighting line, which
led to the coverage rule in v2. At list prices the three plans cost about
$0.12, $0.06 and $0.07.

Prompt v3, with the comparison and definition templates (October 8, 2026):
"Why do AI chatbots sometimes make things up?", 90 s, for curious adults with
no technical background. The first request passed: 5 scenes that used all four
templates (concept, definition, flow, comparison, concept), 20 lines and 217
words, for $0.07. The review rewrote 4 lines (217 to 225 words) for $0.05.

First long video (October 8, 2026, prompts `outline-planner-v1`,
`chapter-planner-v1` and `script-reviewer-v1`): "How AI search engines find
answers", 420 s, for curious adults with no technical background.

| Stage | Result | Tokens in / out | Time | Cost |
| --- | --- | ---: | ---: | ---: |
| Outline | 7 chapters of 45–80 s | 917 / 1,436 | 17 s | — |
| 7 chapter plans | 26 scenes, 94 lines, 1,077 words (about 414 s); every chapter passed on the first request | 22,775 / 16,932 | 182 s | — |
| Plan total | 8 requests, no repairs | 23,692 / 18,368 | 199 s | $0.46 |
| Review | Draft scored 4, 4, 5, 4, 4 (clarity, flow, accuracy, engagement, audience fit); 9 issues: 5 flow, 2 repetition across chapters, 1 clarity, 1 speech; 7 lines rewritten, 1,087 words | 10,658 / 4,282 | 39 s | $0.13 |

Each chapter opened with a line linking it to the previous one, and the
review caught what chapter-by-chapter writing tends to miss, such as a recap
line that nearly repeated a line from two chapters earlier. The reviewed plan
is saved as `fixtures/scene-plan.long.json` for renderer and timeline work.
