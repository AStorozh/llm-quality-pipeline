"""Terminal UI primitives: colors, spinner, key input and list selection.

Everything here degrades gracefully when stdout/stdin is not a TTY (for
example when piped), so the application can also be driven non-interactively.
"""
from __future__ import annotations

import getpass
import itertools
import os
import re
import shutil
import sys
import textwrap
import threading
import time
from collections.abc import Sequence
from typing import Callable

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _enable_windows_ansi() -> None:
    """Enable ANSI escape processing in the Windows console (best effort)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004 on the stdout handle (-11).
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:  # noqa: BLE001 - old console; colors may simply be absent
        pass


_enable_windows_ansi()


def _tty() -> bool:
    """True when both input and output are connected to a terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


class Color:
    """ANSI color codes, disabled automatically when output is not a TTY."""

    _enabled = sys.stdout.isatty()
    RESET = "\033[0m" if _enabled else ""
    BOLD = "\033[1m" if _enabled else ""
    DIM = "\033[2m" if _enabled else ""
    RED = "\033[31m" if _enabled else ""
    GREEN = "\033[32m" if _enabled else ""
    YELLOW = "\033[33m" if _enabled else ""
    BLUE = "\033[34m" if _enabled else ""
    MAGENTA = "\033[35m" if _enabled else ""
    CYAN = "\033[36m" if _enabled else ""
    PINK = "\033[38;5;213m" if _enabled else ""  # highlight for the selection


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a string."""
    return _ANSI_RE.sub("", text)


# Unified selection style, used by every list/menu so the accent looks the same.
NAV_HINT = "↑↓ · Enter · ← / q - back"

# Keys that leave a screen: q (also "й" on a Russian layout), Esc, Left
# arrow and Backspace.
BACK_KEYS = ("q", "й", "esc", "left", "backspace")


def accent(selected: bool) -> tuple:
    """Return the ``(marker, color)`` used for a selectable row."""
    if selected:
        return Color.PINK + Color.BOLD + "▶ ", Color.PINK + Color.BOLD
    return "  ", ""


def option_line(text: str, selected: bool) -> str:
    """Standard single-text selectable row (menus, action pickers)."""
    marker, color = accent(selected)
    return "  " + marker + color + text + Color.RESET


def clear() -> None:
    """Clear the screen and scrollback, redrawing in place (no stacking)."""
    if sys.stdout.isatty():
        # Home cursor, clear screen, clear scrollback — reliable across terminals
        # and, unlike spawning `clear`, it overwrites in place without flicker.
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()


# --------------------------------------------------------------------------- #
# Status lines
# --------------------------------------------------------------------------- #

def info(message: str) -> None:
    print(Color.CYAN + "• " + Color.RESET + message)


def success(message: str) -> None:
    print(Color.GREEN + "✓ " + Color.RESET + message)


def warn(message: str) -> None:
    print(Color.YELLOW + "! " + Color.RESET + message)


def error(message: str) -> None:
    print(Color.RED + "✗ " + Color.RESET + message)


# --------------------------------------------------------------------------- #
# Spinner
# --------------------------------------------------------------------------- #

class Spinner:
    """A context-managed loading animation: ``with Spinner("Loading"): ...``."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, text: str = "Loading"):
        self.text = text
        self._stop = False
        self._thread: threading.Thread | None = None

    def _animate(self) -> None:
        for frame in itertools.cycle(self.FRAMES):
            if self._stop:
                break
            sys.stdout.write("\r%s%s%s %s " % (Color.CYAN, frame, Color.RESET, self.text))
            sys.stdout.flush()
            time.sleep(0.08)

    def __enter__(self) -> Spinner:
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()
        else:
            print(self.text + "...")
        return self

    def __exit__(self, *exc) -> bool:
        self._stop = True
        if self._thread:
            self._thread.join()
            sys.stdout.write("\r" + " " * (len(self.text) + 6) + "\r")
            sys.stdout.flush()
        return False


# --------------------------------------------------------------------------- #
# Keyboard input
# --------------------------------------------------------------------------- #

def secret_input(prompt: str) -> str:
    """Read a password or API key without echoing it to the terminal.

    Falls back to plain ``input`` when stdin is not a terminal (piped input,
    tests), where there is nothing on screen to hide.
    """
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return input(prompt)


