"""Program entry point: the main menu that ties the screens together.

Each screen lives in :mod:`newlxp.screens`; this module only decides what
runs, keeps the session alive across tasks and makes sure an unexpected
error leaves a traceback behind instead of a bare message.
"""
from __future__ import annotations

import os
import sys

from . import api, config
from .screens.auth import login, restore_or_login
from .screens.disciplines import show_disciplines
from .screens.intro import show_intro
from .screens.settings import configure_ai
from .session import Session
from .ui import Color, clear, error, info, option_line, select, wait_back

# Task registry: label -> callable taking a Session. Adding an entry here is
# all it takes for a new task to appear in the menu.
TASKS = [
    ("Disciplines and topics", show_disciplines),
    ("AI settings", configure_ai),
]

ERROR_LOG = os.path.join(os.path.expanduser("~"), ".newlxp_error.log")


def _log_exception() -> None:
    """Append the current traceback to :data:`ERROR_LOG` for debugging."""
    import datetime
    import traceback

    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as handle:
            handle.write("\n=== %s ===\n"
                         % datetime.datetime.now().isoformat(timespec="seconds"))
            traceback.print_exc(file=handle)
        print("  %sDetails written to %s%s" % (Color.DIM, ERROR_LOG, Color.RESET))
    except OSError:
        pass


def _menu_header(session: Session) -> list:
    """Build the profile header shown above the main menu."""
    user = session.user
    initials = ((user.get("lastName") or " ")[0] + (user.get("firstName") or " ")[0]).upper()

    cfg = config.load()
    ai_line = ("%s · %s" % (config.PROVIDERS[cfg["provider"]]["label"], cfg["model"])
               if cfg else "not connected")

    return [
        "",
        "  %s%s%s  %s%s%s" % (Color.CYAN + Color.BOLD, initials, Color.RESET,
                              Color.BOLD, session.full_name, Color.RESET),
        "  %sEmail:%s %s" % (Color.DIM, Color.RESET, user.get("email") or "—"),
        "  %sAI:%s    %s" % (Color.DIM, Color.RESET, ai_line),
        "  %s%s%s" % (Color.DIM, "─" * 40, Color.RESET),
        "",
    ]


def _run_menu(session: Session) -> None:
    """Main menu loop: run tasks, switch account or exit."""
    while True:
        entries = [("item", ("task", label, func)) for label, func in TASKS]
        entries.append(("item", ("account", "Switch account", None)))
        entries.append(("item", ("exit", "Exit", None)))

        try:
            choice = select(
                entries,
                header_lines=_menu_header(session),
                hint="↑↓ · Enter   (leave via the Exit item)",
                render_item=lambda value, selected: option_line(value[1], selected),
                label_item=lambda value: value[1],
                allow_back=False,  # only the "Exit" item leaves the menu
            )
        except (KeyboardInterrupt, EOFError):
            return

        if choice is None or choice[0] == "exit":
            clear()
            info("See you!")
            return

        kind, _label, func = choice
        if kind == "account":
            # Log in first; only switch if it succeeds, so cancelling is safe.
            new_session = login(allow_cancel=True)
            if new_session is not None:
                session = new_session
            continue

        clear()
        try:
            func(session)
        except (KeyboardInterrupt, EOFError):
            return  # Ctrl+C / Ctrl+D inside a task exits cleanly
        except api.AuthError as exc:
            Session.forget()
            new_session = login(notice="Session expired (%s), sign in again." % exc)
            if new_session is None:
                return
            session = new_session
        except api.ApiError as exc:
            error("Error: %s" % exc)
            wait_back("Menu")
        except Exception as exc:  # noqa: BLE001 - keep the UI alive on bugs
            error("Unexpected error: %s" % exc)
            _log_exception()
            wait_back("Menu")


def main() -> int:
    """Program entry point."""
    show_intro()
    try:
        session: Session | None = restore_or_login()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1
    if session is None:  # user cancelled login
        clear()
        info("See you!")
        return 0
    try:
        _run_menu(session)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1
    except Exception as exc:  # noqa: BLE001 - last-resort guard, no traceback
        error("Fatal error: %s" % exc)
        _log_exception()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
