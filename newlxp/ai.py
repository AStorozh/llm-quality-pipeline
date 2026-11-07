"""Minimal AI client for OpenAI and Anthropic (standard library only).

Every call goes through :func:`_send`, which retries on the failures that are
worth retrying (rate limits, server errors, timeouts) with exponential
backoff, and reports what the request cost in tokens. Answers come back as
:class:`Answer`, so callers always have the usage figures at hand.
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request

from .api import SSL_CONTEXT

# Long answers take a while to generate; allow a generous timeout.
AI_TIMEOUT = 300

# Upper bound on the answer length: ~8000 tokens is roughly 5-6 pages of
# Russian text, enough for a full work while still bounding the cost.
MAX_OUTPUT_TOKENS = 8000

# OpenAI reasoning models (o-series, GPT-5 and later) spend part of the output
# budget on hidden reasoning; this extra allowance keeps room for the answer.
REASONING_TOKENS = 8000
_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-6")

# Retry policy. Rate limits and server hiccups are transient, so a few
# attempts with growing pauses turn a failed run into a slow one.
MAX_ATTEMPTS = 4
BACKOFF_BASE = 2.0       # seconds; doubles each attempt
BACKOFF_CAP = 30.0       # never wait longer than this between attempts
RETRY_STATUSES = (408, 409, 429, 500, 502, 503, 504)

# Model-list filtering: only text chat models are useful here.
_OPENAI_CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
_OPENAI_NON_CHAT = ("audio", "realtime", "tts", "transcribe", "image", "search",
                    "instruct", "codex", "-pro", "live", "embedding", "moderation")
# Dated snapshots (``gpt-4.1-2025-04-14``, ``gpt-4-0613``) duplicate an alias.
_SNAPSHOT_RE = re.compile(r"-\d{4}(-\d{2}-\d{2})?$")


class AIError(Exception):
    """Any failure while talking to the AI provider."""


class RetryableError(AIError):
    """A failure worth trying again: rate limit, server error, timeout."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class Answer:
    """What a completion returned: the text plus what it cost."""

    __slots__ = ("text", "model", "input_tokens", "output_tokens", "truncated")

    def __init__(self, text: str, model: str, input_tokens: int = 0,
                 output_tokens: int = 0, truncated: bool = False):
        self.text = text
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        # True when the provider stopped at the output token limit, so the
        # text is likely cut off mid-sentence.
        self.truncated = truncated

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __str__(self) -> str:  # so existing string use keeps working
        return self.text


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

def _sleep_for(attempt: int, retry_after: float) -> float:
    """Pause before the next attempt: the server's hint, or exponential."""
    if retry_after > 0:
        return min(retry_after, BACKOFF_CAP)
    delay = min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP)
    return delay * (0.5 + random.random() / 2)  # jitter, to spread retries


def _send(request: urllib.request.Request) -> dict:
    """Perform a request, retrying transient failures, and return the JSON."""
    last: RetryableError = RetryableError("no attempt was made")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _attempt(request)
        except RetryableError as exc:
            last = exc
            if attempt == MAX_ATTEMPTS:
                break
            time.sleep(_sleep_for(attempt, exc.retry_after))
    raise AIError("%s (gave up after %d attempts)" % (last, MAX_ATTEMPTS))


