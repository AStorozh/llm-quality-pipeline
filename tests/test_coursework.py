import json
import unittest
from unittest import mock

from newlxp import attachments, coursework

TOPICS = {
    "t1": {"name": "Тема 1", "content": {"blocks": [{"name": "Текст", "body": json.dumps([
        {"type": "paragraph", "data": {"text": "Материал темы"}},
        {"type": "uploaderFileTool", "data": {"file": {"name": "лекция.pdf", "url": "https://x/l.pdf"}}},
        {"type": "uploaderFileTool", "data": {"file": {"name": "звук.mp3", "url": "https://x/s.mp3"}}},
        {"type": "uploaderFileTool", "data": {"file": {"name": "битый.docx", "url": "https://x/b.docx"}}},
    ])}]}},
    "k1": {"name": "КТ 1", "content": {"howStudyIt": "Напишите эссе"}},
    "k2": {"name": "КТ 2", "content": {"howStudyIt": "Напишите доклад"}},
}
DISCIPLINE = {"chapters": [
    {"name": "Глава", "topics": [
        {"id": "t1", "name": "Тема 1"},
        {"id": "k1", "name": "КТ 1", "isCheckPoint": True, "maxScore": 10},
        {"id": "k2", "name": "КТ 2", "isCheckPoint": True},
    ]},
]}


def fake_extract(name, url):
    if name.endswith(".docx"):
        raise attachments.AttachmentError("сломан")
    return "Текст из PDF"


