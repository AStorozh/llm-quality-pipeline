"""Defects found in real works: the checks must see them, and must not cry wolf."""
import unittest

from newlxp import arithmetic, checks, coursework, requirements


class TableCellArithmeticTest(unittest.TestCase):
    def findings(self, *rows):
        return arithmetic.check_row_expressions([["Расчет", "Значение"], *map(list, rows)])

    def test_a_wrong_result_in_the_next_cell_is_found(self):
        found = self.findings(("CAC = 42 690 / 63", "677,14 руб."))
        self.assertEqual(len(found), 1)
        self.assertIn("677,62", found[0])

    def test_a_right_result_passes(self):
        self.assertEqual(self.findings(("CAC = 42 690 / 63", "677,62 руб.")), [])

    def test_a_percent_with_the_hundred_written_out(self):
        self.assertEqual(self.findings(("CTR = 890 / 24 560 × 100%", "3,62%")), [])
        self.assertEqual(len(self.findings(("CTR = 890 / 24 560 × 100%", "4,62%"))), 1)

    def test_a_share_as_a_right_operand(self):
        self.assertEqual(self.findings(("Продажи = 82 × 13,415%", "11,0003")), [])
        self.assertEqual(len(self.findings(("Продажи = 82 × 13,415%", "10,9893"))), 1)

    def test_a_share_may_be_written_with_or_without_the_percent_sign(self):
        self.assertEqual(self.findings(("Доля = 3 / 4", "75%")), [])
        self.assertEqual(self.findings(("Доля = 3 / 4", "75")), [])
        self.assertEqual(self.findings(("Доля = 3 / 4", "0,75")), [])

    def test_a_period_is_not_a_subtraction(self):
        self.assertEqual(self.findings(("Месяцы 1 - 3", "50 000")), [])

    def test_a_subtraction_with_an_equals_sign_is_checked(self):
        self.assertEqual(self.findings(("Прибыль = 417 816 - 139 400", "278 416")), [])
        self.assertEqual(len(self.findings(("Прибыль = 417 816 - 139 400", "300 000"))), 1)

    def test_a_cell_followed_by_text_is_left_alone(self):
        self.assertEqual(self.findings(("CAC = 42 690 / 63", "см. ниже")), [])

    def test_it_is_part_of_the_standard_search(self):
        text = "| Расчет | Значение |\n|---|---|\n| CAC = 42 690 / 63 | 677,14 руб. |"
        self.assertEqual(len(arithmetic.find_errors(text)), 1)


class InlinePercentTest(unittest.TestCase):
    def test_a_hundred_written_out_is_checked(self):
        self.assertEqual(arithmetic.check_expressions("890 / 24 560 × 100% = 3,62%"), [])
        self.assertEqual(len(arithmetic.check_expressions("890 / 24 560 × 100% = 4,62%")), 1)

    def test_the_old_forms_are_unchanged(self):
        self.assertEqual(arithmetic.check_expressions("18 / 26 = 69,2%"), [])
        self.assertEqual(len(arithmetic.check_expressions("18 / 26 = 62,9%")), 1)
        self.assertEqual(arithmetic.check_expressions("300 000 / 340 ≈ 882"), [])


class SourceTellTest(unittest.TestCase):
    def hit(self, text):
        return checks.check_no_source_tells(text).status == checks.FAIL

    def test_references_to_the_source_are_found(self):
        for text in ("как сказано в материалах курса", "из материалов лекции",
                     "по материалам темы", "согласно материалам",
                     "логику из учебной темы"):
            self.assertTrue(self.hit(text), text)

    def test_a_conjunction_before_materials_is_not_a_reference(self):
        self.assertFalse(self.hit("расширять систему на другие каналы и материалы"))

    def test_the_word_alone_is_not_a_reference(self):
        self.assertFalse(self.hit("Материалы курса подготовлены заранее."))


class VolumeFalsePositiveTest(unittest.TestCase):
    TASK = ("Создайте контент-план. Это могут быть лонгриды на 5000 знаков, "
            "короткие посты на 500 или постеры на 50.")

    def test_the_size_of_posts_is_not_the_size_of_the_work(self):
        self.assertFalse(coursework.read_volume(self.TASK))

    def test_a_work_that_is_a_post_still_has_its_size(self):
        self.assertEqual(coursework.read_volume("Напишите пост на 500 слов.").floor, 500)

    def test_an_essay_size_is_unchanged(self):
        self.assertEqual(
            coursework.read_volume("Объём эссе - 1500-2000 слов.").ceiling, 2000)


class AppendixFalsePositiveTest(unittest.TestCase):
    def test_software_is_not_an_appendix(self):
        for text in ("используйте специализированные приложения для управления контентом",
                     "статистику использования приложений и другие данные"):
            self.assertFalse(requirements.mentions_appendix(text), text)

    def test_a_real_appendix_is_still_found(self):
        self.assertTrue(requirements.mentions_appendix(
            "Оформите образец регламента в приложении к работе."))


if __name__ == "__main__":
    unittest.main()