def _attempt(request: urllib.request.Request) -> dict:
    """One request. Raises :class:`RetryableError` for transient failures."""
    try:
        with urllib.request.urlopen(request, context=SSL_CONTEXT,
                                    timeout=AI_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (json.loads(exc.read()).get("error") or {}).get("message", "")
        except Exception:  # noqa: BLE001 - the body is optional and untrusted
            pass
        if exc.code in (401, 403):
            raise AIError("invalid or expired token")
        if exc.code in RETRY_STATUSES:
            label = ("rate limit exceeded (429)" if exc.code == 429
                     else "provider error (HTTP %s)" % exc.code)
            raise RetryableError(label, _retry_after(exc))
        raise AIError("HTTP %s%s" % (exc.code, ": " + detail if detail else ""))
    except urllib.error.URLError as exc:
        raise RetryableError("cannot reach the AI provider (%s)" % exc.reason)
    except TimeoutError:
        raise RetryableError("the AI provider did not answer within %s s" % AI_TIMEOUT)
    except AIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIError(str(exc))


def _retry_after(exc) -> float:
    """Seconds the server asked us to wait, or 0 when it did not say."""
    try:
        return max(0.0, float(exc.headers.get("retry-after", "")))
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    return _send(urllib.request.Request(url, data=body, headers=headers))


def _get_json(url: str, headers: dict) -> dict:
    return _send(urllib.request.Request(url, headers=headers))


def _openai_headers(api_key: str) -> dict:
    return {"content-type": "application/json", "authorization": "Bearer " + api_key}


def _anthropic_headers(api_key: str) -> dict:
    return {"content-type": "application/json", "x-api-key": api_key,
            "anthropic-version": "2023-06-01"}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

def list_models(provider: str, api_key: str) -> list:
    """Return the ids of the chat models available to this key, newest first."""
    if provider == "openai":
        data = _get_json("https://api.openai.com/v1/models", _openai_headers(api_key))
        models = sorted(data.get("data") or [], key=lambda m: m.get("created") or 0,
                        reverse=True)
        return [m["id"] for m in models
                if m.get("id", "").startswith(_OPENAI_CHAT_PREFIXES)
                and not any(marker in m["id"] for marker in _OPENAI_NON_CHAT)
                and not _SNAPSHOT_RE.search(m["id"])]
    if provider == "anthropic":
        data = _get_json("https://api.anthropic.com/v1/models?limit=1000",
                         _anthropic_headers(api_key))
        # The API already lists the newest models first.
        return [m["id"] for m in data.get("data") or []
                if m.get("id", "").startswith("claude")]
    raise AIError("unknown provider: %s" % provider)


# --------------------------------------------------------------------------- #
# Completions
# --------------------------------------------------------------------------- #

def complete(config: dict, system: str, user: str, json_mode: bool = False) -> Answer:
    """Send a system+user prompt and return the answer with its token usage.

    With ``json_mode`` the provider is asked to reply with a single JSON
    object; the caller still has to parse and validate it.
    """
    provider = config.get("provider")
    if provider == "openai":
        return _complete_openai(config, system, user, json_mode)
    if provider == "anthropic":
        return _complete_anthropic(config, system, user, json_mode)
    raise AIError("unknown provider: %s" % provider)


def _complete_openai(config: dict, system: str, user: str, json_mode: bool) -> Answer:
    model = config["model"]
    budget = MAX_OUTPUT_TOKENS
    if model.startswith(_REASONING_PREFIXES):
        budget += REASONING_TOKENS
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # ``max_completion_tokens`` (not the legacy ``max_tokens``) and no
        # ``temperature`` keep the request valid for reasoning models too.
        "max_completion_tokens": budget,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post_json("https://api.openai.com/v1/chat/completions",
                      _openai_headers(config["api_key"]), payload)
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise AIError("unexpected response from OpenAI")
    if not text.strip():
        raise AIError("OpenAI returned an empty answer")
    usage = data.get("usage") or {}
    return Answer(text.strip(), model,
                  usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                  truncated=choice.get("finish_reason") == "length")


def _complete_anthropic(config: dict, system: str, user: str, json_mode: bool) -> Answer:
    model = config["model"]
    messages = [{"role": "user", "content": user}]
    if json_mode:
        # Anthropic has no JSON mode; prefilling the reply with "{" is the
        # documented way to force a bare JSON object.
        messages.append({"role": "assistant", "content": "{"})
    payload = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": system,
        "messages": messages,
    }
    data = _post_json("https://api.anthropic.com/v1/messages",
                      _anthropic_headers(config["api_key"]), payload)
    try:
        text = "".join(block["text"] for block in data["content"]
                       if block.get("type") == "text")
    except (KeyError, AttributeError, TypeError):
        raise AIError("unexpected response from Anthropic")
    if not text.strip():
        raise AIError("Anthropic returned an empty answer")
    if json_mode:
        text = "{" + text  # put back the prefilled brace
    usage = data.get("usage") or {}
    return Answer(text.strip(), model,
                  usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                  truncated=data.get("stop_reason") == "max_tokens")