def read_key() -> str:
    """Read a single keypress (cross-platform).

    Returns one of ``"up"``, ``"down"``, ``"left"``, ``"enter"``, ``"esc"``,
    ``"backspace"`` or the typed character (lower-cased). Raises
    ``KeyboardInterrupt``/``EOFError`` for Ctrl+C / Ctrl+D.
    """
    if os.name == "nt":
        return _read_key_windows()
    return _read_key_unix()


def _more_input(fd, timeout: float = 0.02) -> bool:
    """True when another byte is already waiting to be read."""
    import select

    return bool(select.select([fd], [], [], timeout)[0])


def _read_key_unix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)

    # Read raw bytes from the descriptor: sys.stdin is buffered and would
    # swallow the whole arrow sequence at once, so select() below would see
    # nothing left and every arrow key would turn into "esc".
    def read_char() -> str:
        data = os.read(fd, 1)
        if not data:
            raise EOFError
        # A non-ASCII letter (e.g. Cyrillic) spans several bytes.
        extra = 3 if data[0] >= 0xF0 else 2 if data[0] >= 0xE0 else 1 if data[0] >= 0xC0 else 0
        if extra:
            data += os.read(fd, extra)
        return data.decode("utf-8", "replace")

    try:
        # TCSANOW: the default (TCSAFLUSH) discards keys typed while the
        # screen was redrawing, so quick presses got lost.
        tty.setraw(fd, termios.TCSANOW)
        char = read_char()
        if char == "\x1b":
            # Esc alone sends one byte; an arrow key sends two more at once.
            # Reading them unconditionally froze the UI on a bare Esc.
            if not _more_input(fd):
                return "esc"
            sequence = read_char() + (read_char() if _more_input(fd) else "")
            # "[A" normally, "OA" when the terminal is in application mode.
            if sequence in ("[A", "OA"):
                return "up"
            if sequence in ("[B", "OB"):
                return "down"
            if sequence in ("[D", "OD"):
                return "left"
            # Right, Home, Delete and the rest: drain the remainder of the
            # sequence (e.g. a "~") so it is not seen as a separate key.
            while _more_input(fd):
                read_char()
            return "other"
        if char in ("\r", "\n"):
            return "enter"
        if char in ("\x7f", "\x08"):
            return "backspace"
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x04":
            raise EOFError
        return char.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def _read_key_windows() -> str:
    import msvcrt

    char = msvcrt.getwch()
    if char in ("\x00", "\xe0"):  # special key prefix; next char is the code
        code = msvcrt.getwch()
        if code == "H":
            return "up"
        if code == "P":
            return "down"
        if code == "K":
            return "left"
        return "other"
    if char in ("\r", "\n"):
        return "enter"
    if char == "\x08":
        return "backspace"
    if char == "\x03":
        raise KeyboardInterrupt
    if char == "\x1a":  # Ctrl+Z (EOF on Windows)
        raise EOFError
    if char == "\x1b":
        return "esc"
    return char.lower()


def animate_until_key(render_lines: Callable[[int], Sequence[str]], fps: int = 12) -> str:
    """Loop an animation (``render_lines(frame) -> lines``) until a key.

    Redraws in place without flicker and returns the pressed key. When not a
    TTY, renders a single static frame and waits for one line of input.
    """
    if not _tty():
        for line in render_lines(0):
            print(strip_ansi(line))
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        return "enter"

    import threading

    state = {"run": True}

    def loop() -> None:
        frame = 0
        sys.stdout.write("\033[?25l")  # hide cursor
        while state["run"]:
            lines = render_lines(frame)
            buffer = "\033[H" + "".join(line + "\033[K\r\n" for line in lines) + "\033[J"
            sys.stdout.write(buffer)
            sys.stdout.flush()
            frame += 1
            time.sleep(1.0 / fps)

    clear()
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        key = read_key()
    except (KeyboardInterrupt, EOFError):
        key = "enter"
    finally:
        state["run"] = False
        thread.join(timeout=0.3)
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.flush()
        clear()
    return key


def wait_back(label: str = "Back") -> None:
    """Show a uniform "back" hint and wait for Enter / q / Esc."""
    print("\n  %s← %s · Enter, ← or q%s" % (Color.DIM, label, Color.RESET))
    if not _tty():
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        return
    while True:
        try:
            key = read_key()
        except (KeyboardInterrupt, EOFError):
            return
        if key == "enter" or key in BACK_KEYS:
            return


def wait_enter_or_back() -> bool:
    """Wait for Enter (``True``) or q/Esc (``False``)."""
    if not _tty():
        try:
            return input().strip().lower() != "q"
        except (KeyboardInterrupt, EOFError):
            return False
    while True:
        try:
            key = read_key()
        except (KeyboardInterrupt, EOFError):
            return False
        if key == "enter":
            return True
        if key in BACK_KEYS:
            return False


