import io
import unittest
import urllib.error
from unittest import mock

from newlxp import ai


class CompleteTest(unittest.TestCase):
    def complete(self, provider, reply):
        cfg = {"provider": provider, "api_key": "k", "model": "m"}
        with mock.patch.object(ai, "_post_json", return_value=reply) as post:
            return ai.complete(cfg, "system", "user").text, post.call_args[0]

    def test_openai(self):
        text, (url, headers, payload) = self.complete(
            "openai", {"choices": [{"message": {"content": " ответ "}}]})
        self.assertEqual(text, "ответ")
        self.assertIn("openai.com", url)
        self.assertEqual(headers["authorization"], "Bearer k")
        self.assertEqual(payload["max_completion_tokens"], ai.MAX_OUTPUT_TOKENS)
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "system"})

    def test_anthropic_joins_text_blocks(self):
        reply = {"content": [{"type": "thinking", "thinking": "..."},
                             {"type": "text", "text": "часть 1 "},
                             {"type": "text", "text": "часть 2"}]}
        text, (url, headers, payload) = self.complete("anthropic", reply)
        self.assertEqual(text, "часть 1 часть 2")
        self.assertEqual(headers["x-api-key"], "k")
        self.assertEqual(payload["system"], "system")

    def test_empty_answers_are_errors(self):
        with self.assertRaises(ai.AIError):
            self.complete("openai", {"choices": [{"message": {"content": None}}]})
        with self.assertRaises(ai.AIError):
            self.complete("anthropic", {"content": []})
        with self.assertRaises(ai.AIError):
            self.complete("openai", {"unexpected": True})

    def test_unknown_provider(self):
        with self.assertRaises(ai.AIError):
            ai.complete({"provider": "x"}, "s", "u")

    def test_http_errors(self):
        for code, fragment in ((401, "token"), (429, "429"), (500, "500")):
            error = urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))
            with mock.patch.object(ai.urllib.request, "urlopen", side_effect=error), \
                    mock.patch.object(ai.time, "sleep"):
                with self.assertRaises(ai.AIError) as caught:
                    ai._post_json("https://x", {}, {})
            self.assertIn(fragment, str(caught.exception))


class ReasoningBudgetTest(unittest.TestCase):
    def budget(self, model):
        cfg = {"provider": "openai", "api_key": "k", "model": model}
        reply = {"choices": [{"message": {"content": "ok"}}]}
        with mock.patch.object(ai, "_post_json", return_value=reply) as post:
            ai.complete(cfg, "s", "u")
        return post.call_args[0][2]["max_completion_tokens"]

    def test_reasoning_models_get_extra_tokens(self):
        self.assertEqual(self.budget("gpt-4o-mini"), ai.MAX_OUTPUT_TOKENS)
        for model in ("gpt-5.4-mini", "o3", "gpt-6-sol"):
            self.assertEqual(self.budget(model), ai.MAX_OUTPUT_TOKENS + ai.REASONING_TOKENS)


class ListModelsTest(unittest.TestCase):
    def test_openai_filters_and_sorts(self):
        reply = {"data": [
            {"id": "gpt-4o-mini", "created": 1},
            {"id": "gpt-5.5", "created": 3},
            {"id": "gpt-5.5-2026-04-23", "created": 3},
            {"id": "gpt-4-0613", "created": 0},
            {"id": "gpt-4o-mini-tts", "created": 2},
            {"id": "gpt-5.5-pro", "created": 4},
            {"id": "gpt-5.3-codex", "created": 4},
            {"id": "text-embedding-3-small", "created": 5},
            {"id": "o4-mini", "created": 2},
        ]}
        with mock.patch.object(ai, "_get_json", return_value=reply) as get:
            models = ai.list_models("openai", "k")
        self.assertEqual(models, ["gpt-5.5", "o4-mini", "gpt-4o-mini"])
        self.assertEqual(get.call_args[0][1]["authorization"], "Bearer k")

    def test_anthropic_keeps_api_order(self):
        reply = {"data": [{"id": "claude-opus-5-5"}, {"id": "claude-haiku-5-5"}, {"id": "x"}]}
        with mock.patch.object(ai, "_get_json", return_value=reply) as get:
            models = ai.list_models("anthropic", "k")
        self.assertEqual(models, ["claude-opus-5-5", "claude-haiku-5-5"])
        self.assertEqual(get.call_args[0][1]["x-api-key"], "k")

    def test_unknown_provider(self):
        with self.assertRaises(ai.AIError):
            ai.list_models("x", "k")


