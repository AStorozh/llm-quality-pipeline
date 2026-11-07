import unittest

from newlxp import style


class StyleTest(unittest.TestCase):
    def test_random_profile_is_valid(self):
        profile = style.random_profile()
        self.assertEqual(style.normalise(profile), profile)

    def test_normalise_fixes_bad_values(self):
        profile = style.normalise({"structure": 999, "tone": "x"})
        for axis in style.AXIS_ORDER:
            self.assertIn(profile[axis], range(len(style.AXES[axis])))

    def test_describe_and_suffix(self):
        profile = {"structure": 0, "tone": 0, "accent": 0}
        self.assertEqual([label for label, _ in style.describe(profile)],
                         ["Structure", "Tone", "Focus"])
        self.assertTrue(style.suffix(profile).startswith(" " + style.AXES["structure"][0]))
