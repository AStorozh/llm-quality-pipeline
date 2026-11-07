import base64
import json
import time
from unittest import mock

from helpers import TempDirTestCase

from newlxp import api
from newlxp import session as session_module
from newlxp.session import Session, _jwt_expiry


def make_jwt(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return "header.%s.signature" % payload


class SessionTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(session_module, "SESSION_FILE", self.path("s.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_jwt_expiry(self):
        self.assertEqual(_jwt_expiry(make_jwt(1234)), 1234)
        self.assertIsNone(_jwt_expiry("garbage"))

    def test_fresh_token_is_returned(self):
        token = make_jwt(int(time.time()) + 3600)
        self.assertEqual(Session(token, "r", {"id": 1}).valid_token(), token)

    def test_non_jwt_token_is_left_to_the_server(self):
        self.assertEqual(Session("opaque", None, {"id": 1}).valid_token(), "opaque")

    def test_expired_without_refresh_raises(self):
        with self.assertRaises(api.AuthError):
            Session(make_jwt(1), None, {"id": 1}).valid_token()

    def test_expired_refreshes_and_saves(self):
        new = make_jwt(int(time.time()) + 3600)
        with mock.patch.object(api, "refresh_access_token", return_value=new) as refresh:
            s = Session(make_jwt(1), "refresh", {"id": 1})
            self.assertEqual(s.valid_token(), new)
        refresh.assert_called_once_with("refresh")
        self.assertEqual(Session.load().access, new)

    def test_failed_refresh_raises(self):
        failure = api.AuthError("не удалось обновить токен")
        with mock.patch.object(api, "refresh_access_token", side_effect=failure):
            with self.assertRaises(api.AuthError):
                Session(make_jwt(1), "refresh", {"id": 1}).valid_token()

    def test_save_load_forget(self):
        Session("a", "r", {"id": 7, "lastName": "Иванов", "firstName": "Иван"}).save()
        loaded = Session.load()
        self.assertEqual(loaded.user["id"], 7)
        self.assertEqual(loaded.full_name, "Иванов Иван")
        self.assertEqual(loaded.initials, "И.И")
        Session.forget()
        self.assertIsNone(Session.load())

    def test_initials(self):
        user = {"lastName": "петров", "firstName": "Пётр", "middleName": " Петрович "}
        session = Session("a", None, user)
        self.assertEqual(session.initials, "П.П.П")
        self.assertEqual(session.full_name, "петров Пётр Петрович")
