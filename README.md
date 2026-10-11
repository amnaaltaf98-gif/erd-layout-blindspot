# Can a small model draw an ERD without lines hitting tables?

Model tested: [Qwen/Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct), greedy decoding. 40 synthetic schemas, canvas 3100 x 2900.

## 1. The blind spot

A problem I have seen when asking AI tools to draw E-R diagrams is that they cannot perform basic two-dimensional spatial reasoning. In my experimentation, 37 out of 40 initial attempts successfully generated valid JSON that correctly included all the required relationships. Industry standard benchmarks would consider this an outstanding success rate, since most of these models simply check if the text formatting and data keys are correct. However, these diagrams had substantially worse layouts than randomized placement at every table size. I realized this when I saw how many of the diagrams simply had spaghetti-like crossings of lines. This is an unacceptable waste of a potentially valuable tool, because the entire point of an E-R diagram is to be easily readable by humans. The error is in the design of benchmarks that only penalize minor issues of text syntax rather than overall visual readability.

### What I saw when I looked at the outputs

Judging by the results, the model underperformed significantly for every table set size compared to randomly placed tables. For the 5-table setup, the model scored 5.9 flaws compared to the random placement baseline of 2.08, and for the 16-table setup, it scored 79.88 compared to the baseline of 51.92. In some of the visual examples I looked at, the model appeared to be arranging the tables one after another, either in a straight line or a diagonal. As a result, the connecting lines were intersecting the table bodies. When asked to fix these issues, the model was unable to do so, with none of the rearranged layouts being different compared to the initial ones when using the plain prompt. Providing the model with the exact computed flaws reduced the score by 56.8% on average (73.5 flaws for the 16-table setup) but with significantly varying results between the rounds (the second round, for instance, scored 23.7% worse than the first). And even with the reduced number of flaws, the model’s results are still far from the Graphviz baseline of 3.9 flaws.

## 2. How I tested it

**Model.** Qwen2.5-3B-Instruct has 3B parameters, inside the 0.6 to 6B range, has open weights, and fits in fp16 on a free Colab T4 GPU. It is a small model, not a frontier model. I did not test larger models, so these results show the gap at this scale and I cannot say how much of it carries over to frontier models.

**Data.** 40 random connected schemas with 5, 8, 12, 16 tables (same number of each size, seed 42). Each schema has the foreign keys of a tree plus extra ones equal to about 40 percent of the number of tables, so the graphs contain cycles. Table width is fixed at 200 and height depends on the number of columns. The model is told these sizes and must choose only the top left (x, y) of every table. The relationships are given, so the model cannot drop or invent a line. Every failure measured is a placement failure.

**Scoring.** Each relationship is drawn as a straight line between table centers. A layout's problem count is the number of overlapping table pairs, plus pairs of crossing lines that share no table, plus (line, table) pairs where a line passes through a table that is not one of its two ends. Tables outside the canvas are counted separately.

**References.** Graphviz neato on the same sizes (a layout engine, so it shows what is achievable; it is not always zero because dense graphs force some crossings), and random placement (5 random layouts per schema).

**Repair test.** After round 0, the model was told "Make sure the lines are not overlapping. Return the full JSON." for 3 rounds, with the whole conversation kept in context. **Control.** The same rounds, but the prompt listed the exact problems found by the scoring code (for example which line crosses which line), up to 15 per round.

## Results

At 5 tables Qwen2.5-3B averaged 5.9 layout problems per diagram (Graphviz neato: 0.5, random placement: 2.08). At 16 tables it averaged 79.88 (Graphviz neato: 3.9, random placement: 51.92).

37 of 40 first attempts were valid JSON with every table present. All averages above use valid layouts only.

With the prompt "Make sure the lines are not overlapping", 34 schemas had a valid layout both before and after 3 repair rounds. Compared with round 0, 0.0% ended worse, 100.0% unchanged and 0.0% better (mean change in problems: 0.0).

Share of single repair rounds that made the layout worse: round 1: 0.0% worse (34 schemas); round 2: 0.0% worse (35 schemas); round 3: 5.7% worse (35 schemas).

With the computed feedback prompt, 37 schemas had a valid layout before and after 3 rounds. 10.8% ended worse, 32.4% unchanged and 56.8% better (mean change: -5.05).

The mean change with computed feedback was lower than the change with the vague prompt (-5.05 versus 0.0). The two groups can contain different schemas, so compare the full tables below before drawing conclusions.

### Average problems per layout (lower is better)

| tables | Graphviz neato | Random placement | Qwen2.5-3B round 0 |
|---|---|---|---|
| 5 | 0.5 | 2.08 | 5.9 |
| 8 | 0.9 | 9.16 | 23.1 |
| 12 | 2.6 | 25.16 | 54.78 |
| 16 | 3.9 | 51.92 | 79.88 |

### Problems per foreign key

