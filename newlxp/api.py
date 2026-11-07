"""GraphQL transport and typed query helpers for the newLXP API.

This module isolates every network concern: building the SSL context,
executing GraphQL documents, translating transport/server failures into the
two domain exceptions below, and exposing small helper functions for each
query the application needs.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

API_URL = "https://api.newlxp.ru/graphql"
REQUEST_TIMEOUT = 30  # seconds


def _build_ssl_context() -> ssl.SSLContext | None:
    """Return an SSL context, preferring certifi's CA bundle.

    Python builds on macOS frequently ship without a usable system CA bundle,
    so we fall back to certifi when it is installed and finally to the system
    defaults.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - certifi missing or broken
        try:
            return ssl.create_default_context()
        except Exception:  # noqa: BLE001
            return None


SSL_CONTEXT = _build_ssl_context()


class AuthError(Exception):
    """Invalid credentials or an expired/rejected session."""


class ApiError(Exception):
    """Network failure or a server-side error that is not auth related."""


# Markers that identify an authentication failure in a GraphQL error: the
# standard ``extensions.code`` values and keywords from the server messages
# (wrong email/password, missing or expired token).
# FORBIDDEN is deliberately absent: it means "signed in, not allowed", and
# treating it as an authentication failure would throw away a perfectly
# good session over one inaccessible discipline.
_AUTH_CODES = {"UNAUTHENTICATED", "UNAUTHORIZED"}
# Fallback for servers that send no code. Phrases, not stems: "почт" alone
# also matches "Пользователь с такой почтой уже существует".
_AUTH_KEYWORDS = ("неверн", "incorrect", "invalid credential", "unauthenticated",
                  "unauthorized", "token expired", "jwt expired", "jwt malformed",
                  "не авторизован", "истек")


def _is_auth_error(errors: list, message: str) -> bool:
    """True if GraphQL ``errors`` describe an authentication failure."""
    for err in errors:
        code = str((err.get("extensions") or {}).get("code") or "").upper()
        if code in _AUTH_CODES:
            return True
    lowered = message.lower()
    return any(keyword in lowered for keyword in _AUTH_KEYWORDS)


