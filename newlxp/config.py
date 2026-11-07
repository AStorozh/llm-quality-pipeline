"""Local configuration for the AI integration.

Stores the chosen provider, API key and model together with the user's
preferences (custom system prompt, style profile, output formats) in a
user-owned file, so none of it has to be re-entered.

Preferences are independent of the token: they can be changed and are
persisted even before an AI provider is connected.
"""
from __future__ import annotations

import json
import os

from . import storage

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".newlxp_ai.json")

# Supported providers with a short list of recommended models, cheapest
# first, and the one used when the user does not choose. The default is the
# balanced model: the cheapest ones handle the prompt's demands for depth and
# concrete examples poorly. The user can pick a stronger or cheaper model,
# any other model the provider offers, or type an id by hand.
PROVIDERS = {
    "openai": {
        "label": "OpenAI (ChatGPT)",
        "default_model": "gpt-5.4-mini",
        "models": [
            ("gpt-4o-mini", "cheapest and fastest, noticeably weaker"),
            ("gpt-5.4-mini", "default: good quality at a moderate price"),
            ("gpt-5.5", "strongest, pricier and slower"),
        ],
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "default_model": "claude-sonnet-5-5",
        "models": [
            ("claude-haiku-5-5", "cheapest and fastest, noticeably weaker"),
            ("claude-sonnet-5-5", "default: good quality at a moderate price"),
            ("claude-opus-5-5", "strongest, pricier and slower"),
        ],
    },
}


def default_model(provider: str) -> str:
    """The model used when the user has not chosen one."""
    return PROVIDERS[provider]["default_model"]

# Models the provider has retired. A saved config that still names one of
# these is transparently switched to the provider's current default.
RETIRED_MODELS = {
    "claude-3-haiku-20240307",
    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
}

DEFAULT_FORMATS = ["docx"]
# Kept here rather than imported from export: config must not depend on the
# writers, and an unknown code has to be rejected before it reaches them.
KNOWN_FORMATS = ("md", "docx", "pptx")


def _read() -> dict:
    """Return the whole stored config (empty dict if missing or corrupt)."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - missing or corrupt file
        return {}


def _write(data: dict) -> bool:
    """Persist the config dict owner-readable only; return success."""
    return storage.write_private_json(CONFIG_FILE, data)


def _update(**fields) -> bool:
    """Merge ``fields`` into the stored config and persist it."""
    data = _read()
    data.update(fields)
    return _write(data)


def load() -> dict | None:
    """Return the AI configuration, or ``None`` if no token is set up yet.

    A retired model is replaced by the provider's default (and saved), so an
    old config keeps working after a provider shuts a model down.
    """
    data = _read()
    provider = data.get("provider")
    if provider not in PROVIDERS or not data.get("api_key"):
        return None
    if not data.get("model") or data["model"] in RETIRED_MODELS:
        data["model"] = default_model(provider)
        _write(data)
    return data


def save(provider: str, api_key: str, model: str = "") -> bool:
    """Persist provider/token/model, keeping every other preference."""
    return _update(
        provider=provider,
        api_key=api_key,
        model=model or default_model(provider),
    )


def set_model(model: str) -> bool:
    """Switch the model of the connected provider."""
    return _update(model=model)


def get_system_prompt() -> str:
    """Return the user's custom system prompt, or an empty string."""
    return _read().get("system_prompt") or ""


def set_system_prompt(text: str) -> bool:
    """Store a custom system prompt (empty string resets to the default)."""
    return _update(system_prompt=text)


def get_style() -> dict | None:
    """Return the saved style profile, or ``None`` if not set yet."""
    style = _read().get("style")
    return style if isinstance(style, dict) else None


def set_style(profile: dict) -> bool:
    """Persist the user's style profile."""
    return _update(style=profile)


def get_formats() -> list:
    """Return the enabled output formats (defaults to Word).

    Unknown codes are dropped rather than returned: a hand-edited config
    naming a format the program does not have would otherwise break the
    very screen needed to correct it.
    """
    stored = _read().get("formats")
    if not isinstance(stored, list):
        return list(DEFAULT_FORMATS)
    known = [code for code in stored if code in KNOWN_FORMATS]
    return known or list(DEFAULT_FORMATS)


def set_formats(formats: list) -> bool:
    """Persist the enabled output formats (at least Markdown)."""
    return _update(formats=list(formats) or ["md"])


def get_self_review() -> bool:
    """Whether a structured work gets a second look (on unless switched off)."""
    return _read().get("self_review") is not False


def set_self_review(enabled: bool) -> bool:
    """Persist the second-look switch."""
    return _update(self_review=bool(enabled))
