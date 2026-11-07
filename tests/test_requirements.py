import unittest
from unittest import mock

from newlxp import ai, coursework, requirements

TASK = """Разработка организационной структуры компании

Напишите работу объёмом примерно 1500-2000 слов.

1. Исследование компании: кратко охарактеризуйте выбранную компанию.
2. Постановка целей: сформулируйте миссию и стратегические цели.
3. Оценка эффективности: определите метрики и KPI.

Требования к оформлению:
- Документ должен быть структурирован с использованием заголовков.
- Присутствуют приложения с образцами должностных инструкций.
"""


class FromTextTest(unittest.TestCase):
    def test_reads_the_checklist_out_of_the_task(self):
        checklist = requirements.from_text(TASK)
        self.assertEqual(len(checklist["sections"]), 3)
        self.assertIn("Исследование компании", checklist["sections"][0])
        self.assertIn("приложения", checklist["artifacts"])
        self.assertIn("KPI", checklist["keywords"])
        self.assertEqual(checklist["min_words"], 1500)
        self.assertEqual(checklist["max_words"], 2000)
        self.assertTrue(checklist["needs_headings"])
        self.assertTrue(checklist["needs_appendix"])

    def test_a_mobile_app_is_not_an_appendix(self):
        task = ("Разработайте контент-стратегию для продвижения мобильного "
                "приложения. Цель: рост загрузок приложения. Покупатель "
                "показывает код из приложения на кассе.")
        checklist = requirements.from_text(task)
        self.assertFalse(checklist["needs_appendix"])
        self.assertNotIn("приложения", checklist["artifacts"])
        self.assertTrue(requirements.mentions_appendix(
            task + " Расчёты вынесите в приложение к работе."))

    def test_grading_lines_are_not_mistaken_for_sections(self):
        self.assertEqual(requirements.from_text("15 баллов - работа сдана вовремя.")
                         ["sections"], [])

    def test_a_task_without_requirements(self):
        checklist = requirements.from_text("Напишите небольшой разбор темы.")
        self.assertEqual(checklist["min_words"], 0)
        self.assertEqual(checklist["max_words"], 0)
        self.assertFalse(checklist["needs_appendix"])

    def test_upper_bounds_in_other_units(self):
        from newlxp import coursework

        self.assertEqual(requirements.from_text("Не более 4 страниц.")["max_words"],
                         4 * coursework.WORDS_PER_PAGE)
        self.assertGreater(requirements.from_text("Не более 12000 знаков.")["max_words"], 0)

    def test_one_parser_answers_for_the_whole_project(self):
        # Three parsers used to disagree about the same sentence.
        text = "Работа на 5 страниц, не менее 1200 слов."
        stated = coursework.read_volume(text)
        checklist = requirements.from_text(text)
        self.assertEqual(checklist["min_words"], stated.floor)
        self.assertEqual(checklist["max_words"], stated.ceiling)
        self.assertEqual(coursework.volume_floor(text), stated.floor)
        self.assertEqual(coursework.required_volume(text), stated.as_written)

    def test_a_limit_scoped_to_one_section_is_not_the_whole_work(self):
        self.assertEqual(requirements.from_text("Сократите введение до 200 слов.")
                         ["max_words"], 0)

    def test_a_number_that_is_not_a_size(self):
        for text in ("Напишите 1500 словосочетаний.", "Подготовьте 10 листовок.",
                     "Схему разместите на 2 страницах приложения."):
            self.assertEqual(requirements.from_text(text)["min_words"], 0, text)
            self.assertEqual(requirements.from_text(text)["max_words"], 0, text)


class ExtractTest(unittest.TestCase):
    CONFIG = {"provider": "openai", "api_key": "k", "model": "m"}

    def answer(self, text):
        return ai.Answer(text, "m", 10, 20)

    def test_uses_the_structured_answer(self):
        payload = ('{"sections": ["Анализ рынка"], "artifacts": [], '
                   '"keywords": ["SWOT"], "min_words": 0, "max_words": 0, '
                   '"needs_headings": false, "needs_appendix": false}')
        with mock.patch.object(ai, "complete", return_value=self.answer(payload)):
            checklist = requirements.extract(self.CONFIG, "Задание без объёма.")
        self.assertEqual(checklist["sections"], ["Анализ рынка"])
        self.assertEqual(checklist["keywords"], ["SWOT"])

    def test_asks_for_json_mode(self):
        payload = '{"sections": [], "artifacts": [], "min_words": 0, "max_words": 0}'
        with mock.patch.object(ai, "complete", return_value=self.answer(payload)) as call:
            requirements.extract(self.CONFIG, "Задание.")
        self.assertTrue(call.call_args.kwargs.get("json_mode"))

    def test_a_fenced_or_chatty_reply_is_still_parsed(self):
        payload = ('Вот результат:\n```json\n{"sections": ["A"], "artifacts": [], '
                   '"min_words": 0, "max_words": 0}\n```')
        with mock.patch.object(ai, "complete", return_value=self.answer(payload)):
            self.assertEqual(requirements.extract(self.CONFIG, "Задание.")["sections"],
                             ["A"])

    def test_the_stated_size_overrides_the_model(self):
        payload = ('{"sections": [], "artifacts": [], "min_words": 10, '
                   '"max_words": 20}')
        with mock.patch.object(ai, "complete", return_value=self.answer(payload)):
            checklist = requirements.extract(self.CONFIG, TASK)
        self.assertEqual(checklist["min_words"], 1500)
        self.assertEqual(checklist["max_words"], 2000)

    def test_falls_back_when_the_model_answers_badly(self):
        for reply in ("не могу", '{"sections": "не список"}', "{broken"):
            with mock.patch.object(ai, "complete", return_value=self.answer(reply)):
                checklist = requirements.extract(self.CONFIG, TASK)
            self.assertEqual(len(checklist["sections"]), 3, reply)

    def test_falls_back_when_the_call_fails(self):
        with mock.patch.object(ai, "complete", side_effect=ai.AIError("down")):
            checklist = requirements.extract(self.CONFIG, TASK)
        self.assertEqual(checklist["min_words"], 1500)
