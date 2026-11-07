"""Defects found in review, each pinned so it cannot come back.

Every test here failed before its fix. The comment says what went wrong,
because that is the part a reader cannot reconstruct from the assertion.
"""
import unittest
from unittest import mock

from newlxp import (
    api,
    attachments,
    checks,
    content,
    coursework,
    export,
    grades,
    polish,
    ui,
)
from newlxp import (
    session as session_module,
)


class ClippingTest(unittest.TestCase):
    """The assignment was clipped to the background-material budget."""

    def test_prefetch_does_not_cache_a_clipped_assignment(self):
        # _prefetch stored _topic_text's *return* value, which is clipped.
        # The target checkpoint then arrived cut to MAX_TOPIC_CHARS however
        # large MAX_TASK_CHARS was.
        body = "Пункт задания. " * 900          # ~13 500 characters
        topics = [{"id": "t%d" % i, "name": "T%d" % i, "is_checkpoint": i == 2}
                  for i in range(3)]
        with mock.patch.object(coursework.api, "get_topic_content",
                               side_effect=lambda tok, tid: {
                                   "name": tid, "content": {"howStudyIt": body}}):
            prompt, task = coursework.build_prompt("tok", topics, 2, {}, {})
        self.assertNotIn("…[сокращено]", task)
        self.assertGreater(len(task), coursework.MAX_TOPIC_CHARS)
        self.assertIn("…[сокращено]", prompt)  # background still is clipped


class PolishTest(unittest.TestCase):
    """clean_answer deleted ordinary final paragraphs."""

    def keeps(self, tail):
        return tail in polish.clean_answer("Основной текст работы.\n\n" + tail)

    def test_impersonal_russian_is_not_an_offer(self):
        # "мог"/"гото" as a stem matched "могут применяться" and
        # "готовность", so conclusions were silently dropped.
        for tail in ("При необходимости могут применяться дополнительные меры.",
                     "Если необходимости нет, сотрудники могут работать по-старому.",
                     "При необходимости готовность персонала проверяется ежегодно.",
                     "Сотрудники могут оформить заявку через портал."):
            self.assertTrue(self.keeps(tail), tail)

    def test_a_real_offer_is_still_removed(self):
        for tail in ("Если нужно, я могу оформить это официальным документом.",
                     "Если хотите, могу дополнить разбор примерами.",
                     "Готов оформить это приложением.",
                     "Могу также подготовить презентацию."):
            self.assertFalse(self.keeps(tail), tail)

    def test_paragraphs_separated_by_one_newline_are_cleaned_too(self):
        text = "Текст работы.\nЕсли нужно, я могу оформить это таблицей."
        self.assertEqual(polish.clean_answer(text), "Текст работы.")


class VolumeTest(unittest.TestCase):
    """Three parsers disagreed about the same sentence."""

    def test_a_later_sentence_can_supply_the_floor(self):
        stated = coursework.read_volume("Работа на 5 страниц, не менее 1200 слов.")
        self.assertEqual(stated.floor, 1200)

    def test_a_ceiling_written_with_do_is_not_a_floor(self):
        stated = coursework.read_volume("Эссе объёмом до 2 000 знаков")
        self.assertEqual(stated.floor, 0)
        self.assertGreater(stated.ceiling, 0)

    def test_contradictory_bounds_keep_the_demand(self):
        stated = coursework.read_volume("Не более 2000 слов, но не менее 1200 слов.")
        self.assertEqual((stated.floor, stated.ceiling), (1200, 2000))

    def test_a_number_with_a_unit_is_not_always_a_size(self):
        for text in ("Напишите 1500 словосочетаний.", "Подготовьте 10 листовок.",
                     "Схему разместите на 2 страницах приложения."):
            self.assertEqual(coursework.read_volume(text).as_written, "", text)

    def test_a_limit_on_one_section_is_not_the_whole_work(self):
        self.assertEqual(coursework.read_volume("Сократите введение до 200 слов.")
                         .ceiling, 0)

    def test_a_range_is_not_prefixed_with_a_qualifier(self):
        self.assertEqual(coursework.read_volume("Объём: от 800 до 1200 слов")
                         .as_written, "800-1 200 слов")


class GradeTest(unittest.TestCase):
    """A retake scored zero showed the pre-retake mark."""

    def row(self, **extra):
        item = {"discipline": {"id": "d", "name": "X", "maxScore": 100},
                "studyPeriod": [{"name": "П", "endDate": "2025-01-01",
                                 "status": "FINISHED"}],
                "learningGroup": {"id": "g"}, "hasRetake": True,
                "retakeDisciplineGradeV2": "TWO", "retakeDisciplineGrade": "THREE",
                "disciplineGrade": "FIVE"}
        item.update(extra)
        return grades.parse_discipline(item)

    def test_a_zero_main_attempt_still_selects_the_retake_grade(self):
        # "elif main:" treated a score of 0 as absent.
        self.assertEqual(self.row(mainStudentAttempt={"scoreForAttempt": 0})["grade"], 2)

    def test_a_zero_retake_score_selects_the_retake_grade(self):
        self.assertEqual(self.row(retakeScore=0)["grade"], 3)

    def test_a_max_score_of_zero_is_not_replaced_by_a_hundred(self):
        self.assertEqual(grades.parse_discipline(
            {"discipline": {"maxScore": 0}})["max"], 0)

    def test_nan_does_not_crash_the_table(self):
        self.assertEqual(grades.format_number(float("nan")), "0")


