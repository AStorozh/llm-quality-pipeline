"""The second look: what it may change and what it must leave alone."""
import io
import json
import os
from contextlib import redirect_stdout
from unittest import mock

import test_integration
from helpers import TempDirTestCase

from newlxp import ai, api, config, coursework, requirements, review, usage
from newlxp.screens import generate

TASK = ("Алгоритм:\n1. Определите цели кампании.\n2. Разделите бюджет по каналам.\n"
        "3. Рассчитайте стоимость заявки.\n4. Сделайте вывод.")

WORK = (
    "## Расчет\n\n"
    "Для учебной задачи я беру условный набор данных по двум каналам и считаю "
    "итоги по каждому показателю. Цель кампании - получить десять заявок и "
    "уложиться в триста рублей. Повторяющаяся фраза для проверки. "
    "Повторяющаяся фраза для проверки.\n\n"
    "| Канал | Бюджет | Заявок |\n|---|---:|---:|\n"
    "| А | 100 | 4 |\n| Б | 200 | 6 |\n| Итого | 300 | 10 |\n\n"
    "Средняя стоимость заявки составит 300 / 10 = 30 рублей. Блогеров "
    "подключаем в первый месяц. Первый канал даёт четыре заявки из десяти, "
    "а второй приносит остальные шесть, поэтому бюджет распределён с учётом "
    "результата каждого канала и плановой стоимости обращения."
)

CHECKLIST = requirements.from_text(TASK)


def reply(edits, issues=None):
    payload = {"issues": issues or [], "edits": edits}
    return ai.Answer(json.dumps(payload, ensure_ascii=False), "m", 200, 40)


def run_review(edits, issues=None, work=WORK):
    with mock.patch.object(ai, "complete", return_value=reply(edits, issues)) as call:
        outcome = review.review({"provider": "x"}, work, TASK, CHECKLIST)
    return outcome, call


class GateTest(TempDirTestCase):
    def test_an_essay_is_not_reviewed(self):
        self.assertFalse(review.needs_review(requirements.from_text(
            "Напишите эссе на 300 слов.")))

    def test_numbered_steps_are_reviewed(self):
        self.assertTrue(review.needs_review(CHECKLIST))

    def test_a_calculation_is_reviewed_even_without_steps(self):
        self.assertTrue(review.needs_review(requirements.from_text(
            "Постройте медиаплан и рассчитайте стоимость заявки.")))


