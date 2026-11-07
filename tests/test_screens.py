"""The screens hold real logic, not just printing: grouping, de-duplication
and row rendering. Those parts are tested here; the key-loop itself is
exercised through the non-TTY fallback in the smoke tests."""
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from newlxp import api, app, ui
from newlxp.screens import disciplines, generate, intro, prompts
from newlxp.session import Session


def discipline(did, name, group, period, end, score=50, grade=4):
    return {
        "discipline": {"id": did, "name": name, "maxScore": 100},
        "learningGroup": {"id": group},
        "studyPeriod": [{"name": period, "endDate": end, "status": "FINISHED"}],
        "scoreForAnsweredTasks": score,
        "disciplineGrade": grade,
    }


class DisciplineEntriesTest(unittest.TestCase):
    def entries(self, raw):
        session = Session("t", None, {"id": "u1"})
        with mock.patch.object(disciplines.api, "search_student_disciplines",
                               return_value=raw), \
                mock.patch.object(Session, "valid_token", return_value="t"), \
                redirect_stdout(io.StringIO()):
            return disciplines._discipline_entries(session)

    def test_grouped_by_period_newest_first(self):
        raw = [discipline("a", "Старая", "g1", "Осень 24", "2024-12-31"),
               discipline("b", "Новая", "g2", "Весна 26", "2026-06-30")]
        entries, count = self.entries(raw)
        headers = [v for kind, v in entries if kind == "header"]
        self.assertEqual(headers, ["Весна 26 (1)", "Осень 24 (1)"])
        self.assertEqual(count, 2)

    def test_duplicates_are_removed_by_discipline_and_group(self):
        raw = [discipline("a", "X", "g1", "Осень", "2025-01-01"),
               discipline("a", "X", "g1", "Осень", "2025-01-01"),   # same pair
               discipline("a", "X", "g2", "Осень", "2025-01-01")]   # other group
        entries, count = self.entries(raw)
        self.assertEqual(count, 2)
        self.assertEqual([v for kind, v in entries if kind == "header"], ["Осень (2)"])

    def test_junk_rows_are_skipped_not_fatal(self):
        raw = [None, "строка", 42, discipline("a", "X", "g", "Осень", "2025-01-01")]
        _entries, count = self.entries(raw)
        self.assertEqual(count, 1)

    def test_no_disciplines_at_all(self):
        entries, count = self.entries([])
        self.assertEqual((entries, count), ([], 0))

    def test_a_period_without_an_end_date_still_appears(self):
        raw = [discipline("a", "X", "g", "Без даты", None),
               discipline("b", "Y", "g", "Весна", "2026-06-30")]
        entries, count = self.entries(raw)
        self.assertEqual(count, 2)
        self.assertEqual(len([1 for kind, _ in entries if kind == "header"]), 2)


class RowRenderingTest(unittest.TestCase):
    def test_a_long_name_is_truncated_not_wrapped(self):
        row = {"name": "Э" * 120, "score": 87, "max": 100, "grade": 5}
        line = ui.strip_ansi(disciplines._discipline_line(row, False, name_width=20))
        self.assertIn("…", line)
        self.assertNotIn("\n", line)

    def test_a_missing_grade_shows_zero(self):
        row = {"name": "X", "score": 10, "max": 100, "grade": None}
        self.assertIn("0", ui.strip_ansi(disciplines._discipline_line(row, False)))

    def test_the_selected_row_is_marked(self):
        row = {"name": "X", "score": 1, "max": 2, "grade": 3}
        selected = ui.strip_ansi(disciplines._discipline_line(row, True))
        plain = ui.strip_ansi(disciplines._discipline_line(row, False))
        self.assertIn("▶", selected)
        self.assertNotIn("▶", plain)

    def test_checkpoint_and_study_rows_differ(self):
        checkpoint = {"kind": "topic", "topic": {"name": "КТ1", "is_checkpoint": True,
                                                 "max_score": 15}}
        study = {"kind": "topic", "topic": {"name": "Тема", "is_checkpoint": False}}
        self.assertIn("Checkpoint", ui.strip_ansi(disciplines._topic_line(checkpoint, False)))
        self.assertIn("15 pt", ui.strip_ansi(disciplines._topic_line(checkpoint, False)))
        self.assertIn("Study topic", ui.strip_ansi(disciplines._topic_line(study, False)))

    def test_the_all_checkpoints_row(self):
        line = ui.strip_ansi(disciplines._topic_line({"kind": "all"}, False))
        self.assertIn("Write every checkpoint", line)

    def test_a_topic_without_a_name_does_not_crash(self):
        row = {"kind": "topic", "topic": {}}
        self.assertIsInstance(disciplines._topic_line(row, False), str)


