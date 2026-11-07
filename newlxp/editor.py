"""Edit text in the operating system's ordinary notepad.

Terminal editors (nano, vim) are hard for most people: long lines do not
wrap, the mouse does not work and saving/quitting needs special keys. So the
text is written to a file and opened in TextEdit (macOS), Notepad (Windows)
or the desktop's default text editor (Linux); the program then reads the
file back once the user has saved it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

EDIT_FILE = os.path.join(os.path.expanduser("~"), ".newlxp_cache", "prompt.txt")

# Shortcut that saves a file in the notepad, shown in the instructions.
SAVE_SHORTCUT = "Cmd+S" if sys.platform == "darwin" else "Ctrl+S"


def write(text: str, path: str | None = None) -> None:
    """Write ``text`` for editing (UTF-8 with BOM so every notepad detects it).

    ``path`` resolves to :data:`EDIT_FILE` at call time rather than at
    import time, so redirecting the file in a test actually takes effect.
    """
    path = EDIT_FILE if path is None else path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig") as handle:
        handle.write(text)


def read(path: str | None = None) -> str:
    """Read the edited text back (a BOM, if any, is dropped)."""
    with open(EDIT_FILE if path is None else path, encoding="utf-8-sig") as handle:
        return handle.read().strip()


def open_in_notepad(path: str | None = None) -> str | None:
    """Open ``path`` in a graphical text editor without waiting for it.

    Returns the editor's display name, or ``None`` when no graphical editor
    is available (e.g. over SSH).
    """
    path = EDIT_FILE if path is None else path
    try:
        if sys.platform == "darwin":
            if subprocess.call(["open", "-e", path]) == 0:
                return "TextEdit"
        elif os.name == "nt":
            subprocess.Popen(["notepad.exe", path])
            return "Notepad"
        elif (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) \
                and shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "a text editor"
    except OSError:
        pass
    return None


def terminal_editor() -> str | None:
    """A terminal editor to fall back on: $VISUAL/$EDITOR, else nano."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        return editor
    return "nano" if shutil.which("nano") else None
