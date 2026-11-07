import unittest
from unittest import mock

from newlxp import ai, judge

GOOD = {"compliance": 5, "depth": 4, "concreteness": 4, "coherence": 5,
        "comment": "Мало примеров."}
CONFIG = {"provider": "openai", "api_key": "k", "model": "m"}


def reply(text):
    return ai.Answer(text, "m", 100, 20)


class VerdictTest(unittest.TestCase):
    def test_scores_and_average(self):
        verdict = judge.Verdict("x", **{k: v for k, v in GOOD.items()
                                        if k != "comment"})
        self.assertEqual(verdict.scores["depth"], 4)
        self.assertAlmostEqual(verdict.average, 4.5)
        self.assertEqual(verdict.comment, "x")


class RateTest(unittest.TestCase):
    def rate(self, payload):
        with mock.patch.object(ai, "complete", return_value=reply(payload)) as call:
            return judge.rate(CONFIG, "работа", "задание"), call

    def test_a_valid_verdict(self):
        import json
        verdict, call = self.rate(json.dumps(GOOD, ensure_ascii=False))
        self.assertEqual(verdict.compliance, 5)
        self.assertEqual(verdict.comment, "Мало примеров.")
        self.assertTrue(call.call_args.kwargs.get("json_mode"))

    def test_the_task_is_included_when_given(self):
        import json
        with mock.patch.object(ai, "complete",
                               return_value=reply(json.dumps(GOOD))) as call:
            judge.rate(CONFIG, "работа", "задание")
        self.assertIn("задание", call.call_args[0][2])

    def test_a_fenced_reply_is_parsed(self):
        import json
        verdict, _ = self.rate("```json\n%s\n```" % json.dumps(GOOD))
        self.assertEqual(verdict.depth, 4)

    def test_a_malformed_reply_raises_rather_than_guessing(self):
        # A made-up score would quietly pollute the eval history.
        for payload in ("не могу оценить", "{broken", '{"compliance": 5}'):
            with self.assertRaises(ai.AIError, msg=payload):
                self.rate(payload)

    def test_a_score_outside_the_scale_is_rejected(self):
        import json
        bad = dict(GOOD, depth=9)
        with self.assertRaises(ai.AIError) as caught:
            self.rate(json.dumps(bad))
        self.assertIn("outside 1-5", str(caught.exception))

    def test_a_non_integer_score_is_rejected(self):
        import json
        with self.assertRaises(ai.AIError):
            self.rate(json.dumps(dict(GOOD, depth="высокая")))


class AgreementTest(unittest.TestCase):
    def verdict(self, **scores):
        return judge.Verdict("", **scores)

    def test_everything_inside_the_bands(self):
        stats = judge.agreement(
            [self.verdict(compliance=5, depth=4, concreteness=4, coherence=5)],
            [{"compliance": (4, 5), "depth": (4, 5)}])
        self.assertEqual(stats["rate"], 1.0)
        self.assertEqual(stats["mean_miss"], 0.0)
        self.assertEqual(stats["criteria"], 2)

    def test_a_miss_is_measured_by_distance(self):
        stats = judge.agreement(
            [self.verdict(compliance=1, depth=4, concreteness=4, coherence=5)],
            [{"compliance": (4, 5)}])
        self.assertEqual(stats["rate"], 0.0)
        self.assertEqual(stats["mean_miss"], 3.0)

    def test_no_expectations_means_full_agreement(self):
        self.assertEqual(judge.agreement([], [])["rate"], 1.0)


class RubricTest(unittest.TestCase):
    def test_the_schema_matches_the_rubric(self):
        for name in judge.RUBRIC:
            self.assertIn(name, judge.SCORE_SCHEMA["properties"])
            self.assertIn(name, judge.SCORE_SCHEMA["required"])
        self.assertIn("comment", judge.SCORE_SCHEMA["required"])

    def test_every_criterion_is_described_to_the_model(self):
        for name in judge.RUBRIC:
            self.assertIn(name, judge.SYSTEM)
