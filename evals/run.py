#!/usr/bin/env python3
"""Score the eval cases and report regressions.

    python3 evals/run.py                 the offline gate: stored works, no API
    python3 evals/run.py --verbose       show every check, not only failures
    python3 evals/run.py --json          machine-readable, for CI

    python3 evals/run.py --live          regenerate the works with the real
                                         model and score those (costs money)
    python3 evals/run.py --judge         rate the fresh works with the rubric
    python3 evals/run.py --calibrate     check the judge against known work
    python3 evals/run.py --history       compare recorded live runs

The offline gate is what CI runs: it needs no key, and it catches a
regression in the pipeline. A live run measures the model instead, and every
result is filed under the prompt fingerprint that produced it, so two runs
can be compared.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from newlxp import (  # noqa: E402 - needs the path above
    ai,
    checks,
    config,
    coursework,
    judge,
    polish,
    requirements,
    style,
    usage,
)

HERE = pathlib.Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"
JUDGE_DIR = HERE / "judge_cases"
RESULTS_DIR = HERE / "results"

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    ("\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")
    if sys.stdout.isatty() else ("", "", "", "", "", ""))
MARK = {checks.PASS: "ok", checks.WARN: "warn", checks.FAIL: "FAIL"}
SHADE = {checks.PASS: GREEN, checks.WARN: YELLOW, checks.FAIL: RED}


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #

def load_cases(names, directory: pathlib.Path = CASES_DIR) -> list:
    cases = []
    for path in sorted(directory.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        case.setdefault("name", path.stem)
        if not names or case["name"] in names:
            cases.append(case)
    return cases


def evaluate(case: dict, work: str | None = None) -> dict:
    """Run the checks for one case and decide whether it passed."""
    work = case["work"] if work is None else work
    checklist = requirements.from_text(case["task"])
    results = checks.run(work, checklist, case.get("materials", ""))
    score = checks.score(results)
    failed = {r.name for r in results if r.status == checks.FAIL}

    problems = []
    floor = case.get("min_score", 1.0)
    if score < floor:
        problems.append("scored %.2f, floor is %.2f" % (score, floor))
    for name in case.get("must_fail", []):
        if name not in failed:
            problems.append("check %r no longer catches this defect" % name)
    return {"case": case, "results": results, "score": score, "problems": problems}


def report(outcome: dict, verbose: bool) -> None:
    case, score, problems = outcome["case"], outcome["score"], outcome["problems"]
    colour = RED if problems else GREEN
    print("%s%-28s %3d%%%s  %s" % (colour, case["name"], round(score * 100), RESET,
                                   case.get("comment", "")))
    for result in outcome["results"]:
        if verbose or result.status != checks.PASS:
            print("    %s%-5s%s %-22s %s" % (SHADE[result.status],
                                             MARK[result.status], RESET,
                                             result.name, result.detail))
    if "verdict" in outcome and outcome["verdict"]:
        verdict = outcome["verdict"]
        print("    %sjudge%s %s  avg %.1f  %s"
              % (DIM, RESET,
                 " ".join("%s %d" % (n[:4], v) for n, v in verdict.scores.items()),
                 verdict.average, verdict.comment[:60]))
    for problem in problems:
        print("    %s>>> %s%s" % (RED, problem, RESET))


# --------------------------------------------------------------------------- #
# Live runs: the model, not the stored text
# --------------------------------------------------------------------------- #

def live_cases(cases: list) -> list:
    """Cases worth regenerating: the clean baselines, unless asked otherwise.

    Defect cases hold a deliberately broken work, so regenerating them would
    measure nothing.
    """
    return [c for c in cases if c.get("min_score") == 1.0]


def generate(cfg: dict, case: dict) -> tuple:
    """Produce a fresh work for a case, exactly as the client would.

    That includes the follow-up request when the first answer falls short of
    a length the task states: the point is to measure the pipeline a user
    actually gets, not a single call.
    """
    task = case["task"]
    system = coursework.system_prompt("", "", slides=False) \
        + style.suffix(style.random_profile())
    replies = [ai.complete(cfg, system, task + "\n\n" + coursework.output_rules(task))]
    work = polish.clean_answer(replies[0].text)

    floor = coursework.volume_floor(task)
    if floor and len(work.split()) < floor * coursework.VOLUME_TOLERANCE:
        replies.append(ai.complete(cfg, system,
                                   coursework.expansion_prompt(work, task)))
        work = polish.clean_answer(replies[-1].text)
    return work, replies


def run_live(cases: list, cfg: dict, want_judge: bool, verbose: bool) -> dict:
    """Regenerate each case, score it, and file the result."""
    outcomes, runs = [], []
    for case in cases:
        print("%s... generating %s%s" % (DIM, case["name"], RESET))
        work, replies = generate(cfg, case)
        runs.append(usage.Run(cfg["model"],
                              sum(r.input_tokens for r in replies),
                              sum(r.output_tokens for r in replies),
                              "eval:" + case["name"]))
        outcome = evaluate(case, work)
        outcome["work"] = work
        if want_judge:
            try:
                outcome["verdict"] = judge.rate(cfg, work, case["task"])
            except ai.AIError as exc:
                print("    %sjudge failed: %s%s" % (YELLOW, exc, RESET))
                outcome["verdict"] = None
        outcomes.append(outcome)
        report(outcome, verbose)

    record = {
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "prompt_version": coursework.prompt_version(),
        "model": cfg["model"],
        "average": sum(o["score"] for o in outcomes) / len(outcomes),
        "cases": {o["case"]["name"]: round(o["score"], 3) for o in outcomes},
        "judge": {o["case"]["name"]: round(o["verdict"].average, 2)
                  for o in outcomes if o.get("verdict")},
        "tokens": sum(r.total_tokens for r in runs),
    }
    _save(record)
    print("\n  %sprompt %s · model %s · %s tokens%s"
          % (DIM, record["prompt_version"], record["model"],
             record["tokens"], RESET))
    return record


def _save(record: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    name = record["when"].replace(":", "-") + ".json"
    (RESULTS_DIR / name).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("  %ssaved to %s%s" % (DIM, RESULTS_DIR / name, RESET))


def show_history() -> int:
    records = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
    if not records:
        print("No live runs recorded yet. Run: python3 evals/run.py --live")
        return 0
    print("%-20s %-10s %-16s %6s %6s" % ("when", "prompt", "model", "checks", "judge"))
    for record in records:
        judged = record.get("judge") or {}
        average_judge = (sum(judged.values()) / len(judged)) if judged else None
        print("%-20s %-10s %-16s %5d%% %6s"
              % (record.get("when", "?")[:19], record.get("prompt_version", "?"),
                 str(record.get("model", "?"))[:16],
                 round(record.get("average", 0) * 100),
                 "%.1f" % average_judge if average_judge is not None else "-"))
    return 0


# --------------------------------------------------------------------------- #
# Calibration: is the judge worth listening to?
# --------------------------------------------------------------------------- #

def run_calibration(cfg: dict) -> int:
    cases = load_cases([], JUDGE_DIR)
    if not cases:
        print("No calibration cases in %s: nothing to check the judge against."
              % JUDGE_DIR)
        return 1
    verdicts, expected = [], []
    for case in cases:
        print("%s... judging %s%s" % (DIM, case["name"], RESET))
        try:
            verdict = judge.rate(cfg, case["work"], case["task"])
        except ai.AIError as exc:
            print("  %sfailed: %s%s" % (RED, exc, RESET))
            return 1
        verdicts.append(verdict)
        expected.append({k: tuple(v) for k, v in case["expected"].items()})
        for name, (low, high) in sorted(case["expected"].items()):
            value = getattr(verdict, name)
            ok = low <= value <= high
            print("    %s%-14s %d  expected %d-%d%s"
                  % (GREEN if ok else RED, name, value, low, high, RESET))
        print("    %s%s%s" % (DIM, verdict.comment[:70], RESET))

    stats = judge.agreement(verdicts, expected)
    print("\n  %d of %d criteria inside their band (%d%%), mean miss %.2f"
          % (stats["inside_band"], stats["criteria"], round(stats["rate"] * 100),
             stats["mean_miss"]))
    if stats["rate"] < 0.8:
        print("  %sThe judge disagrees with known-quality work: do not trust its "
              "scores until the rubric is fixed.%s" % (RED, RESET))
        return 1
    print("  %sThe judge separates good work from filler; its scores are usable."
          "%s" % (GREEN, RESET))
    return 0


# --------------------------------------------------------------------------- #

def _require_key():
    cfg = config.load()
    if not cfg:
        print("No AI key configured. Set one in the client first (AI settings).")
        return None
    return cfg


def _confirm(count: int, extra: int) -> bool:
    total = count + extra
    print("This makes %d request(s) to %s and is billed to your account."
          % (total, config.load()["model"]))
    try:
        return input("Continue? (y / Enter to cancel): ").strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="run only these cases")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show every check, not only the failures")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="machine-readable output, for CI")
    parser.add_argument("--live", action="store_true",
                        help="regenerate the works with the real model")
    parser.add_argument("--judge", action="store_true",
                        help="also rate the fresh works against the rubric")
    parser.add_argument("--calibrate", action="store_true",
                        help="check the judge against known-quality work")
    parser.add_argument("--history", action="store_true",
                        help="compare the recorded live runs")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="do not ask before spending money")
    args = parser.parse_args(argv)

    if args.history:
        return show_history()

    if args.calibrate:
        cfg = _require_key()
        if cfg is None:
            return 1
        if not args.yes and not _confirm(len(load_cases([], JUDGE_DIR)), 0):
            return 1
        return run_calibration(cfg)

    cases = load_cases(args.names)
    if not cases:
        print("no cases found in %s" % CASES_DIR)
        return 1

    if args.judge and not args.live:
        print("--judge rates freshly generated work, so it needs --live.")
        return 1

    if args.live:
        cfg = _require_key()
        if cfg is None:
            return 1
        chosen = cases if args.names else live_cases(cases)
        if not chosen:
            print("No baseline case to regenerate. Name a case explicitly, or "
                  "mark one with \"min_score\": 1.0.")
            return 1
        if not args.yes and not _confirm(len(chosen), len(chosen) if args.judge else 0):
            return 1
        record = run_live(chosen, cfg, args.judge, args.verbose)
        return 0 if record["average"] >= 0.9 else 1

    outcomes = [evaluate(case) for case in cases]
    if args.as_json:
        print(json.dumps([{
            "name": o["case"]["name"], "score": round(o["score"], 3),
            "problems": o["problems"],
            "checks": {r.name: r.status for r in o["results"]},
        } for o in outcomes], ensure_ascii=False, indent=2))
    else:
        for outcome in outcomes:
            report(outcome, args.verbose)

    broken = [o for o in outcomes if o["problems"]]
    average = sum(o["score"] for o in outcomes) / len(outcomes)
    if not args.as_json:
        print("\n%d case(s), average score %d%%, %d regression(s)"
              % (len(outcomes), round(average * 100), len(broken)))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
