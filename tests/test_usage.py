import json

from helpers import TempDirTestCase

from newlxp import usage

PRICES = {"m1": {"input": 1.0, "output": 2.0}}


class RunTest(TempDirTestCase):
    def test_cost_needs_a_price(self):
        run = usage.Run("m1", 1_000_000, 500_000)
        self.assertAlmostEqual(run.cost(PRICES), 1.0 + 1.0)
        self.assertIsNone(usage.Run("unknown", 10, 10).cost(PRICES))

    def test_totals(self):
        run = usage.Run("m1", 300, 700)
        self.assertEqual(run.total_tokens, 1000)

    def test_prices_merge_config_over_defaults(self):
        merged = usage.prices({"prices": {"gpt-4o-mini": {"input": 9.0, "output": 9.0}}})
        self.assertEqual(merged["gpt-4o-mini"]["input"], 9.0)
        self.assertIn("gpt-4o", merged)  # defaults still there
        self.assertEqual(usage.prices({"prices": "nonsense"}), usage.DEFAULT_PRICES)

    def test_log_round_trip(self):
        path = self.path("usage.jsonl")
        self.assertTrue(usage.record(usage.Run("m1", 10, 20, "КТ1", 1.5), path))
        self.assertTrue(usage.record(usage.Run("m1", 30, 40, "КТ2"), path))
        runs = usage.read_log(path)
        self.assertEqual([r.label for r in runs], ["КТ1", "КТ2"])
        self.assertEqual(runs[0].input_tokens, 10)

    def test_log_survives_a_corrupt_line(self):
        path = self.path("usage.jsonl")
        usage.record(usage.Run("m1", 10, 20), path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
            handle.write(json.dumps({"no": "model"}) + "\n")
        self.assertEqual(len(usage.read_log(path)), 1)

    def test_missing_log_is_empty_not_an_error(self):
        self.assertEqual(usage.read_log(self.path("nope.jsonl")), [])

    def test_summary(self):
        runs = [usage.Run("m1", 1_000_000, 0), usage.Run("unknown", 500, 500)]
        total = usage.summarise(runs, PRICES)
        self.assertEqual(total["requests"], 2)
        self.assertEqual(total["total_tokens"], 1_001_000)
        self.assertAlmostEqual(total["cost"], 1.0)   # only the priced run counts
        self.assertEqual(total["priced_requests"], 1)

    def test_summary_without_any_price(self):
        self.assertIsNone(usage.summarise([usage.Run("unknown", 1, 1)], PRICES)["cost"])

    def test_format_run(self):
        line = usage.format_run(usage.Run("m1", 1_000_000, 0), PRICES)
        self.assertIn("1 000 000 in", line)
        self.assertIn("$1.0000", line)
        self.assertNotIn("$", usage.format_run(usage.Run("unknown", 5, 5), PRICES))
