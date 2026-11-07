"""Heading numbers that repeat or run backwards, and table rows printed twice."""
import unittest

from newlxp import checks


def work(*parts):
    return "\n\n".join(parts)


class NumberingTest(unittest.TestCase):
    def status(self, text):
        return checks.check_numbering(text).status

    def test_a_clean_numbered_work_passes(self):
        text = work("## 1. Цели", "Текст.", "## 2. Механика", "Текст.",
                    "## 2.1. Уровни", "Текст.", "## 3. Оценка", "Текст.")
        self.assertEqual(self.status(text), checks.PASS)

    def test_a_work_without_numbers_passes(self):
        self.assertEqual(self.status(work("## Введение", "Текст.", "## Вывод")), checks.PASS)

    def test_a_repeated_number_is_found(self):
        text = work("## 5. Сравнение", "Текст.", "## 5. План", "Текст.")
        result = checks.check_numbering(text)
        self.assertEqual(result.status, checks.WARN)
        self.assertIn("5", result.detail)

    def test_a_number_that_runs_backwards_is_found(self):
        text = work("## 1. Цели", "## 3. Оценка", "## 2. Механика")
        self.assertEqual(self.status(text), checks.WARN)

    def test_a_year_at_the_start_of_a_heading_is_not_a_number(self):
        text = work("## 2024 год в цифрах", "## 1. Итоги", "## 2023 год в цифрах")
        self.assertEqual(self.status(text), checks.PASS)

    def test_a_header_row_printed_twice_is_found(self):
        table = ("| Этап | Срок |\n|---|---|\n| Этап | Срок |\n|---|---|\n"
                 "| 1. Подготовка | 1 месяц |")
        result = checks.check_numbering(work("## 1. План", table))
        self.assertEqual(result.status, checks.WARN)
        self.assertIn("printed twice", result.detail)

    def test_a_normal_table_passes(self):
        table = "| Этап | Срок |\n|---|---|\n| 1. Подготовка | 1 месяц |\n| 2. Запуск | 2 месяц |"
        self.assertEqual(self.status(work("## 1. План", table)), checks.PASS)

    def test_it_is_part_of_the_standard_run(self):
        names = [r.name for r in checks.run("слово " * 80, {})]
        self.assertIn("numbering", names)

    def test_a_warning_does_not_lower_the_score(self):
        results = [checks.Result("a", checks.PASS), checks.check_numbering(
            work("## 1. А", "## 1. Б"))]
        self.assertEqual(checks.score(results), 1.0)


if __name__ == "__main__":
    unittest.main()
