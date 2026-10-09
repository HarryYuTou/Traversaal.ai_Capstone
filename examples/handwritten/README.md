# Hand-written storyboards (not pipeline output)

These five scene plans were written by hand in a Claude Code session on
2026-10-09, on Charles's Claude subscription. They were **not** produced by the
`capstone_script` planner and made no Claude API calls, so they are not test
results for the automatic pipeline and say nothing about its failure rate.

They exist to try the renderer on the kind of topics the client asked for
(history, science, not only AI), and to exercise the four templates the
planner prompts do not describe yet: timeline, stat, quote and map.

| File | Video | Scenes | Words |
| --- | --- | --- | --- |
| `silk-road.json` | The Silk Road: How Trade Connected Two Worlds | 25 | 1,199 |
| `world-war-two.json` | How World War II Reshaped the World | 24 | 1,126 |
| `first-emperor.json` | The First Emperor: How Qin Unified China | 23 | 1,137 |
| `apollo-11.json` | Apollo 11: How Humans Reached the Moon | 24 | 1,160 |
| `dinosaur-extinction.json` | The Day the Dinosaurs Died | 23 | 1,128 |

Facts were written from general knowledge, kept to widely documented claims,
and hedged where historians disagree (ancient casualty figures, the burning of
the books, the role of the Deccan volcanoes). Check them against sources before
publishing any of these videos.

Voice and render one locally, with no API key needed:

```bash
python -m capstone_script narrate --plan examples/handwritten/apollo-11.json --out runs/handwritten-apollo-11 --offline --threads 4
python -m capstone_script render --run runs/handwritten-apollo-11 --theme night --share
```
