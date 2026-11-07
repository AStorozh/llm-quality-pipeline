import io
import json
import unittest
import urllib.error
from unittest import mock

from newlxp import api


def response(body: dict):
    handle = mock.MagicMock()
    handle.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return handle


class ExecuteTest(unittest.TestCase):
    def run_with(self, **urlopen_kwargs):
        with mock.patch.object(api.urllib.request, "urlopen", **urlopen_kwargs):
            return api.execute("query { x }", {}, "token")

    def test_returns_data(self):
        self.assertEqual(self.run_with(return_value=response({"data": {"x": 1}})), {"x": 1})

    def test_http_401_is_auth_error(self):
        error = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b""))
        with self.assertRaises(api.AuthError):
            self.run_with(side_effect=error)

    def test_unauthenticated_code_is_auth_error(self):
        body = {"errors": [{"message": "nope", "extensions": {"code": "UNAUTHENTICATED"}}]}
        with self.assertRaises(api.AuthError):
            self.run_with(return_value=response(body))

    def test_wrong_password_message_is_auth_error(self):
        body = {"errors": [{"message": "Неверный пароль"}]}
        with self.assertRaises(api.AuthError):
            self.run_with(return_value=response(body))

    def test_other_error_is_api_error(self):
        body = {"errors": [{"message": "Internal server error"}]}
        with self.assertRaises(api.ApiError):
            self.run_with(return_value=response(body))

    def test_network_failure_is_api_error(self):
        with self.assertRaises(api.ApiError):
            self.run_with(side_effect=urllib.error.URLError("down"))