class ApplyTest(TempDirTestCase):
    def test_a_good_edit_goes_in_and_the_rest_is_untouched(self):
        outcome, call = run_review(
            [{"old": "Блогеров подключаем в первый месяц.",
              "new": "Блогеров подключаем со второго месяца, когда отработают тесты."}],
            issues=["блогеры стартуют позже, чем сказано"])
        self.assertEqual(outcome.applied, 1)
        self.assertIn("со второго месяца", outcome.text)
        self.assertNotIn("в первый месяц.", outcome.text)
        self.assertEqual(outcome.text.replace(
            "Блогеров подключаем со второго месяца, когда отработают тесты.",
            "Блогеров подключаем в первый месяц."), WORK)
        self.assertEqual(outcome.issues, ["блогеры стартуют позже, чем сказано"])
        self.assertEqual(len(outcome.replies), 1)
        self.assertTrue(call.call_args.kwargs["json_mode"])

    def test_the_prompt_carries_the_task_the_steps_and_the_work(self):
        _, call = run_review([])
        user = call.call_args.args[2]
        self.assertIn("Рассчитайте стоимость заявки", user)
        self.assertIn("# ПУНКТЫ ЗАДАНИЯ", user)
        self.assertIn("Средняя стоимость заявки составит", user)

    def test_a_quote_that_is_not_in_the_work_is_dropped(self):
        outcome, _ = run_review([{"old": "Такого предложения в работе нет.",
                                  "new": "Любая замена на его месте."}])
        self.assertEqual(outcome.applied, 0)
        self.assertEqual(outcome.text, WORK)
        self.assertIn("not in the work", outcome.rejected[0][0])

    def test_an_ambiguous_quote_is_dropped(self):
        outcome, _ = run_review([{"old": "Повторяющаяся фраза для проверки.",
                                  "new": "Одна фраза вместо двух одинаковых."}])
        self.assertEqual(outcome.text, WORK)
        self.assertIn("2 times", outcome.rejected[0][0])

    def test_a_short_quote_is_not_an_anchor(self):
        outcome, _ = run_review([{"old": "заявки", "new": "обращения"}])
        self.assertEqual(outcome.text, WORK)

    def test_a_replacement_that_cuts_the_passage_is_dropped(self):
        old = ("Первый канал даёт четыре заявки из десяти, а второй приносит "
               "остальные шесть, поэтому бюджет распределён с учётом результата "
               "каждого канала и плановой стоимости обращения.")
        outcome, _ = run_review([{"old": old, "new": "Бюджет распределён."}])
        self.assertEqual(outcome.text, WORK)
        self.assertIn("cuts", outcome.rejected[0][0])

    def test_an_edit_that_breaks_a_total_is_dropped(self):
        outcome, _ = run_review([{"old": "| Б | 200 | 6 |", "new": "| Б | 200 | 9 |"}])
        self.assertEqual(outcome.text, WORK)
        self.assertIn("arithmetic", outcome.rejected[0][0])

    def test_an_edit_that_removes_a_table_row_is_dropped(self):
        outcome, _ = run_review([{"old": "| А | 100 | 4 |\n| Б | 200 | 6 |",
                                  "new": "| Б | 200 | 6 |"}])
        self.assertEqual(outcome.text, WORK)

    def test_a_replacement_that_trips_a_check_is_dropped(self):
        outcome, _ = run_review([{
            "old": "Блогеров подключаем в первый месяц.",
            "new": "Блогеров подключаем позже, как описано в материалах курса."}])
        self.assertEqual(outcome.text, WORK)
        self.assertIn("no source tells", outcome.rejected[0][0])

    def test_long_dashes_are_turned_into_hyphens(self):
        outcome, _ = run_review([{
            "old": "Блогеров подключаем в первый месяц.",
            "new": "Блогеров подключаем позже — после первых тестов."}])
        self.assertEqual(outcome.applied, 1)
        self.assertIn("позже - после", outcome.text)
        self.assertNotIn("—", outcome.text)

    def test_a_replacement_that_adds_a_heading_is_dropped(self):
        outcome, _ = run_review([{
            "old": "Блогеров подключаем в первый месяц.",
            "new": "Блогеров подключаем в первый месяц.\n\n## 4.1 Риски\n\nТекст о рисках."}])
        self.assertEqual(outcome.text, WORK)
        self.assertIn("heading", outcome.rejected[0][0])

    def test_a_quote_across_paragraphs_is_dropped(self):
        outcome, _ = run_review([{
            "old": "Блогеров подключаем в первый месяц. Первый канал даёт\n\nчетыре заявки",
            "new": "Блогеров подключаем позже."}])
        self.assertEqual(outcome.text, WORK)
        self.assertIn("paragraphs", outcome.rejected[0][0])

    def test_a_repeated_table_row_is_dropped(self):
        outcome, _ = run_review([{"old": "| А | 100 | 4 |",
                                  "new": "| А | 100 | 4 |\n| А | 100 | 4 |"}])
        self.assertEqual(outcome.text, WORK)

    def test_one_bad_edit_does_not_stop_the_good_one(self):
        outcome, _ = run_review([
            {"old": "Такого предложения в работе нет.", "new": "Замена."},
            {"old": "Блогеров подключаем в первый месяц.",
             "new": "Блогеров подключаем со второго месяца, когда отработают тесты."},
        ])
        self.assertEqual(outcome.applied, 1)
        self.assertEqual(len(outcome.rejected), 1)

    def test_no_problems_means_no_changes(self):
        outcome, _ = run_review([], issues=[])
        self.assertFalse(outcome.changed)
        self.assertEqual(outcome.text, WORK)


