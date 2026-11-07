"""Long expressions are judged as a whole, not by their last pair."""
import unittest

from newlxp import arithmetic


class ChainTest(unittest.TestCase):
    def found(self, text):
        return arithmetic.find_errors(text)

    def test_a_correct_weighted_sum_passes(self):
        self.assertEqual(self.found(
            "r = 0,2 × 1,75 + 0,6 × 1,83 + 0,2 × 3,33 = 2,11%"), [])

    def test_a_wrong_weighted_sum_is_found_with_the_right_value(self):
        found = self.found("r = 0,3 × 1,75 + 0,3 × 1,83 + 0,4 × 3,33 = 2,50%")
        self.assertEqual(len(found), 1)
        self.assertIn("2,41", found[0])

    def test_sums_and_differences(self):
        self.assertEqual(self.found("29,91 + 0,33 + 1,55 - 1,88 - 1,36 + 0,29 = 28,84"), [])
        self.assertEqual(len(self.found("29,91 + 0,33 + 1,55 - 1,88 - 1,36 + 0,29 = 30,84")), 1)

    def test_missing_brackets_are_found(self):
        self.assertEqual(len(self.found("S = 10,54 - 8 / 5,37 = 2,54")), 1)
        self.assertEqual(self.found("S = (10,54 - 8) / 5,37 = 2,54 / 5,37 ≈ 0,47"), [])

    def test_the_last_pair_of_a_chain_is_not_judged_alone(self):
        self.assertEqual(self.found("0,5 × 2 + 3 × 4 = 13"), [])

    def test_a_dash_in_prose_is_not_an_operator(self):
        self.assertEqual(self.found("цель - 18 / 26 = 69,2%"), [])

    def test_a_line_with_two_equals_signs_is_not_misread(self):
        line = "r = 0,1 × 10,4 + 0,6 × 9,4 + 0,3 × 13,6 = 1,04 + 5,64 + 4,08 = 10,76%"
        self.assertEqual(self.found(line), [])
        self.assertEqual(len(self.found(line.replace("= 10,76%", "= 11,76%"))), 1)

    def test_two_numbers_are_still_checked_as_before(self):
        self.assertEqual(self.found("5 × 3 = 15"), [])
        self.assertEqual(len(self.found("5 × 3 = 16")), 1)


if __name__ == "__main__":
    unittest.main()
