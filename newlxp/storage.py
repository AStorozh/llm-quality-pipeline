"""Writing the two files that hold credentials, safely."""
from __future__ import annotations

import json
import os


def write_private_json(path: str, data: dict) -> bool:
    """Write JSON to a file only its owner can read.

    Created through ``os.open`` with mode 0600 rather than written and then
    chmod-ed: the simple way leaves a window in which a bearer token sits on
    disk world-readable. Written to a temporary file and renamed, so an
    interrupted write cannot truncate a working session or key.
    """
    temporary = path + ".part"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            os.remove(temporary)
        except OSError:
            pass
        return False