class FailureTest(TempDirTestCase):
    def test_an_unreadable_answer_changes_nothing(self):
        garbage = ai.Answer("Конечно! Вот исправленная работа целиком.", "m", 5, 5)
        with mock.patch.object(ai, "complete", return_value=garbage):
            outcome = review.review({"provider": "x"}, WORK, TASK, CHECKLIST)
        self.assertEqual(outcome.text, WORK)
        self.assertEqual(len(outcome.replies), 1)  # still paid for, still counted

    def test_an_answer_of_the_wrong_shape_changes_nothing(self):
        wrong = ai.Answer('{"edits": "заменить всё"}', "m", 5, 5)
        with mock.patch.object(ai, "complete", return_value=wrong):
            outcome = review.review({"provider": "x"}, WORK, TASK, CHECKLIST)
        self.assertEqual(outcome.text, WORK)

    def test_a_failed_request_is_raised_for_the_caller_to_handle(self):
        with mock.patch.object(ai, "complete", side_effect=ai.AIError("down")):
            with self.assertRaises(ai.AIError):
                review.review({"provider": "x"}, WORK, TASK, CHECKLIST)

    def test_only_the_first_edits_are_considered(self):
        edits = [{"old": "Такого предложения в работе нет %d." % i, "new": "Замена."}
                 for i in range(review.MAX_EDITS + 5)]
        outcome, _ = run_review(edits)
        self.assertEqual(len(outcome.rejected), review.MAX_EDITS)


