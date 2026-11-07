"""Fixes for problems found in the pre-publication audit."""
import io
import os
import unittest
import urllib.error
from unittest import mock

from helpers import TempDirTestCase

from newlxp import ai, api, checks, export


class TruncatedAnswerTest(unittest.TestCase):
    """An answer cut off by the token limit used to be saved as complete."""

    def complete(self, provider, reply):
        cfg = {"provider": provider, "api_key": "k", "model": "m"}
        with mock.patch.object(ai, "_post_json", return_value=reply):
            return ai.complete(cfg, "system", "user")

    def test_openai_length_stop_is_reported(self):
        reply = {"choices": [{"message": {"content": "текст"}, "finish_reason": "length"}]}
        self.assertTrue(self.complete("openai", reply).truncated)

    def test_openai_normal_stop_is_not_truncated(self):
        reply = {"choices": [{"message": {"content": "текст"}, "finish_reason": "stop"}]}
        self.assertFalse(self.complete("openai", reply).truncated)

    def test_anthropic_max_tokens_stop_is_reported(self):
        reply = {"content": [{"type": "text", "text": "текст"}], "stop_reason": "max_tokens"}
        self.assertTrue(self.complete("anthropic", reply).truncated)

    def test_anthropic_end_turn_is_not_truncated(self):
        reply = {"content": [{"type": "text", "text": "текст"}], "stop_reason": "end_turn"}
        self.assertFalse(self.complete("anthropic", reply).truncated)


class Http403Test(unittest.TestCase):
    """"Signed in, not allowed" must not throw the session away."""

    def run_with(self, body: bytes):
        error = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(body))
        with mock.patch.object(api.urllib.request, "urlopen", side_effect=error):
            return api.execute("query { x }", {}, "token")

    def test_empty_403_is_an_api_error(self):
        with self.assertRaises(api.ApiError) as caught:
            self.run_with(b"")
        self.assertNotIsInstance(caught.exception, api.AuthError)

    def test_forbidden_code_is_an_api_error(self):
        body = b'{"errors": [{"message": "no", "extensions": {"code": "FORBIDDEN"}}]}'
        with self.assertRaises(api.ApiError) as caught:
            self.run_with(body)
        self.assertNotIsInstance(caught.exception, api.AuthError)

    def test_unauthenticated_code_in_a_403_is_still_auth(self):
        body = b'{"errors": [{"message": "no", "extensions": {"code": "UNAUTHENTICATED"}}]}'
        with self.assertRaises(api.AuthError):
            self.run_with(body)


class PreviousVersionTest(TempDirTestCase):
    """Generating a checkpoint again used to overwrite the last file silently."""

    def test_existing_file_is_kept_as_previous(self):
        export.save_all(self.tmp, "work", ["Работа"], "Первая версия.", ["md"])
        export.save_all(self.tmp, "work", ["Работа"], "Вторая версия.", ["md"])
        with open(os.path.join(self.tmp, "work_previous.md"), encoding="utf-8") as fh:
            self.assertIn("Первая версия.", fh.read())
        with open(os.path.join(self.tmp, "work.md"), encoding="utf-8") as fh:
            self.assertIn("Вторая версия.", fh.read())

    def test_first_save_makes_no_backup(self):
        export.save_all(self.tmp, "work", ["Работа"], "Текст.", ["md"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "work_previous.md")))


class FiguresAgainstMaterialsTest(unittest.TestCase):
    """One figure anywhere in the materials used to clear every figure."""

    def test_a_figure_missing_from_the_materials_is_flagged(self):
        result = checks.check_no_invented_figures(
            "Доля выросла на 47%, а выручка на 93%.", "Рост составил 12% и 47%.")
        self.assertEqual(result.status, checks.WARN)
        self.assertIn("1 figure", result.detail)

    def test_figures_in_other_wording_still_match(self):
        result = checks.check_no_invented_figures(
            "Доля выросла на 47 процентов.", "Рост составил 47%.")
        self.assertEqual(result.status, checks.PASS)