class IntroTest(unittest.TestCase):
    def test_the_logo_is_a_rectangle(self):
        rows = intro._build_logo()
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({len(r.rstrip()) > 0 for r in rows}), 1)

    def test_shimmer_keeps_the_text_when_colour_is_off(self):
        with mock.patch.object(ui.Color, "_enabled", False):
            self.assertEqual(intro._shimmer("abc", 0), "abc")

    def test_shimmer_does_not_lose_characters(self):
        with mock.patch.object(ui.Color, "_enabled", True):
            self.assertEqual(ui.strip_ansi(intro._shimmer("ab c", 3)), "ab c")


class MenuHeaderTest(unittest.TestCase):
    def test_initials_and_name(self):
        session = Session("t", None, {"lastName": "Иванов", "firstName": "Иван",
                                      "email": "i@x.ru"})
        with mock.patch.object(app.config, "load", return_value=None):
            text = ui.strip_ansi("\n".join(app._menu_header(session)))
        self.assertIn("ИИ", text)
        self.assertIn("i@x.ru", text)
        self.assertIn("not connected", text)

    def test_a_user_without_a_name_does_not_crash(self):
        with mock.patch.object(app.config, "load", return_value=None):
            text = ui.strip_ansi("\n".join(app._menu_header(Session("t", None, {}))))
        self.assertIn("no name", text)


class NameNoteTest(unittest.TestCase):
    def test_with_and_without_a_name(self):
        self.assertIn("Петров", prompts.name_note("Петров Пётр"))
        self.assertIn("student name", prompts.name_note(""))


class ReportChecksTest(unittest.TestCase):
    """The post-run report must never break a finished generation."""

    def report(self, work, task):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            generate._report_checks(work, task)
        return ui.strip_ansi(buffer.getvalue())

    def test_a_clean_work_reports_all_passed(self):
        task = "Напишите разбор темы."
        text = self.report("Связный текст про управление. " * 30, task)
        self.assertIn("checks:", text)
        self.assertIn("checks passed", text)

    def test_failures_are_listed(self):
        task = "Напишите эссе объёмом примерно 1500-2000 слов."
        text = self.report("Коротко.", task)
        self.assertIn("length", text)

    def test_it_swallows_its_own_errors(self):
        with mock.patch.object(generate.checks, "run", side_effect=RuntimeError("boom")):
            self.assertEqual(self.report("текст", "задание"), "")


class ApiQueryTest(unittest.TestCase):
    """The query helpers encode the request shape; a typo here breaks a screen."""

    def test_sign_in_sends_the_credentials_and_returns_tokens(self):
        data = {"signIn": {"accessToken": "a", "refreshToken": "r", "user": {"id": "u"}}}
        with mock.patch.object(api, "execute", return_value=data) as call:
            result = api.sign_in("mail@x.ru", "secret")
        self.assertEqual(result["accessToken"], "a")
        self.assertEqual(call.call_args[0][1]["input"],
                         {"email": "mail@x.ru", "password": "secret"})

    def test_sign_in_without_a_token_is_an_auth_error(self):
        for data in ({"signIn": {}}, {"signIn": {"accessToken": "a", "user": {}}}):
            with mock.patch.object(api, "execute", return_value=data):
                with self.assertRaises(api.AuthError):
                    api.sign_in("m", "p")

    def test_refresh_returns_the_new_token(self):
        with mock.patch.object(api, "execute",
                               return_value={"refreshToken": {"accessToken": "new"}}):
            self.assertEqual(api.refresh_access_token("old"), "new")
        with mock.patch.object(api, "execute", return_value={"refreshToken": {}}):
            with self.assertRaises(api.AuthError):
                api.refresh_access_token("old")

    def test_get_me_tolerates_an_empty_answer(self):
        with mock.patch.object(api, "execute", return_value={}):
            self.assertEqual(api.get_me("t"), {})

    def test_discipline_queries_pass_their_identifiers(self):
        with mock.patch.object(api, "execute", return_value={}) as call:
            self.assertEqual(api.search_student_disciplines("t", "u1"), [])
        self.assertEqual(call.call_args[0][1]["input"], {"studentId": "u1"})

        with mock.patch.object(api, "execute", return_value={}) as call:
            self.assertEqual(api.get_discipline_with_topics("t", "d1"), {})
        self.assertEqual(call.call_args[0][1]["input"], {"disciplineId": "d1"})

        with mock.patch.object(api, "execute", return_value={}) as call:
            self.assertEqual(api.get_topic_content("t", "t1"), {})
        self.assertEqual(call.call_args[0][1]["input"], {"disciplineTopicId": "t1"})
