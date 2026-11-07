# Evals

A quality gate for the generated documents. Before this existed, "did that
prompt change help?" could only be answered by reading the output.

There are two levels, and they measure different things.

## The offline gate

```bash
python3 evals/run.py              # score every case, exit non-zero on a regression
python3 evals/run.py --verbose    # list every check, not just the failures
python3 evals/run.py --json       # machine-readable, for CI
```

Needs no API key and makes no network calls: the works are stored in
`cases/`. This measures **the pipeline** - the checks themselves, the
post-processing, the requirement parsing. It runs in CI on every push to main and every pull request.

Each case pairs a task with a work and the score that work must reach:

- **Regressions** (`must_fail`) hold a work that once shipped with a real
  defect - leftover chat text, an invented figure, a missing appendix. The
  case pins the defect so it cannot come back unnoticed.
- **Baselines** (`min_score: 1.0`) hold a clean work, so a change that makes
  things worse is caught immediately.

## The live run

```bash
python3 evals/run.py --live            # regenerate the baselines, score them
python3 evals/run.py --live --judge    # and rate them against the rubric
python3 evals/run.py --history         # compare the recorded runs
```

This measures **the model**, not the pipeline: each baseline case is
regenerated through the real client path, including the follow-up request
when the first answer is too short. It costs money, so it asks before
spending any and only regenerates the baselines by default.

Every run is filed in `results/` with the model, the date and the
fingerprint of the prompt that produced it, which is the point: a score with
no prompt attached cannot be compared to anything.

```
when                 prompt     model            checks  judge
2026-10-10T02:37:23  54c29aad   gpt-5.4-mini       100%    4.4
```

## The judge, and why it is calibrated

The checks answer "is the required section there". They cannot answer "is
the reasoning any good", which is what most marks are actually for. For that
there is a rubric in [`newlxp/judge.py`](../newlxp/judge.py): four criteria,
scored one to five, returned as validated JSON.

A judge nobody checked is just the model agreeing with itself, so:

```bash
python3 evals/run.py --calibrate
```

runs it over `judge_cases/` - works of deliberately different quality, all
the same length so the judge cannot mistake length for quality - and reports
how often it lands inside the expected band. Below 80% it says the scores
are not usable.

Two of those cases were rewritten rather than the judge blamed: the first
"off-topic" fixture was management text with a few words find-and-replaced,
which the judge correctly read as on-topic, and one band asked for a higher
coherence score than a text that repeats itself deserves. The comments in
the case files record both corrections.

## Adding a case

Save a task and a work you have already generated into `cases/`, record the
score the checks give it today, and add `must_fail` if the case exists to pin
a specific defect. For a judge case, put the work in `judge_cases/` with the
band each criterion should land in and a note on why.
