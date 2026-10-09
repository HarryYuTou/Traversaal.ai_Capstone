# Script Planner Evaluation

How reliably does the script stage turn a topic into a usable script? This
batch planned and reviewed eight topics of 60 seconds to five minutes for
different audiences, and voiced the six short ones to measure real speech
length. It ran on October 9, 2026 with Claude Opus 5.5 (effort `high`),
prompts `scene-planner-v3`, `outline-planner-v1`, `chapter-planner-v1` and
`script-reviewer-v1`, and Harry's TTS module on Windows.

```bash
python -m capstone_script evaluate --topics fixtures/evaluation-topics.json --out runs/eval-01 --narrate --offline
```

The command writes one normal run directory per topic plus `results.json`
and `results.md`, so every number below can be traced to a run's files.

## Results

| # | Topic (audience) | Target | Mode | Words (of target) | Scenes | Review scores* | Lines rewritten | Speech | Cost |
| ---: | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | How do vaccines train the immune system? (adults, no science background) | 90 s | single | 236 (106%) | 5 | 4, 4, 4, 4, 5 | 3 | 92.1 s | $0.13 |
| 2 | What is compound interest and why does it matter? (high school students) | 60 s | single | 162 (110%) | 5 | 4, 4, 5, 4, 4 | 5 | 65.8 s | $0.14 |
| 3 | How does GPS know where you are? (adults, no technical background) | 120 s | single | 309 (104%) | 6 | 4, 4, 4, 4, 4 | 4 | 115.9 s | $0.18 |
| 4 | What is a large language model? (business professionals) | 180 s | single | 462 (104%) | 7 | 4, 4, 4, 4, 5 | 4 | 169.1 s | $0.18 |
| 5 | How do credit card payments work behind the scenes? (small business owners) | 90 s | single | 236 (106%) | 5 | 4, 3, 3, 3, 4 | 6 | 90.6 s | $0.15 |
| 6 | Why do we have leap years? (middle school students) | 60 s | single | 158 (107%) | 5 | 4, 4, 4, 4, 5 | 3 | 58.5 s | $0.11 |
| 7 | How does a search engine decide which pages to show first? (marketing professionals) | 300 s | 5 chapters | 811 (109%) | 20 | 4, 4, 4, 3, 4 | 16 | — | $0.56 |
| 8 | What really happens to the things we recycle? (adults) | 300 s | 5 chapters | 779 (105%) | 18 | 4, 3, 4, 4, 4 | 8 | — | $0.48 |

\* Clarity, flow, accuracy, engagement and audience fit, from 1 to 5, given
by the reviewer to the draft before its edits.

## Findings

- **Reliability.** All 8 plans passed validation on the first request; no
  repair was needed, including the 12 requests of the two chaptered videos.
  Every review passed on its first request too.
- **Length.** Drafts came out 2–7% above the word target and the review added
  0–4% more, so final scripts were 104–110% of target. Real speech for the
  six voiced scripts was 99–115% of the speech target (95% of the video
  length); the listening previews, which include pauses, were 97–115% of the
  requested length. The shortest videos ran longest in relative terms (60 s
  compound interest: 68.7 s preview).
- **Templates.** All four templates appeared in every plan: 27 concept,
  15 flow, 15 comparison and 14 definition scenes. Every five-scene plan used
  the same mix (two concept scenes and one of each other), so short videos may
  start to look alike; a later prompt could vary the order and mix by topic.
- **Review.** Mean scores were 4.0 clarity, 3.75 flow, 4.0 accuracy, 3.75
  engagement and 4.38 audience fit. The reviewer found 60 issues (17
  repetition, 16 flow, 14 clarity, 8 accuracy, 3 highlight sync, 2 speech) and
  rewrote 49 lines. Repetition clustered in the chaptered videos (6 of the 15
  issues in topic 7), which is what the review step was built for.
- **Accuracy.** The reviewer flagged at least one possible accuracy problem
  in 7 of 8 scripts, usually a specific claim stated more firmly than general
  knowledge supports. Without a reference file, a human fact check is still
  needed before a video is published.
- **Cost and time.** Planning plus review cost $1.92 for all eight: $0.11–0.18
  for videos up to three minutes and about $0.50 for five minutes, at list
  prices. Planning took 26–44 s for one request and 138–164 s for five
  chapters.

## Limits of this batch

One run per topic, so the numbers show typical behavior rather than rates
with confidence intervals. The review scores come from the same model family
that wrote the scripts, so they are a consistency check, not an independent
judgment; a short human rating of a few videos would complement them.
Pronunciation and the rendered videos were not part of this batch.
