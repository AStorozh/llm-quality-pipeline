"""The eval harness itself has to be trustworthy, so it is tested too."""
import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("evals_run", ROOT / "evals" / "run.py")
evals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evals)

from newlxp import ai, coursework, judge  # noqa: E402


class CaseFilesTest(unittest.TestCase):
    def test_every_case_is_well_formed(self):
        cases = evals.load_cases([])
        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            with self.subTest(case=case["name"]):
                for key in ("task", "work", "comment", "min_score"):
                    self.assertIn(key, case)
                self.assertGreater(len(case["work"].split()), 20)
                self.assertTrue(case["comment"].strip())

    def test_there_is_at_least_one_clean_baseline(self):
        clean = [c for c in evals.load_cases([]) if c.get("min_score") == 1.0]
        self.assertTrue(clean, "no baseline case to catch a general regression")

    def test_names_are_unique(self):
        names = [c["name"] for c in evals.load_cases([])]
        self.assertEqual(len(names), len(set(names)))


class RunnerTest(unittest.TestCase):
    def test_the_whole_suite_passes_today(self):
        outcomes = [evals.evaluate(case) for case in evals.load_cases([])]
        broken = [(o["case"]["name"], o["problems"]) for o in outcomes if o["problems"]]
        self.assertEqual(broken, [])

    def test_each_defect_case_really_catches_its_defect(self):
        for case in evals.load_cases([]):
            for name in case.get("must_fail", []):
                with self.subTest(case=case["name"], check=name):
                    statuses = {r.name: r.status
                                for r in evals.evaluate(case)["results"]}
                    self.assertEqual(statuses.get(name), "fail")

    def test_a_regression_is_reported_and_exits_non_zero(self):
        broken = {"name": "synthetic", "comment": "x", "min_score": 1.0,
                  "task": "Напишите эссе объёмом примерно 1500-2000 слов.",
                  "work": "Слишком короткая работа."}
        outcome = evals.evaluate(broken)
        self.assertTrue(outcome["problems"])
        self.assertLess(outcome["score"], 1.0)

    def test_filtering_by_name(self):
        one = evals.load_cases(["essay-baseline"])
        self.assertEqual([c["name"] for c in one], ["essay-baseline"])

    def test_main_exits_zero_and_prints_a_summary(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = evals.main([])
        self.assertEqual(code, 0)
        self.assertIn("regression(s)", buffer.getvalue())

    def test_json_output_is_machine_readable(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            evals.main(["--json"])
        rows = json.loads(buffer.getvalue())
        self.assertTrue(all({"name", "score", "checks"} <= set(r) for r in rows))


class JudgeCaseFilesTest(unittest.TestCase):
    """The calibration set is what makes the judge's scores believable."""

    def cases(self):
        return evals.load_cases([], evals.JUDGE_DIR)

    def test_every_case_is_well_formed(self):
        cases = self.cases()
        self.assertGreaterEqual(len(cases), 3)
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertTrue(case["task"].strip())
                self.assertGreater(len(case["work"].split()), 50)
                self.assertTrue(case["comment"].strip())
                for name, band in case["expected"].items():
                    self.assertIn(name, judge.RUBRIC)
                    low, high = band
                    self.assertTrue(1 <= low <= high <= 5, (name, band))

    def test_the_set_covers_both_ends_of_the_scale(self):
        bands = [b for c in self.cases() for b in c["expected"].values()]
        self.assertTrue(any(high <= 2 for _low, high in bands), "no weak work")
        self.assertTrue(any(low >= 4 for low, _high in bands), "no strong work")

    def test_the_works_are_the_same_length(self):
        # Otherwise the judge could be scoring length instead of quality.
        lengths = [len(c["work"].split()) for c in self.cases()]
        self.assertLess(max(lengths) - min(lengths), max(lengths) * 0.35,
                        "calibration works differ too much in length")

    def test_the_task_does_not_contradict_the_works(self):
        for case in self.cases():
            with self.subTest(case=case["name"]):
                floor = coursework.volume_floor(case["task"])
                if floor:
                    self.assertGreaterEqual(len(case["work"].split()), floor * 0.8,
                                            "the task asks for more than the "
                                            "fixture provides")


class LiveModeTest(unittest.TestCase):
    """The live path is exercised with a stubbed model, so it costs nothing."""

    CONFIG = {"provider": "openai", "api_key": "k", "model": "test-model"}

    def test_generation_retries_when_the_answer_is_short(self):
        short = ai.Answer("слово " * 50, "test-model", 10, 10)
        full = ai.Answer("слово " * 1600, "test-model", 10, 10)
        case = {"task": "Напишите эссе объёмом примерно 1500-2000 слов."}
        with mock.patch.object(ai, "complete", side_effect=[short, full]) as call:
            work, replies = evals.generate(self.CONFIG, case)
        self.assertEqual(call.call_count, 2, "no expansion request was made")
        self.assertEqual(len(replies), 2)
        self.assertGreater(len(work.split()), 1000)

    def test_generation_stops_at_one_call_when_long_enough(self):
        full = ai.Answer("слово " * 1600, "test-model", 10, 10)
        case = {"task": "Напишите эссе объёмом примерно 1500-2000 слов."}
        with mock.patch.object(ai, "complete", return_value=full) as call:
            evals.generate(self.CONFIG, case)
        self.assertEqual(call.call_count, 1)

    def test_only_baselines_are_regenerated_by_default(self):
        chosen = evals.live_cases(evals.load_cases([]))
        self.assertTrue(chosen)
        for case in chosen:
            self.assertEqual(case["min_score"], 1.0,
                             "a deliberately broken work would measure nothing")

    def test_a_live_run_is_filed_under_its_prompt_version(self):
        answer = ai.Answer("слово " * 1600, "test-model", 100, 200)
        cases = [{"name": "x", "task": "Эссе.", "work": "", "min_score": 1.0,
                  "comment": "c"}]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(evals, "RESULTS_DIR", pathlib.Path(tmp)), \
                mock.patch.object(ai, "complete", return_value=answer), \
                contextlib.redirect_stdout(io.StringIO()):
            record = evals.run_live(cases, self.CONFIG, False, False)
            saved = list(pathlib.Path(tmp).glob("*.json"))
        self.assertEqual(record["prompt_version"], coursework.prompt_version())
        self.assertEqual(record["model"], "test-model")
        self.assertEqual(record["tokens"], 300)
        self.assertEqual(len(saved), 1)

    def test_the_prompt_version_changes_with_the_prompt(self):
        before = coursework.prompt_version()
        with mock.patch.object(coursework, "SYSTEM_PROMPT",
                               coursework.SYSTEM_PROMPT + " и ещё правило."):
            self.assertNotEqual(coursework.prompt_version(), before)
        self.assertEqual(coursework.prompt_version(), before)