| tables | Graphviz neato | Random placement | Qwen2.5-3B round 0 |
|---|---|---|---|
| 5 | 0.08 | 0.35 | 0.98 |
| 8 | 0.09 | 0.92 | 2.31 |
| 12 | 0.16 | 1.57 | 3.42 |
| 16 | 0.19 | 2.47 | 3.8 |

### Valid JSON layouts on the first attempt

| tables | valid layouts | schemas | share valid |
|---|---|---|---|
| 5 | 10 | 10 | 1.0 |
| 8 | 10 | 10 | 1.0 |
| 12 | 9 | 10 | 0.9 |
| 16 | 8 | 10 | 0.8 |

### What kind of problems the model's first attempts had

| tables | table overlaps | line crossings | lines through tables | tables off canvas |
|---|---|---|---|---|
| 5 | 0.4 | 0.9 | 4.6 | 0.0 |
| 8 | 1.3 | 9.0 | 12.8 | 0.0 |
| 12 | 2.56 | 24.56 | 27.67 | 0.0 |
| 16 | 2.38 | 32.75 | 44.75 | 0.12 |

### Average problems by repair round, prompt: "make sure the lines are not overlapping"

Only schemas with a valid layout in every round are averaged, so the rounds are comparable. Schemas per size: 5 tables: 10, 8 tables: 10, 12 tables: 9, 16 tables: 5.

| tables | round 0 | round 1 | round 2 | round 3 |
|---|---|---|---|---|
| 5 | 5.9 | 5.9 | 5.9 | 5.9 |
| 8 | 23.1 | 23.1 | 21.7 | 23.1 |
| 12 | 54.8 | 54.8 | 54.8 | 54.8 |
| 16 | 97.2 | 97.2 | 97.2 | 97.2 |

### Average problems by repair round, prompt: computed feedback (control)

Only schemas with a valid layout in every round are averaged, so the rounds are comparable. Schemas per size: 5 tables: 10, 8 tables: 10, 12 tables: 9, 16 tables: 8.

| tables | round 0 | round 1 | round 2 | round 3 |
|---|---|---|---|---|
| 5 | 5.9 | 4.7 | 6.3 | 4.4 |
| 8 | 23.1 | 18.5 | 19.2 | 19.2 |
| 12 | 54.8 | 41.6 | 47.7 | 45.7 |
| 16 | 79.9 | 76.6 | 77.1 | 73.5 |

### Did a repair round make the layout worse?

| condition | round | n | worse_% | same_% | better_% | mean_change |
|---|---|---|---|---|---|---|
| plain | 1 | 34 | 0.0 | 100.0 | 0.0 | 0.0 |
| plain | 2 | 35 | 0.0 | 94.3 | 5.7 | -0.4 |
| plain | 3 | 35 | 5.7 | 94.3 | 0.0 | 0.4 |
| plain | 0 to 3 | 34 | 0.0 | 100.0 | 0.0 | 0.0 |
| feedback | 1 | 37 | 10.8 | 32.4 | 56.8 | -5.49 |
| feedback | 2 | 38 | 23.7 | 71.1 | 5.3 | 2.16 |
| feedback | 3 | 38 | 7.9 | 68.4 | 23.7 | -1.74 |
| feedback | 0 to 3 | 37 | 10.8 | 32.4 | 56.8 | -5.05 |

### Limits of this study

- One model, one prompt wording, greedy decoding, 40 schemas. Differences between small groups can be noise.
- Lines are straight center to center segments. Real ERD tools route lines differently, so absolute counts are specific to this metric.
- Averages use valid layouts only. Invalid outputs are reported separately.
- The Graphviz reference is a good layout engine, not a proof of the minimum number of crossings.

## 3. Path forward

I believe AI models currently see coordinates just as text, without understanding them as real physical spaces on a grid. To fix this, we need to build an automated grader that counts every overlapping box and crossed line. We can use this score to train the AI, actively rewarding it for creating cleaner diagrams so it learns to spread things out. Another option is to have the AI generate several different layouts behind the scenes, use that same grader to quickly score them, and only show us the neatest one. Just forcing the AI to copy good examples isn't enough, because it will likely just memorize the text patterns instead of actually learning how to draw a readable map.

## Files in this bucket

- `README.md` this file
- `erd_eval.py` the full code: dataset generation, scoring, model runs, analysis
- `schemas.json` the 40 evaluation schemas with table sizes
- `round0_raw.json`, `repair_raw.json`, `feedback_raw.json` raw model outputs
- `model_scores.csv`, `baseline_scores.csv`, `regression_rates.csv`, `results_summary.md` scores and tables
- `figures/` plots and before and after layout images
- `config.json` canvas size, seed and model id
- `model/` copy of the model weights, if the copy step succeeded

To reproduce: run `python erd_eval.py --workdir out` on a GPU machine with transformers, accelerate, shapely, networkx, pandas, matplotlib and Graphviz installed.