class SecondLookTest(TempDirTestCase):
    """The step in the generation flow around :func:`review.review`."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(config, "CONFIG_FILE", self.path("ai.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def look(self, task=TASK, side_effect=None, return_value=None):
        spent = []
        with mock.patch.object(ai, "complete", side_effect=side_effect,
                               return_value=return_value) as call, \
                redirect_stdout(io.StringIO()) as out:
            result = generate._second_look({"provider": "x"}, mock.Mock(full_name=""),
                                           "КТ 1", WORK, task, "", spent)
        return result, call, spent, out.getvalue()

    def test_it_is_on_by_default(self):
        self.assertTrue(config.get_self_review())

    def test_it_can_be_switched_off_and_on(self):
        config.set_self_review(False)
        self.assertFalse(config.get_self_review())
        (text, outcome), call, _, _ = self.look(return_value=reply([]))
        self.assertEqual((text, outcome), (WORK, None))
        call.assert_not_called()
        config.set_self_review(True)
        self.assertTrue(config.get_self_review())

    def test_an_essay_costs_no_extra_request(self):
        (text, outcome), call, _, _ = self.look(
            task="Напишите эссе на 300 слов.", return_value=reply([]))
        self.assertEqual((text, outcome), (WORK, None))
        call.assert_not_called()

    def test_the_replies_are_handed_back_for_costing(self):
        (_, outcome), _, spent, _ = self.look(return_value=reply([]))
        self.assertEqual(len(spent), 1)
        self.assertIs(spent[0], outcome.replies[0])

    def test_a_failed_request_keeps_the_work_and_says_so(self):
        (text, outcome), _, spent, out = self.look(side_effect=ai.AIError("rate limit"))
        self.assertEqual((text, outcome, spent), (WORK, None, []))
        self.assertIn("rate limit", out)

    def test_a_bug_inside_the_review_keeps_the_work(self):
        with mock.patch.object(review, "review", side_effect=RuntimeError("boom")):
            (text, outcome), _, _, _ = self.look(return_value=reply([]))
        self.assertEqual((text, outcome), (WORK, None))


STEPS_TASK = ("Выполните задание:\n1. Определите цели программы.\n"
              "2. Разработайте механику программы.\n3. Опишите учёт бонусов.\n"
              "4. Предложите оценку эффективности.")

PROGRAM = (
    "Цель программы - вернуть клиентов к повторной покупке и поднять средний "
    "чек в течение квартала. Механика строится на накоплении баллов за каждую "
    "покупку и на двух уровнях участия, которые открываются по сумме заказов. "
    "Лимит списания составляет тридцать процентов, и это слишком много для "
    "учебного продукта с невысокой маржой. Учёт бонусов ведётся в личном "
    "кабинете, где клиент видит баланс, историю начислений и историю списаний. "
    "Эффективность оценивается по доле повторных покупок и по среднему чеку "
    "участников программы в сравнении с остальными покупателями."
)

BAD, GOOD = ("Лимит списания составляет тридцать процентов, и это слишком много "
             "для учебного продукта с невысокой маржой.",
             "Лимит списания составляет пятнадцать процентов, чтобы программа "
             "не уходила в минус на продукте с невысокой маржой.")


class FlowTest(test_integration.EndToEndTest):
    """Through the real screens: a structured task gets its second look.

    Reuses the end-to-end harness (patched platform, model and home
    directory). Its own tests describe a one-request essay, so they are
    switched off here rather than run against a different task.
    """

    locals().update({name: None for name in dir(test_integration.EndToEndTest)
                     if name.startswith("test_")})

    def setUp(self):
        super().setUp()
        content = dict(test_integration.CONTENT)
        content["k1"] = {"name": 'КТ №1 "Программа"',
                         "content": {"howStudyIt": STEPS_TASK}}
        patcher = mock.patch.object(api, "get_topic_content",
                                    side_effect=lambda token, tid: content[tid])
        patcher.start()
        self.addCleanup(patcher.stop)

    KEYS = ["1", "1", "2", "1", "", "", "", "4"]

    def saved(self):
        folder = os.path.join(self.path("ai_output"), "Корпоративный_менеджмент")
        name = next(n for n in os.listdir(folder) if n.endswith(".md"))
        with open(os.path.join(folder, name), encoding="utf-8") as fh:
            return fh.read()

    def test_the_fix_is_saved_remembered_and_costed(self):
        first = ai.Answer(PROGRAM, "test-model", 1000, 300)
        second = reply([{"old": BAD, "new": GOOD}], ["лимит списания слишком высок"])
        with mock.patch.object(ai, "complete", side_effect=[first, second]) as call:
            code, output = self.run_app(self.KEYS)
        self.assertEqual(code, 0)
        self.assertEqual(call.call_count, 2)
        self.assertIn("пятнадцать процентов", self.saved())
        self.assertNotIn("тридцать процентов", self.saved())
        remembered = coursework.load_works_index("Корпоративный менеджмент")
        self.assertTrue(any("пятнадцать" in w for w in remembered.values()))
        runs = usage.read_log(self.path("usage.jsonl"))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].input_tokens, 1000 + 200)
        self.assertIn("1 fix(es) applied", output)
        self.assertIn("лимит списания слишком высок", output)

    def test_a_broken_review_leaves_the_first_answer(self):
        first = ai.Answer(PROGRAM, "test-model", 1000, 300)
        with mock.patch.object(ai, "complete",
                               side_effect=[first, ai.AIError("rate limit")]):
            code, output = self.run_app(self.KEYS)
        self.assertEqual(code, 0)
        self.assertIn(BAD, self.saved())
        self.assertIn("second look skipped", output)
        self.assertNotIn("Traceback", output)

    def test_switched_off_it_is_one_request(self):
        config.set_self_review(False)
        first = ai.Answer(PROGRAM, "test-model", 1000, 300)
        with mock.patch.object(ai, "complete", return_value=first) as call:
            self.run_app(self.KEYS)
        self.assertEqual(call.call_count, 1)