class RetryTest(unittest.TestCase):
    """Transient failures are retried; permanent ones are not."""

    def send(self, side_effect):
        request = mock.MagicMock()
        with mock.patch.object(ai.urllib.request, "urlopen",
                               side_effect=side_effect) as urlopen, \
                mock.patch.object(ai.time, "sleep") as sleep:
            try:
                return ai._send(request), urlopen.call_count, sleep.call_args_list
            except ai.AIError as exc:
                return exc, urlopen.call_count, sleep.call_args_list

    @staticmethod
    def http(code, headers=None):
        return urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(b"{}"))

    @staticmethod
    def ok(payload=b'{"ok": true}'):
        handle = mock.MagicMock()
        handle.__enter__.return_value.read.return_value = payload
        return handle

    def test_a_rate_limit_is_retried_until_it_succeeds(self):
        result, attempts, sleeps = self.send([self.http(429), self.http(429), self.ok()])
        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts, 3)
        self.assertEqual(len(sleeps), 2)

    def test_server_errors_are_retried(self):
        for code in (500, 502, 503, 504, 408):
            _result, attempts, _ = self.send([self.http(code), self.ok()])
            self.assertEqual(attempts, 2, code)

    def test_it_gives_up_after_the_limit(self):
        result, attempts, _ = self.send([self.http(429)] * 10)
        self.assertIsInstance(result, ai.AIError)
        self.assertIn("gave up after %d attempts" % ai.MAX_ATTEMPTS, str(result))
        self.assertEqual(attempts, ai.MAX_ATTEMPTS)

    def test_a_bad_token_is_not_retried(self):
        result, attempts, _ = self.send([self.http(401)])
        self.assertIn("token", str(result))
        self.assertEqual(attempts, 1)

    def test_an_unknown_client_error_is_not_retried(self):
        _result, attempts, _ = self.send([self.http(400)])
        self.assertEqual(attempts, 1)

    def test_network_failures_are_retried(self):
        _result, attempts, _ = self.send([urllib.error.URLError("down"), self.ok()])
        self.assertEqual(attempts, 2)

    def test_retry_after_header_is_obeyed(self):
        headers = {"retry-after": "7"}
        _result, _attempts, sleeps = self.send([self.http(429, headers), self.ok()])
        self.assertEqual(sleeps[0].args[0], 7.0)

    def test_backoff_grows_and_is_capped(self):
        delays = [ai._sleep_for(attempt, 0) for attempt in range(1, 8)]
        self.assertLess(delays[0], delays[-1])
        self.assertLessEqual(max(delays), ai.BACKOFF_CAP)
        self.assertEqual(ai._sleep_for(1, 999), ai.BACKOFF_CAP)  # hint is capped too


class UsageTest(unittest.TestCase):
    def test_openai_usage_is_reported(self):
        reply = {"choices": [{"message": {"content": "ответ"}}],
                 "usage": {"prompt_tokens": 120, "completion_tokens": 30}}
        with mock.patch.object(ai, "_post_json", return_value=reply):
            answer = ai.complete({"provider": "openai", "api_key": "k", "model": "m"},
                                 "s", "u")
        self.assertEqual((answer.input_tokens, answer.output_tokens), (120, 30))
        self.assertEqual(answer.total_tokens, 150)
        self.assertEqual(answer.model, "m")

    def test_anthropic_usage_is_reported(self):
        reply = {"content": [{"type": "text", "text": "ответ"}],
                 "usage": {"input_tokens": 7, "output_tokens": 3}}
        with mock.patch.object(ai, "_post_json", return_value=reply):
            answer = ai.complete({"provider": "anthropic", "api_key": "k", "model": "m"},
                                 "s", "u")
        self.assertEqual(answer.total_tokens, 10)

    def test_a_reply_without_usage_reports_zero(self):
        reply = {"choices": [{"message": {"content": "ответ"}}]}
        with mock.patch.object(ai, "_post_json", return_value=reply):
            answer = ai.complete({"provider": "openai", "api_key": "k", "model": "m"},
                                 "s", "u")
        self.assertEqual(answer.total_tokens, 0)


class JsonModeTest(unittest.TestCase):
    def test_openai_asks_for_a_json_object(self):
        reply = {"choices": [{"message": {"content": "{}"}}]}
        with mock.patch.object(ai, "_post_json", return_value=reply) as post:
            ai.complete({"provider": "openai", "api_key": "k", "model": "m"},
                        "s", "u", json_mode=True)
        self.assertEqual(post.call_args[0][2]["response_format"],
                         {"type": "json_object"})

    def test_anthropic_prefills_the_brace_and_puts_it_back(self):
        reply = {"content": [{"type": "text", "text": '"a": 1}'}]}
        with mock.patch.object(ai, "_post_json", return_value=reply) as post:
            answer = ai.complete({"provider": "anthropic", "api_key": "k", "model": "m"},
                                 "s", "u", json_mode=True)
        self.assertEqual(post.call_args[0][2]["messages"][-1],
                         {"role": "assistant", "content": "{"})
        self.assertEqual(answer.text, '{"a": 1}')

    def test_json_mode_is_off_by_default(self):
        reply = {"choices": [{"message": {"content": "x"}}]}
        with mock.patch.object(ai, "_post_json", return_value=reply) as post:
            ai.complete({"provider": "openai", "api_key": "k", "model": "m"}, "s", "u")
        self.assertNotIn("response_format", post.call_args[0][2])
