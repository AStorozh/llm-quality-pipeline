"""Authenticated session: on-disk persistence and token refresh."""
from __future__ import annotations

import base64
import json
import os
import time

from . import api, storage

# Session file lives in the user's home directory with owner-only permissions.
SESSION_FILE = os.path.join(os.path.expanduser("~"), ".newlxp_session.json")

# Refresh the access token this many seconds before it actually expires.
_EXPIRY_MARGIN = 60


def _jwt_expiry(token: str) -> int | None:
    """Return the ``exp`` (unix seconds) claim of a JWT, or ``None``."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore base64 padding
        claims = json.loads(base64.urlsafe_b64decode(payload))
        expiry = claims.get("exp")
        # A server could send anything here; only a number is usable, and a
        # string would otherwise crash the comparison in valid_token().
        return int(expiry) if isinstance(expiry, (int, float)) else None
    except Exception:  # noqa: BLE001 - malformed token
        return None


class Session:
    """Holds the access/refresh tokens and the user profile.

    The session transparently refreshes the access token when it is close to
    expiry and can persist itself to :data:`SESSION_FILE` so the user does not
    have to log in again on the next run.
    """

    def __init__(self, access: str, refresh: str | None, user: dict | None):
        self.access = access
        self.refresh = refresh
        self.user = user or {}

    # -- persistence -------------------------------------------------------- #

    def save(self) -> bool:
        """Write the session to disk, owner-readable only. Never raises."""
        return storage.write_private_json(
            SESSION_FILE,
            {"access": self.access, "refresh": self.refresh, "user": self.user})

    @classmethod
    def load(cls) -> Session | None:
        """Load a previously saved session, or ``None`` if unavailable."""
        try:
            with open(SESSION_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("access") and data.get("user"):
                return cls(data["access"], data.get("refresh"), data["user"])
        except Exception:  # noqa: BLE001 - missing or corrupt file
            pass
        return None

    @staticmethod
    def forget() -> None:
        """Delete the persisted session file, if any."""
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass

    # -- tokens ------------------------------------------------------------- #

    def valid_token(self) -> str:
        """Return a usable access token, refreshing it when near expiry.

        Raises :class:`api.AuthError` when the token has expired and cannot
        be refreshed (the user must log in again), and :class:`api.ApiError`
        when the refresh failed for a network reason.
        """
        expiry = _jwt_expiry(self.access)
        if expiry is None or expiry > time.time() + _EXPIRY_MARGIN:
            return self.access  # not a JWT (let the server judge) or still fresh
        if not self.refresh:
            raise api.AuthError("session expired")
        self.access = api.refresh_access_token(self.refresh)
        self.save()
        return self.access

    # -- display helpers ---------------------------------------------------- #

    def _name_parts(self) -> list:
        """Non-empty name parts in "Last First Middle" order."""
        parts = [self.user.get(key) for key in ("lastName", "firstName", "middleName")]
        return [p.strip() for p in parts if p and p.strip()]

    @property
    def full_name(self) -> str:
        """Full name in "Last First Middle" order."""
        return " ".join(self._name_parts()) or "(no name)"

    @property
    def initials(self) -> str:
        """Initials in "Last First Middle" order, e.g. ``И.И.И``."""
        return ".".join(p[0].upper() for p in self._name_parts())