class ContentTest(unittest.TestCase):
    def test_a_bare_angle_bracket_is_not_a_tag(self):
        # "<[^>]+>" deleted everything between a "<" and any later ">".
        self.assertEqual(content.html_to_text("если a < b и c > d, то конец"),
                         "если a < b и c > d, то конец")
        self.assertEqual(content.html_to_text("<p>текст</p>"), "текст")

    def test_a_name_of_dots_cannot_become_a_directory(self):
        self.assertEqual(content.safe_filename(".."), "topic")

    def test_ordered_lists_keep_their_numbers(self):
        body = '[{"type":"list","data":{"style":"ordered","items":["а","б"]}}]'
        self.assertEqual(content.body_to_text(body), "1. а\n2. б")

    def test_the_same_file_is_listed_once(self):
        topic = {"content": {"blocks": [{"body":
            '[{"type":"uploaderFileTool","data":{"file":{"url":"u","name":"a"}}},'
            ' {"type":"uploaderFileTool","data":{"file":{"url":"u","name":"a"}}}]'}]}}
        self.assertEqual(len(content.topic_attachments(topic)), 1)


class AttachmentTest(unittest.TestCase):
    def test_only_http_urls_are_fetched(self):
        # A content block could otherwise make the client read a local file
        # and paste it into a prompt sent to the AI provider.
        for url in ("file:///etc/passwd", "data:text/plain,hi", "ftp://x/y"):
            with self.assertRaises(attachments.AttachmentError, msg=url):
                attachments._download(url)

    def test_the_url_decides_the_format_not_the_name(self):
        self.assertEqual(attachments.file_extension("лекция.txt", "https://x/f.pdf"),
                         ".pdf")
        self.assertEqual(attachments.file_extension("Задание v1.2", "https://x/f.pdf"),
                         ".pdf")
        self.assertTrue(attachments.is_supported("Задание v1.2", "https://x/f.pdf"))


class SessionTest(unittest.TestCase):
    def test_a_non_numeric_expiry_is_ignored_not_fatal(self):
        import base64
        import json
        payload = base64.urlsafe_b64encode(
            json.dumps({"exp": "1760000000"}).encode()).decode().rstrip("=")
        self.assertIsNone(session_module._jwt_expiry("h.%s.s" % payload))


class ApiTest(unittest.TestCase):
    def test_a_non_string_error_message_does_not_crash(self):
        with mock.patch.object(api.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = \
                b'{"errors":[{"message":null}]}'
            with self.assertRaises(api.ApiError):
                api.execute("q", {})

    def test_forbidden_does_not_throw_away_the_session(self):
        # FORBIDDEN means "signed in, not allowed"; treating it as an
        # authentication failure logged the user out over one discipline.
        self.assertFalse(api._is_auth_error(
            [{"extensions": {"code": "FORBIDDEN"}}], "no access to discipline"))

    def test_a_message_about_an_email_in_use_is_not_an_auth_failure(self):
        self.assertFalse(api._is_auth_error(
            [{"message": "Пользователь с такой почтой уже существует"}],
            "Пользователь с такой почтой уже существует"))

    def test_wrong_credentials_still_are(self):
        self.assertTrue(api._is_auth_error(
            [{"message": "Неверная почта или пароль"}], "Неверная почта или пароль"))


class ExportTest(unittest.TestCase):
    def test_a_section_with_nothing_under_it_is_not_a_slide(self):
        slides = export.slides_from_text("T", "# Intro\n# Body\nТекст.\n# Вывод")
        self.assertEqual([s["title"] for s in slides], ["Body"])

    def test_identifiers_are_not_emphasis(self):
        self.assertEqual(export.clean_inline("метод __init__ в классе"),
                         "метод __init__ в классе")

    def test_an_abbreviation_does_not_end_a_sentence(self):
        self.assertEqual(export._sentences("В 1992 г. Москва изменилась."),
                         ["В 1992 г. Москва изменилась."])


class ChecksTest(unittest.TestCase):
    def test_an_empty_work_scores_zero_not_ninety(self):
        # With nothing to object to, every other check passed.
        self.assertEqual(checks.score(checks.run("", {})), 0.0)
        self.assertEqual(checks.score(checks.run("слово " * 5, {})), 0.0)
        self.assertEqual(checks.score(checks.run("Связный текст. " * 40, {})), 1.0)


class SelectorTest(unittest.TestCase):
    def test_out_of_range_input_selects_nothing(self):
        import contextlib
        import io

        for raw in ("0", "-1", "99", "x"):
            with mock.patch("sys.stdin", io.StringIO(raw + "\n")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(ui.select([("item", "a"), ("item", "b")]), raw)

    def test_rows_that_cannot_be_opened_are_still_shown(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("\n")), \
                contextlib.redirect_stdout(buffer):
            ui.select([("header", "Глава"), ("text", "  Тема для чтения")])
        self.assertIn("Тема для чтения", buffer.getvalue())


class OfferBeforeSignatureTest(unittest.TestCase):
    """A closing offer survived when the model signed the text after it."""

    def test_offer_followed_by_a_signature_is_removed(self):
        from newlxp import polish

        text = ("Текст работы основной.\n\nЕсли нужно, я могу оформить это "
                "в виде таблицы.\n\nИванов И.И.")
        self.assertEqual(polish.clean_answer(text, "Иванов Иван Иванович"),
                         "Текст работы основной.")