def execute(query: str, variables: dict, token: str | None = None) -> dict:
    """Execute a GraphQL document and return its ``data`` object.

    Raises :class:`AuthError` for authentication problems and
    :class:`ApiError` for any other transport or server failure.
    """
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = "Bearer " + token

    try:
        payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = urllib.request.Request(API_URL, data=payload, headers=headers)
        with urllib.request.urlopen(
            request, context=SSL_CONTEXT, timeout=REQUEST_TIMEOUT
        ) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("session expired or invalid")
        # GraphQL returns useful error bodies even on HTTP 400. A 403 is read
        # the same way: "signed in, not allowed" must not drop the session,
        # while an UNAUTHENTICATED code in its body still does.
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001
            raw = b""
        if not raw.strip():
            if exc.code == 403:
                raise ApiError("access denied (HTTP 403)")
            raise ApiError("HTTP %s" % exc.code)
    except urllib.error.URLError as exc:
        raise ApiError("cannot reach the server (%s)" % exc.reason)
    except TimeoutError:
        raise ApiError("the server did not answer within %s s" % REQUEST_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(str(exc))

    try:
        body = json.loads(raw)
    except Exception:  # noqa: BLE001
        raise ApiError("unreadable response from the server")

    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        errors = [e for e in errors if isinstance(e, dict)]
        # A server may answer with a null or structured message; joining
        # those directly would raise a TypeError out of execute().
        message = "; ".join(str(e.get("message") or "") for e in errors).strip("; ")
        if _is_auth_error(errors, message):
            raise AuthError(message or "authentication error")
        raise ApiError(message or "API error")

    data = body.get("data") if isinstance(body, dict) else None
    if not data:
        raise ApiError("empty response from the server")
    return data


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

_SIGN_IN = """
query SignIn($input: SignInInput!) {
  signIn(input: $input) {
    accessToken
    refreshToken
    user { id }
  }
}
"""

_REFRESH = """
query RefreshToken($input: RefreshTokenInput!) {
  refreshToken(input: $input) { accessToken }
}
"""

_GET_ME = """
query GetMe {
  getMe { id email firstName lastName middleName }
}
"""


def sign_in(email: str, password: str) -> dict:
    """Authenticate and return ``{accessToken, refreshToken, user}``."""
    data = execute(_SIGN_IN, {"input": {"email": email, "password": password}})
    result = data.get("signIn") or {}
    if not result.get("accessToken") or not (result.get("user") or {}).get("id"):
        raise AuthError("the server returned no token")
    return result


def refresh_access_token(refresh_token: str) -> str:
    """Exchange a refresh token for a fresh access token."""
    data = execute(_REFRESH, {"input": {"token": refresh_token}})
    token = (data.get("refreshToken") or {}).get("accessToken")
    if not token:
        raise AuthError("could not refresh the token")
    return token


def get_me(token: str) -> dict:
    """Return the profile of the currently authenticated user."""
    return execute(_GET_ME, {}, token).get("getMe") or {}


# --------------------------------------------------------------------------- #
# Domain queries
# --------------------------------------------------------------------------- #

_SEARCH_DISCIPLINES = """
query SearchStudentDisciplines($input: SearchStudentDisciplinesInput!, $e: String) {
  searchStudentDisciplines(input: $input) {
    disciplineId
    discipline { id name maxScore }
    learningGroup { id name }
    studyPeriod { name endDate status }
    scoreForAnsweredTasks
    studentRecalculationScore { academicDifferenceAbsoluteScore }
    mainStudentAttempt { scoreForAttempt }
    retakeScore
    scoreForAnsweredRetakeTasks
    hasRetake
    hasRetakeV1
    disciplineGrade(studyPeriodEndDate: $e)
    retakeDisciplineGrade
    retakeDisciplineGradeV2
  }
}
"""

_DISCIPLINE_WITH_TOPICS = """
query GetDisciplineWithTopics($input: GetDisciplineByIdInput!) {
  getDisciplineById(input: $input) {
    id
    name
    chapters {
      id
      name
      topics { id name isCheckPoint maxScore }
    }
  }
}
"""

_TOPIC_CONTENT = """
query GetTopic($input: GetDisciplineTopicByIdInput!) {
  getDisciplineTopicById(input: $input) {
    name
    content {
      whyStudyIt
      howStudyIt
      blocks {
        ... on InfoDisciplineTopicContentBlock { name body }
        ... on TaskDisciplineTopicContentBlock { name body }
        ... on TestDisciplineTopicContentBlock { name body }
      }
    }
  }
}
"""


def search_student_disciplines(token: str, student_id: str) -> list[dict[str, Any]]:
    """Return every discipline available to the student across all periods.

    This mirrors the website's "all study periods" filter (no period id in the
    input). ``disciplineGrade`` is requested without an end date; the final
    grade is only meaningful for finished periods (see :mod:`newlxp.grades`).
    """
    variables = {"input": {"studentId": student_id}, "e": None}
    data = execute(_SEARCH_DISCIPLINES, variables, token)
    return data.get("searchStudentDisciplines") or []


def get_discipline_with_topics(token: str, discipline_id: str) -> dict:
    """Return a discipline with its chapters and topics."""
    variables = {"input": {"disciplineId": discipline_id}}
    return execute(_DISCIPLINE_WITH_TOPICS, variables, token).get(
        "getDisciplineById"
    ) or {}


def get_topic_content(token: str, topic_id: str) -> dict:
    """Return a single topic with its full content blocks."""
    variables = {"input": {"disciplineTopicId": topic_id}}
    return execute(_TOPIC_CONTENT, variables, token).get(
        "getDisciplineTopicById"
    ) or {}
