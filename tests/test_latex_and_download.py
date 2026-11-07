"""Formulas written as LaTeX, and a download that must not run forever."""
import unittest
from unittest import mock

from newlxp import arithmetic, attachments, checks, coursework, polish


class LatexTest(unittest.TestCase):
    def test_common_markup_becomes_plain_text(self):
        self.assertEqual(polish.replace_latex("\\bar r_A = 21/12 = 1{,}75\\%"),
                         "r_A = 21/12 = 1,75%")
        self.assertEqual(polish.replace_latex("\\sigma_A = 2{,}3\\,\\%"), "σ_A = 2,3 %")
        self.assertEqual(polish.replace_latex("\\frac{a}{b} \\times 100"), "a / b × 100")
        self.assertEqual(polish.replace_latex("\\(a + b\\)"), "a + b")

    def test_ordinary_text_is_untouched(self):
        for text in ("Цена 100$ и 200$ за штуку", "C:\\Users\\Docs\\file.txt",
                     "Формула x^2 + y^2", "Обычный текст, 75%.", ""):
            self.assertEqual(polish.replace_latex(text), text)

    def test_it_is_part_of_clean_answer(self):
        self.assertIn("1,75%", polish.clean_answer("r = 21/12 = 1{,}75\\%"))

    def test_the_arithmetic_check_reads_it_as_the_document_will(self):
        self.assertEqual(arithmetic.find_errors("\\bar r_A = 21/12 = 1{,}75\\%"), [])
        self.assertEqual(len(arithmetic.find_errors("\\bar r = 18/26 = 62{,}9\\%")), 1)

    def test_the_check_reports_what_is_left(self):
        self.assertEqual(checks.check_no_latex("a \\frac{1}{2}").status, checks.WARN)
        self.assertEqual(checks.check_no_latex("1,75% за месяц").status, checks.PASS)

    def test_the_prompt_asks_for_plain_formulas(self):
        self.assertIn("LaTeX", coursework.output_rules("Рассчитайте показатели."))


class MeanOfPercentagesTest(unittest.TestCase):
    def test_a_mean_of_percentages_is_not_an_error(self):
        self.assertEqual(arithmetic.check_expressions("21 / 12 = 1,75%"), [])

    def test_a_share_is_still_checked(self):
        self.assertEqual(arithmetic.check_expressions("18 / 26 = 69,2%"), [])
        self.assertEqual(len(arithmetic.check_expressions("18 / 26 = 62,9%")), 1)


class SlowDownloadTest(unittest.TestCase):
    def response(self, chunks):
        handle = mock.MagicMock()
        handle.__enter__.return_value.read.side_effect = chunks
        return handle

    def test_a_download_that_keeps_trickling_is_given_up(self):
        full = b"x" * attachments._CHUNK_BYTES
        clock = iter([0, 10, 20, attachments.DOWNLOAD_DEADLINE + 1, 10_000])
        with mock.patch.object(attachments.urllib.request, "urlopen",
                               return_value=self.response([full] * 10)), \
                mock.patch.object(attachments.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaises(attachments.AttachmentError) as ctx:
                attachments._download("https://example.com/a.pdf")
        self.assertIn("дольше", str(ctx.exception))

    def test_a_normal_download_is_returned_whole(self):
        part = b"a" * attachments._CHUNK_BYTES
        with mock.patch.object(attachments.urllib.request, "urlopen",
                               return_value=self.response([part, part, b"tail"])):
            data = attachments._download("https://example.com/a.pdf")
        self.assertEqual(data, part + part + b"tail")

    def test_a_small_file_needs_one_read(self):
        with mock.patch.object(attachments.urllib.request, "urlopen",
                               return_value=self.response([b"small"])):
            self.assertEqual(attachments._download("https://example.com/a.txt"), b"small")


if __name__ == "__main__":
    unittest.main()