class CourseworkTest(unittest.TestCase):
    def setUp(self):
        self.topics = coursework.flatten_topics(DISCIPLINE)
        patches = [
            mock.patch.object(coursework.api, "get_topic_content",
                              side_effect=lambda token, tid: TOPICS[tid]),
            mock.patch.object(attachments, "extract_text", side_effect=fake_extract),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_flatten_and_checkpoints(self):
        self.assertEqual([t["id"] for t in self.topics], ["t1", "k1", "k2"])
        self.assertEqual([i for i, _ in coursework.checkpoints(self.topics)], [1, 2])
        self.assertEqual(self.topics[1]["max_score"], 10)

    def test_prompt_contains_previous_materials_in_order(self):
        prompt = coursework.build_prompt("tok", self.topics, 2, {"k1": "Моё эссе"}, {})[0]
        order = [prompt.index(s) for s in (
            "[Учебная тема] Тема 1", "Материал темы", "Вложение «лекция.pdf»",
            "Текст из PDF", "[Контрольная точка] КТ 1", "Моё эссе",
            "ЗАДАНИЕ: КОНТРОЛЬНАЯ ТОЧКА", "Напишите доклад")]
        self.assertEqual(order, sorted(order))
        self.assertIn("(не удалось прочитать: сломан)", prompt)
        self.assertNotIn("звук.mp3»", prompt)  # unsupported files are skipped

    def test_the_task_itself_is_never_clipped(self):
        # КТ5 of this course is ~8000 characters: clipped at the topic limit
        # its last requirements never reached the model.
        long_task = "Пункт. " * 1500  # ~10 500 characters
        topics = [{"id": "big", "name": "КТ", "is_checkpoint": True}]
        with mock.patch.object(coursework.api, "get_topic_content", return_value={
                "name": "КТ", "content": {"howStudyIt": long_task}}):
            prompt, task_text = coursework.build_prompt("tok", topics, 0, {}, {})
        self.assertGreater(len(task_text), coursework.MAX_TOPIC_CHARS)
        self.assertNotIn("…[сокращено]", task_text)
        self.assertIn(long_task.strip()[-200:], prompt)

    def test_background_topics_are_still_clipped(self):
        long_topic = "Текст. " * 1500
        topics = [{"id": "t", "name": "Тема", "is_checkpoint": False},
                  {"id": "k", "name": "КТ", "is_checkpoint": True}]
        bodies = {"t": long_topic, "k": "Задание"}
        with mock.patch.object(coursework.api, "get_topic_content",
                               side_effect=lambda tok, i: {
                                   "name": i, "content": {"howStudyIt": bodies[i]}}):
            prompt, _ = coursework.build_prompt("tok", topics, 1, {}, {})
        self.assertIn("…[сокращено]", prompt)

    def test_output_rules_come_last_right_after_the_task(self):
        prompt = coursework.build_prompt("tok", self.topics, 2, {}, {})[0]
        self.assertTrue(prompt.rstrip().endswith(coursework.output_rules()))
        self.assertLess(prompt.index("ЗАДАНИЕ"), prompt.index(coursework.output_rules()))
        rules = coursework.output_rules().lower()
        for fragment in ("700-1200 слов", "больше 1800 слов не пиши",
                         "шести-восьми на всю работу", "связный текст абзацами",
                         "это твоё предложение, а не факт", "без подписи в конце"):
            self.assertIn(fragment, rules)

    def test_task_requirements_outrank_the_formatting_rules(self):
        # КТ3 demands headings, numbered lists and appendices; blanket
        # "fewer headings, no lists" rules must not override the task.
        rules = coursework.output_rules().lower()
        self.assertTrue(rules.index("требования задания важнее")
                        < rules.index("700-1200 слов"))
        for fragment in ("сначала выпиши для себя всё, что требует задание",
                         "титульный лист с датой", "пояснение после каждого пункта",
                         "swot", "если задание не требует иного",
                         "а не выбрасывая его", "1400-1800 слов",
                         "срок и ответственного", "отдельным разделом «приложения»",
                         "опиши каждый вариант отдельно"):
            self.assertIn(fragment, rules)
        prompt = coursework.SYSTEM_PROMPT.lower()
        self.assertIn("если задание не предписывает иного", prompt)
        self.assertIn("пропущенный пункт стоит баллов", prompt)

    def test_prompt_does_not_ask_for_a_full_length_work(self):
        # "полную работу" pushed the model towards padding.
        self.assertNotIn("полную", coursework.build_prompt("tok", self.topics, 1, {}, {})[0])

    def test_first_checkpoint_has_only_preceding_topics(self):
        prompt = coursework.build_prompt("tok", self.topics, 1, {}, {})[0]
        self.assertNotIn("Напишите доклад", prompt)
        self.assertIn("Напишите эссе", prompt)

    def test_topic_content_is_cached(self):
        cache = {}
        coursework.build_prompt("tok", self.topics, 2, {}, cache)
        coursework.build_prompt("tok", self.topics, 1, {}, cache)
        self.assertEqual(coursework.api.get_topic_content.call_count, 3)

    def test_clip(self):
        self.assertEqual(coursework._clip("абвгд", 3), "абв …[сокращено]")
        self.assertEqual(coursework._clip(" аб ", 3), "аб")

    def test_system_prompt(self):
        self.assertIn("Иванов Иван", coursework.system_prompt("Иванов Иван"))
        self.assertTrue(coursework.system_prompt("", "свой").startswith("свой"))

    def test_slides_instruction_only_for_presentations(self):
        self.assertNotIn("презентацией", coursework.system_prompt("Иванов Иван"))
        with_slides = coursework.system_prompt("Иванов Иван", slides=True)
        self.assertIn("презентацией", with_slides)
        # The author line stays last, after the slides instruction.
        self.assertLess(with_slides.index("презентацией"), with_slides.index("Иванов Иван"))

    def test_custom_prompt_also_gets_the_additions(self):
        text = coursework.system_prompt("Иванов Иван", "  свой промт  ", slides=True)
        self.assertTrue(text.startswith("свой промт"))
        self.assertIn("## ", text)
        self.assertIn("Иванов Иван", text)

    def test_default_prompt_demands_substance_and_forbids_invention(self):
        prompt = coursework.SYSTEM_PROMPT.lower()
        for fragment in ("не выдавай выдуманное за факт",
                         "не заполняй пробелы догадками",
                         "обосновывай выводы", "общеизвестные факты"):
            self.assertIn(fragment, prompt)

    def test_default_prompt_closes_the_holes_seen_in_practice(self):
        prompt = coursework.SYSTEM_PROMPT.lower()
        checks = {
            "no invented events": "не описывай как состоявшееся то, чего не было",
            "no visible source refs": "«в материалах»",
            "no pseudo-graphics": "символами псевдографики",
            "no repeated block type": "не повторяй один и тот же тип блока",
            "length varies by task": "работы по разным темам не должны получаться "
                                     "одинакового размера",
            "hard word ceiling": "не превышай 1800 слов",
            "ordinary length target": "700-1200 слов",
            "no long dashes": "не используй длинное и среднее тире",
            "dates only when asked": "проставляй, только если задание",
            "no fabricated numbers": "не подставляй правдоподобные",
            "own estimates allowed": "давай их конкретно, как своё предложение",
            "few headings": "не больше шести-восьми на всю работу",
            "prose not bullet skeleton": "связный текст абзацами",
            "no trailing signature": "без подписи в конце",
            "no offers to redo": "без предложений доработать",
        }
        for name, fragment in checks.items():
            self.assertIn(fragment, prompt, name)

    def test_default_prompt_links_works_without_copying_them(self):
        prompt = coursework.SYSTEM_PROMPT.lower()
        self.assertIn("опирайся на принятые там решения", prompt)
        self.assertIn("не копируй формулировки", prompt)

    def test_default_prompt_defines_what_to_do_without_outside_sources(self):
        # The task rarely says whether outside sources are allowed, so the
        # fallback must be spelled out rather than left to the model.
        self.assertIn("если в задании об этом ничего не сказано",
                      coursework.SYSTEM_PROMPT.lower())

    def test_default_prompt_keeps_its_section_labels_out_of_the_work(self):
        self.assertIn("не переноси их в текст", coursework.SYSTEM_PROMPT.lower())


class NamingTest(unittest.TestCase):
    def test_checkpoint_label(self):
        cases = {
            'КТ №4. Контрольная работа №4.': (4, "Контрольная работа №4"),
            'КТ № 3 - "Планирование кампании"': (3, "Планирование кампании"),
            'КТ №5: Решение кейса "План"': (5, 'Решение кейса "План"'),
            'КТ №6 "Матрица «А – Б»"': (6, "Матрица «А – Б»"),
            "КТ1 Эссе": (1, "Эссе"),
            "Checkpoint 2. Introduction to IT": (2, "Introduction to IT"),
            "Контрольная точка: обратная матрица": (9, "Обратная матрица"),
            "КТ Случайные события": (9, "Случайные события"),
            "Итоговая работа": (9, "Итоговая работа"),
            "Ктулху": (9, "Ктулху"),
        }
        for name, expected in cases.items():
            self.assertEqual(coursework.checkpoint_label(name, 9), expected, name)

    def test_heading_and_filename(self):
        self.assertEqual(
            coursework.work_heading("Менеджмент", 5, "Эссе", "Иванов Иван Иванович"),
            ["Менеджмент", "КТ5: Эссе", "Иванов Иван Иванович"])
        self.assertEqual(
            coursework.work_filename(5, "Корпоративный менеджмент", "И.И.И"),
            "КТ5_Корпоративный_менеджмент_И.И.И")


class RequiredVolumeTest(unittest.TestCase):
    def test_wordings_found_in_real_tasks(self):
        cases = {
            "Напишите эссе объёмом примерно 1500–2000 слов, посвящённое":
                "1 500-2 000 слов",
            "Объём работы — не менее 5 страниц": "не менее 5 страниц",
            "Текст не более 10 000 знаков": "не более 10 000 знаков",
            "Реферат объёмом 12000 символов": "12 000 символов",
            "Работа на 3 листа": "3 листа",
            "Объём: от 800 до 1200 слов": "800-1 200 слов",
            "не менее 2 стр.": "не менее 2 стр.",
        }
        for text, expected in cases.items():
            self.assertEqual(coursework.required_volume(text), expected, text)

    def test_numbers_that_are_not_a_size(self):
        for text in ("Другими словами, компании растут",
                     "не в полном объеме",
                     "Группа A (Разработчики): 10 человек",
                     "Сформируйте список из 3–5 ключевых ценностей",
                     "15 баллов - Работа сдана вовремя",
                     "Компания основана в 1995 году",
                     ""):
            self.assertEqual(coursework.required_volume(text), "", text)

    def test_stated_size_replaces_the_default_guidance(self):
        rules = coursework.output_rules("эссе объёмом примерно 1500–2000 слов")
        self.assertIn("Объём задан в задании: 1 500-2 000 слов", rules)
        self.assertIn("целься в верхнюю половину", rules)
        self.assertNotIn("700-1200 слов", rules)
        self.assertIn("700-1200 слов", coursework.output_rules("обычное задание"))

    def test_size_from_the_task_reaches_the_prompt(self):
        topics = [{"id": "k1", "name": "КТ", "is_checkpoint": True}]
        with mock.patch.object(coursework.api, "get_topic_content", return_value={
                "name": "КТ", "content": {"howStudyIt": "Эссе объёмом 1500–2000 слов"}}):
            prompt, _task = coursework.build_prompt("tok", topics, 0, {}, {})
        self.assertIn("Объём задан в задании: 1 500-2 000 слов", prompt)


class VolumeFloorTest(unittest.TestCase):
    def test_floor_only_for_checkable_units(self):
        cases = {
            "эссе объёмом примерно 1500–2000 слов": 1500,
            "от 800 до 1200 слов": 800,
            "объём 12000 символов": int(12000 / coursework.CHARS_PER_WORD),
            "не менее 5 страниц": 0,          # pages depend on formatting
            "не более 10 000 знаков": 0,      # an upper bound only
            "обычное задание без объёма": 0,
        }
        for text, expected in cases.items():
            self.assertEqual(coursework.volume_floor(text), expected, text)

    def test_expansion_prompt_states_both_sizes_and_keeps_the_text(self):
        answer = "слово " * 100
        prompt = coursework.expansion_prompt(answer, "эссе объёмом 1500–2000 слов")
        self.assertIn("в ней 100 слов", prompt)
        self.assertIn("1 500-2 000 слов", prompt)
        self.assertIn(answer.strip(), prompt)
        self.assertIn("не повторяй уже сказанное", prompt)
