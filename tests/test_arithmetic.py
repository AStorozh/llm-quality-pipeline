import unittest

from newlxp import arithmetic, checks, requirements

RFM = """| Клиент | Последняя покупка | Дней с последней покупки | Покупок |
|---|---|---|---|
| К1 | 20.02.2026 | 9 | 14 |
| К2 | 10.01.2026 | 50 | 9 |
| К3 | 16.10.2025 | 137 | 2 |
| К4 | 28.02.2026 | 1 | 16 |
"""

MEDIA = """| Канал | Бюджет, руб. | Ожидаемый CTR / отклик | Стоимость заявки, руб. | Число заявок |
|---|---|---|---|---|
| Директ | 150 000 | 3,0% | 750 | 210 |
| Таргет | 100 000 | 1,5% | 1000 | 100 |
| Блогеры | 50 000 | 2,0% | 1250 | 40 |
| Итого | 300 000 | - | - | 350 |
"""


class ExpressionTest(unittest.TestCase):
    def test_wrong_ratio_is_reported_with_the_right_value(self):
        self.assertEqual(arithmetic.check_expressions("удержание 18 / 26 = 62,9%."),
                         ["«18 / 26 = 62,9%»: должно быть 69,2%"])

    def test_right_figures_pass(self):
        text = ("18 / 26 = 69,2%, 300 000 / 340 ≈ 882 рубля, 5 × 120 = 600, "
                "120 + 30 = 150, 10 - 4 = 6")
        self.assertEqual(arithmetic.check_expressions(text), [])

    def test_approximately_allows_rounding(self):
        self.assertEqual(arithmetic.check_expressions("330 000 / 340 ≈ 970"), [])

    def test_parse_number(self):
        self.assertEqual(arithmetic.parse_number("1 234,5 руб."), 1234.5)
        self.assertEqual(arithmetic.parse_number("69,2%"), 69.2)
        self.assertIsNone(arithmetic.parse_number("1-3 месяц"))


class TableTest(unittest.TestCase):
    def test_day_count_from_a_shared_date(self):
        self.assertEqual(arithmetic.find_errors(RFM), [
            "таблица, «К3», Дней с последней покупки: 137, а от 16.10.2025 до 01.03.2026 - 136"])

    def test_leads_are_budget_over_cost(self):
        # The total (350) does add up: only the Директ row is wrong.
        findings = arithmetic.find_errors(MEDIA)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("«Директ», Число заявок: 210", findings[0])
        self.assertIn("= 200", findings[0])

    def test_correct_table_passes(self):
        fixed = MEDIA.replace("| 210 |", "| 200 |").replace("| 350 |", "| 340 |")
        self.assertEqual(arithmetic.find_errors(fixed), [])

    def test_wrong_total(self):
        wrong = (MEDIA.replace("| 210 |", "| 200 |").replace("| 350 |", "| 340 |")
                 .replace("| 300 000 | - |", "| 310 000 | - |"))
        self.assertEqual(arithmetic.find_errors(wrong), [
            "таблица «Бюджет, руб.», строка «Итого»: 310 000, а сумма строк выше - 300 000"])

    def test_a_rate_column_total_is_not_summed(self):
        table = "| Канал | CTR, % |\n|--|--|\n| А | 2 |\n| Б | 4 |\n| Итого | 3 |"
        self.assertEqual(arithmetic.find_errors(table), [])

    def test_inferred_relation_flags_the_odd_row(self):
        table = ("| Товар | Цена | Кол-во | Сумма |\n|--|--|--|--|\n"
                 "| А | 10 | 3 | 30 |\n| Б | 20 | 2 | 40 |\n| В | 5 | 4 | 20 |\n"
                 "| Г | 7 | 3 | 25 |")
        findings = arithmetic.find_errors(table)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("«Г», Сумма: 25", findings[0])
        self.assertIn("= 21", findings[0])

    def test_unrelated_small_numbers_raise_nothing(self):
        table = ("| Неделя | Постов | Видео |\n|--|--|--|\n| 1 | 3 | 1 |\n"
                 "| 2 | 4 | 0 |\n| 3 | 2 | 1 |\n| 4 | 5 | 2 |")
        self.assertEqual(arithmetic.find_errors(table), [])


class ChecksTest(unittest.TestCase):
    def status(self, work, task):
        results = checks.run(work, requirements.from_text(task))
        return {r.name: r.status for r in results}

    def test_calculation_task_without_a_table_fails(self):
        statuses = self.status("Слово " * 200, "Рассчитайте RFM для 30 клиентов.")
        self.assertEqual(statuses["calculations"], checks.FAIL)

    def test_calculation_task_with_a_table_passes(self):
        work = "Расчёт ниже.\n\n" + MEDIA.replace("| 210 |", "| 200 |").replace("| 350 |", "| 340 |")
        statuses = self.status(work, "Разработайте медиаплан и рассчитайте бюджет.")
        self.assertEqual(statuses["calculations"], checks.PASS)
        self.assertEqual(statuses["arithmetic"], checks.PASS)

    def test_essay_task_needs_no_calculation(self):
        self.assertFalse(requirements.from_text("Напишите эссе о лидерстве.")["needs_calculation"])

    def test_comma_instead_of_a_dash_is_flagged(self):
        statuses = self.status("Работа. Главная цель, это рост продаж. " * 20, "Эссе.")
        self.assertEqual(statuses["no comma dashes"], checks.WARN)
        statuses = self.status("Работа. Он ушёл рано, это было видно. " * 20, "Эссе.")
        self.assertEqual(statuses["no comma dashes"], checks.WARN)


class ClicheTest(unittest.TestCase):
    def test_stock_phrases_are_named(self):
        work = ("Это и есть главная мысль. Важно отметить, что CRM играет "
                "ключевую роль. Это и есть итог. ") + "Обычный текст. " * 100
        result = checks.check_no_cliches(work)
        self.assertEqual(result.status, checks.WARN)
        self.assertIn('"это и есть", "важно отметить", "играет ключевую роль"', result.detail)

    def test_not_x_but_y_only_in_bulk(self):
        once = "Цель не охват, а заявки. " + "Обычный текст здесь. " * 100
        self.assertEqual(checks.check_no_cliches(once).status, checks.PASS)
        bulk = ("Цель не охват, а заявки. Отчёт не просто цифры, а выводы. "
                "Канал не реклама, а доверие. Метрика не клики, а продажи. ") + "Слово. " * 150
        self.assertEqual(checks.check_no_cliches(bulk).status, checks.WARN)

    def test_plain_text_passes(self):
        text = "Бюджет распределён по трём каналам. Поиск даёт заявки. " * 30
        self.assertEqual(checks.check_no_cliches(text).status, checks.PASS)


if __name__ == "__main__":
    unittest.main()
