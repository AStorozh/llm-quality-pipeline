import unittest

from newlxp import checks

TASK_CHECKLIST = {
    "sections": ["Цифровая трансформация: как она меняет управление",
                 "Этические вопросы: доверие и репутация"],
    "artifacts": ["приложения"],
    "keywords": ["SWOT"],
    "min_words": 100,
    "max_words": 300,
    "needs_headings": True,
    "needs_appendix": True,
}

GOOD = ("## Цифровая трансформация\n\n"
        + "Трансформация меняет управление и компетенции руководителя. " * 12
        + "\n\n## Этические вопросы\n\n"
        + "Доверие общества и репутация стали активом компании. " * 12
        + "\n\nАнализ по SWOT показывает сильные и слабые стороны.\n\n"
        + "## Приложения\n\nПриложение 1. Образец регламента.")


def status_of(results, name):
    return next(r.status for r in results if r.name == name)


class ChecksTest(unittest.TestCase):
    def test_a_good_work_passes_everything(self):
        results = checks.run(GOOD, TASK_CHECKLIST)
        failures = [r for r in results if r.status == checks.FAIL]
        self.assertEqual(failures, [], failures)
        self.assertEqual(checks.score(results), 1.0)

    def test_too_short_and_too_long(self):
        short = checks.check_length("слово " * 10, TASK_CHECKLIST)
        self.assertEqual(short.status, checks.FAIL)
        self.assertIn("100", short.detail)
        self.assertEqual(checks.check_length("слово " * 400, TASK_CHECKLIST).status,
                         checks.FAIL)
        self.assertEqual(checks.check_length("слово " * 310, TASK_CHECKLIST).status,
                         checks.WARN)

    def test_no_stated_length_means_no_opinion(self):
        self.assertEqual(checks.check_length("слово", {}).status, checks.PASS)

    def test_a_missing_section_is_noticed(self):
        without = GOOD.split("## Этические")[0] + "\n\n## Приложения\n\nОбразец."
        self.assertEqual(status_of(checks.run(without, TASK_CHECKLIST), "sections"),
                         checks.FAIL)

    def test_sections_match_by_topic_not_by_wording(self):
        # The work never repeats the task's full sentence, only the topic.
        self.assertEqual(status_of(checks.run(GOOD, TASK_CHECKLIST), "sections"),
                         checks.PASS)

    def test_missing_appendix_and_keyword(self):
        bare = GOOD.split("## Приложения")[0].replace("Анализ по SWOT", "Анализ")
        results = checks.run(bare, TASK_CHECKLIST)
        self.assertEqual(status_of(results, "artifacts"), checks.FAIL)
        self.assertEqual(status_of(results, "keywords"), checks.FAIL)

    def test_chat_leftovers(self):
        self.assertEqual(
            checks.check_no_chat_leftovers("Текст.\n\nЕсли нужно, я могу оформить.").status,
            checks.FAIL)
        self.assertEqual(checks.check_no_chat_leftovers("Обычный текст.").status,
                         checks.PASS)

    def test_figures_are_judged_against_the_materials(self):
        work = "Доля рынка выросла на 47% за год."
        self.assertEqual(
            checks.check_no_invented_figures(work, "В материалах нет чисел.").status,
            checks.FAIL)
        self.assertEqual(
            checks.check_no_invented_figures(work, "Рост составил 12% и 47%.").status,
            checks.PASS)
        self.assertEqual(checks.check_no_invented_figures(work, "").status, checks.WARN)
        self.assertEqual(checks.check_no_invented_figures("Без чисел.", "").status,
                         checks.PASS)

    def test_source_tells_and_dashes(self):
        self.assertEqual(checks.check_no_source_tells("В материалах сказано.").status,
                         checks.FAIL)
        self.assertEqual(checks.check_no_source_tells("Прямое изложение.").status,
                         checks.PASS)
        self.assertEqual(checks.check_no_long_dashes("мысль — другая").status,
                         checks.FAIL)
        self.assertEqual(checks.check_no_long_dashes("мысль - другая").status,
                         checks.PASS)

    def test_structure_wants_prose_but_obeys_the_task(self):
        skeleton = "\n\n".join("## Раздел %d\n\nОдин абзац." % i for i in range(12))
        self.assertEqual(checks.check_structure(skeleton, {}).status, checks.WARN)
        self.assertEqual(
            checks.check_structure("Просто текст без заголовков.",
                                   {"needs_headings": True}).status, checks.FAIL)

    def test_score_is_the_share_that_did_not_fail(self):
        results = [checks.Result("a", checks.PASS), checks.Result("b", checks.WARN),
                   checks.Result("c", checks.FAIL), checks.Result("d", checks.PASS)]
        self.assertEqual(checks.score(results), 0.75)
        self.assertEqual(checks.score([]), 1.0)