def wrap(text: str, width: int) -> list:
    """Wrap text to ``width`` for display, keeping paragraph breaks."""
    lines = []
    for paragraph in text.split("\n"):
        lines += textwrap.wrap(paragraph, width) or [""]
    return lines


def terminal_size() -> tuple:
    """``(columns, lines)`` of the terminal (80×24 when unknown)."""
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


# --------------------------------------------------------------------------- #
# Scrollable list selector
# --------------------------------------------------------------------------- #

# An entry is a tuple ``(kind, value)`` where kind is "header" or "item".
Entry = tuple


def select(
    entries: Sequence[Entry],
    *,
    header_lines: Sequence[str] = (),
    hint: str = "",
    render_item: Callable[[object, bool], str] | None = None,
    label_item: Callable[[object], str] | None = None,
    allow_back: bool = True,
):
    """Render a scrollable list and let the user pick a selectable item.

    ``entries`` mixes non-selectable ``("header", text)`` rows with selectable
    ``("item", value)`` rows. Navigation is by arrow keys; Enter selects. When
    ``allow_back`` is true, q/Esc returns ``None``; when false (e.g. the main
    menu) q/Esc are ignored so the user cannot leave by accident.

    ``render_item(value, selected)`` produces the full line for a TTY.
    ``label_item(value)`` produces a plain label for the non-TTY fallback.
    """
    if render_item is None:
        def render_item(value, selected):
            return ("  ▶ " if selected else "    ") + str(value)
    if label_item is None:
        label_item = str

    item_indices = [i for i, (kind, _) in enumerate(entries) if kind == "item"]
    if not item_indices:
        # There may still be rows worth reading: a discipline with no
        # checkpoints is all study topics, and hiding them behind
        # "Nothing here" would be a lie.
        clear()
        for line in header_lines:
            print(line)
        for kind, value in entries:
            if kind == "header":
                print("  %s%s%s" % (Color.CYAN + Color.BOLD, value, Color.RESET))
            else:
                print(value)
        print("\n  %sNothing here to open.%s" % (Color.DIM, Color.RESET))
        wait_back()
        return None

    if not _tty():
        return _select_non_interactive(entries, item_indices, header_lines, label_item)

    cursor = 0
    while True:
        clear()
        rows_available = max(6, terminal_size()[1] - 6)
        selected_index = item_indices[cursor]

        start = 0
        if len(entries) > rows_available:
            start = min(
                max(selected_index - rows_available // 2, 0),
                len(entries) - rows_available,
            )
        window = entries[start:start + rows_available]

        for line in header_lines:
            print(line)
        print(Color.DIM + "  ▲" + Color.RESET if start > 0 else "")
        for index, (kind, value) in enumerate(window, start):
            if kind == "header":
                print("  %s%s%s" % (Color.CYAN + Color.BOLD, value, Color.RESET))
            elif kind == "text":  # shown but not selectable
                print(value)
            else:
                print(render_item(value, index == selected_index))
        if start + rows_available < len(entries):
            print(Color.DIM + "  ▼" + Color.RESET)
        if hint:
            print("\n  %s%s%s" % (Color.DIM, hint, Color.RESET))

        key = read_key()
        if key == "up":
            cursor = (cursor - 1) % len(item_indices)
        elif key == "down":
            cursor = (cursor + 1) % len(item_indices)
        elif key == "enter":
            return entries[item_indices[cursor]][1]
        elif key in BACK_KEYS and allow_back:
            return None


def _select_non_interactive(entries, item_indices, header_lines, label_item):
    """Numbered fallback selector used when stdin is not a TTY."""
    clear()
    for line in header_lines:
        print(line)
    number = 0
    for kind, value in entries:
        if kind == "header":
            print("  " + strip_ansi(str(value)))
        elif kind == "text":
            print("  " + strip_ansi(str(value)))
        else:
            number += 1
            print("   %d. %s" % (number, label_item(value)))
    try:
        raw = input("Choice (empty - back): ").strip()
        if not raw:
            return None
        choice = int(raw)
    except (ValueError, KeyboardInterrupt, EOFError):
        return None
    # Python would read 0 as "the last item" and -1 as the one before it.
    if not 1 <= choice <= len(item_indices):
        return None
    return entries[item_indices[choice - 1]][1]
