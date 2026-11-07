"""An end-to-end run through the real screens.

Everything outside the program is replaced - the platform API, the model,
the home directory - but the flow is the genuine one: the menu, the
discipline list, the checkpoint screen, generation, export. A crash anywhere
in those screens fails this test, which unit tests of individual printers
would not catch.
"""
import io
import os
from contextlib import redirect_stdout
from unittest import mock

from helpers import TempDirTestCase

from newlxp import ai, api, app, config, coursework, usage
from newlxp import session as session_module

WORK = ("Корпоративное управление отделяет собственность от управления, и "
        "именно отсюда растут его главные трудности. " * 40)

PROFILE = {"id": "u1", "email": "user@example.ru", "lastName": "Петров",
           "firstName": "Пётр", "middleName": "Петрович"}

DISCIPLINES = [{
    "discipline": {"id": "d1", "name": "Корпоративный менеджмент", "maxScore": 100},
    "learningGroup": {"id": "g1"},
    "studyPeriod": [{"name": "Весна 26", "endDate": "2026-06-30", "status": "FINISHED"}],
    "scoreForAnsweredTasks": 87, "disciplineGrade": "FIVE",
}]

TOPICS = {"id": "d1", "name": "Корпоративный менеджмент", "chapters": [
    {"id": "c1", "name": "Введение", "topics": [
        {"id": "t1", "name": "Корпорация", "isCheckPoint": False},
        {"id": "k1", "name": 'КТ №1 "Эссе"', "isCheckPoint": True, "maxScore": 10},
    ]},
]}

CONTENT = {
    "t1": {"name": "Корпорация", "content": {"blocks": [
        {"name": "Текст", "body": '[{"type":"paragraph","data":{"text":"Материал."}}]'}]}},
    "k1": {"name": 'КТ №1 "Эссе"',
           "content": {"howStudyIt": "Напишите эссе на 300 слов."}},
}


class EndToEndTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.patches = [
            mock.patch.object(config, "CONFIG_FILE", self.path("ai.json")),
            mock.patch.object(session_module, "SESSION_FILE", self.path("session.json")),
            mock.patch.object(coursework, "OUTPUT_ROOT", self.path("ai_output")),
            mock.patch.object(coursework, "CACHE_ROOT", self.path("cache")),
            mock.patch.object(usage, "LOG_FILE", self.path("usage.jsonl")),
            mock.patch.object(app, "ERROR_LOG", self.path("error.log")),
            mock.patch.object(api, "sign_in",
                              return_value={"accessToken": "a", "refreshToken": "r",
                                            "user": {"id": "u1"}}),
            mock.patch.object(api, "get_me", return_value=PROFILE),
            mock.patch.object(api, "search_student_disciplines", return_value=DISCIPLINES),
            mock.patch.object(api, "get_discipline_with_topics", return_value=TOPICS),
            mock.patch.object(api, "get_topic_content",
                              side_effect=lambda token, tid: CONTENT[tid]),
            mock.patch.object(ai, "complete",
                              return_value=ai.Answer(WORK, "test-model", 1200, 450)),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        config.save("openai", "sk-test", "test-model")
        # Markdown needs no optional library, so this runs on a bare
        # interpreter; the Word and slide writers have their own tests.
        config.set_formats(["md"])

    # Intro, then the sign-in screen asks for an email and a password.
    START = ["", "user@example.ru", "secret"]

    def run_app(self, keys):
        """Drive the program through its non-TTY fallback and return output."""
        buffer = io.StringIO()
        keys = self.START + keys
        with mock.patch("sys.stdin", io.StringIO("\n".join(keys) + "\n")), \
                redirect_stdout(buffer):
            code = app.main()
        return code, buffer.getvalue()

    def test_a_full_run_writes_a_work_and_exits_cleanly(self):
        # intro, menu->disciplines, discipline, checkpoint, start, back, back, exit
        code, output = self.run_app(["1", "1", "2", "1", "", "", "", "4"])
        self.assertEqual(code, 0)
        self.assertIn("Корпоративный менеджмент", output)

        folder = os.path.join(self.path("ai_output"), "Корпоративный_менеджмент")
        produced = os.listdir(folder)
        self.assertTrue(produced, "no file was written")
        self.assertTrue(any(n.startswith("КТ1_") and n.endswith(".md")
                            for n in produced), produced)
        self.assertNotIn("Unexpected error", output)
        self.assertNotIn("Traceback", output)

    def test_the_run_is_costed_and_checked(self):
        _code, output = self.run_app(["1", "1", "2", "1", "", "", "", "4"])
        self.assertIn("cost", output)
        self.assertIn("checks:", output)
        runs = usage.read_log(self.path("usage.jsonl"))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].input_tokens, 1200)

    def test_the_work_is_remembered_for_the_next_checkpoint(self):
        self.run_app(["1", "1", "2", "1", "", "", "", "4"])
        self.assertTrue(coursework.load_works_index("Корпоративный менеджмент"))

    def test_browsing_without_generating_changes_nothing(self):
        code, _ = self.run_app(["1", "1", "", "", "4"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.path("ai_output")))

    def test_settings_are_reachable_and_leave_the_key_intact(self):
        code, output = self.run_app(["2", "", "4"])
        self.assertEqual(code, 0)
        self.assertIn("AI settings", output)
        self.assertEqual(config.load()["api_key"], "sk-test")

    def test_an_api_failure_is_shown_not_a_traceback(self):
        with mock.patch.object(api, "search_student_disciplines",
                               side_effect=api.ApiError("сервер недоступен")):
            code, output = self.run_app(["1", "", "4"])
        self.assertEqual(code, 0)
        self.assertIn("сервер недоступен", output)
        self.assertNotIn("Traceback", output)

    def test_an_ai_failure_does_not_lose_the_session(self):
        with mock.patch.object(ai, "complete", side_effect=ai.AIError("rate limit")):
            code, output = self.run_app(["1", "1", "2", "1", "", "", "", "4"])
        self.assertEqual(code, 0)
        self.assertIn("rate limit", output)
        self.assertIn("See you!", output)

    def test_an_unexpected_bug_is_caught_and_logged(self):
        with mock.patch.object(api, "get_discipline_with_topics",
                               side_effect=RuntimeError("boom")):
            code, output = self.run_app(["1", "1", "", "4"])
        self.assertEqual(code, 0)
        self.assertIn("Unexpected error", output)
        self.assertTrue(os.path.exists(self.path("error.log")))

    def test_an_expired_session_sends_the_user_back_to_login(self):
        with mock.patch.object(api, "search_student_disciplines",
                               side_effect=api.AuthError("session expired")):
            code, output = self.run_app(["1", "user@example.ru", "secret", "4"])
        self.assertEqual(code, 0)
        self.assertIn("Session expired", output)
