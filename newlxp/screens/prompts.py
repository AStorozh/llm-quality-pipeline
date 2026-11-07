"""Viewing and editing the system prompt the model writes by."""
from __future__ import annotations

import sys

from .. import config, coursework, editor
from ..ui import (
    NAV_HINT,
    Color,
    clear,
    option_line,
    select,
    terminal_size,
    wait_enter_or_back,
    warn,
    wrap,
)

# --------------------------------------------------------------------------- #
# System prompt editing
# --------------------------------------------------------------------------- #

def _notepad_edit(text: str) -> str | None:
    """Let the user edit ``text`` in the system notepad; return the result.

    Returns the edited text (``""`` if everything was deleted) or ``None``
    when the user cancelled.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        try:
            return input("  New prompt on one line: ").strip() or None
        except (KeyboardInterrupt, EOFError):
            return None

    editor.write(text)
    app_name = editor.open_in_notepad()
    if app_name is None:
        return _terminal_edit(text)

    original = text.strip()
    reminder = ""
    while True:
        clear()
        print("  %sEditing the prompt%s\n" % (Color.BOLD, Color.RESET))
        print("  The prompt is open in a separate window: %s%s%s.\n"
              % (Color.CYAN + Color.BOLD, app_name, Color.RESET))
        steps = ["Edit the text in that window.",
                 "Save the file: %s%s%s." % (Color.BOLD, editor.SAVE_SHORTCUT, Color.RESET),
                 "Come back here and press %sEnter%s." % (Color.BOLD, Color.RESET)]
        for number, step in enumerate(steps, 1):
            print("  %s%d.%s %s" % (Color.PINK, number, Color.RESET, step))
        print("\n  %sYou can close the editor afterwards. Deleting all the text%s"
              % (Color.DIM, Color.RESET))
        print("  %srestores the built-in prompt.%s" % (Color.DIM, Color.RESET))
        if reminder:
            print()
            warn(reminder)
        print("\n  %sEnter to apply · q to cancel%s" % (Color.DIM, Color.RESET))

        if not wait_enter_or_back():
            return None
        try:
            edited = editor.read()
        except OSError as exc:
            reminder = "Could not read the file: %s" % exc
            continue
        if edited != original:
            return edited
        reminder = ("No changes seen. Save the file (%s) and press Enter again, "
                    "or q to cancel." % editor.SAVE_SHORTCUT)


def _terminal_edit(text: str) -> str | None:
    """Fallback without a graphical notepad: a terminal editor, with hints."""
    import subprocess

    command = editor.terminal_editor()
    if command is None:
        print("  %sNo editor found: type the prompt on one line.%s"
              % (Color.DIM, Color.RESET))
        try:
            return input("  > ").strip() or None
        except (KeyboardInterrupt, EOFError):
            return None
    clear()
    print("  The %s%s%s editor will open." % (Color.BOLD, command, Color.RESET))
    if command == "nano":
        print("  Save: %sCtrl+O%s then Enter. Quit: %sCtrl+X%s."
              % (Color.BOLD, Color.RESET, Color.BOLD, Color.RESET))
    print("\n  %sEnter to open · q to cancel%s" % (Color.DIM, Color.RESET))
    if not wait_enter_or_back():
        return None
    try:
        subprocess.call(command.split() + [editor.EDIT_FILE])
        edited = editor.read()
    except OSError:
        return None
    return edited if edited != text.strip() else None


def show_prompt_screen(title: str, note: str, get_base, apply) -> None:
    """Show the whole prompt and let the user edit or reset it.

    ``get_base()`` returns the current custom prompt (``""`` = default);
    ``apply(text)`` stores a new one (``""`` resets) and returns a status
    message (``None`` on failure).
    """
    labels = {"edit": "Edit the text in a notepad",
              "reset": "Restore the built-in prompt"}
    status = ""
    while True:
        base = get_base()
        text = base or coursework.SYSTEM_PROMPT
        columns, lines = terminal_size()
        width = max(40, min(columns - 4, 100))

        header = ["  %s%s%s" % (Color.BOLD, title, Color.RESET)]
        header += ["  %s%s%s" % (Color.DIM, line, Color.RESET) for line in wrap(note, width)]
        header.append("  %s%s%s" % (Color.DIM, "─" * width, Color.RESET))
        body = wrap(text, width)
        # Keep the menu on screen: show as much of the text as fits.
        room = max(5, lines - 14)
        if len(body) > room:
            hidden = len(body) - room + 1
            body = body[:room - 1] + [
                "%s… %d more lines, all of them visible under Edit%s"
                % (Color.DIM, hidden, Color.RESET)]
        header += ["  " + line for line in body]
        header.append("  %s%s%s" % (Color.DIM, "─" * width, Color.RESET))
        if status:
            header.append("  " + status)
        header.append("")

        items = [("item", "edit")]
        if base:
            items.append(("item", "reset"))
        action = select(
            items,
            header_lines=header,
            hint=NAV_HINT,
            render_item=lambda value, selected: option_line(labels[value], selected),
            label_item=lambda value: labels[value],
        )
        if action is None:
            return
        new_text = "" if action == "reset" else _notepad_edit(text)
        if new_text is None:
            status = "%sChanges cancelled.%s" % (Color.DIM, Color.RESET)
            continue
        message = apply(new_text)
        status = (Color.GREEN + "✓ " + Color.RESET + message if message
                  else Color.RED + "✗ " + Color.RESET
                  + "Could not write %s." % config.CONFIG_FILE)


def name_note(student_name: str) -> str:
    """Line explaining what is appended to the prompt automatically."""
    if student_name:
        return ("Added automatically: the work is signed as %s, plus the "
                "writing style." % student_name)
    return "The student name and the writing style are added automatically."


def edit_saved_prompt(student_name: str) -> None:
    """Settings: view and edit the saved prompt used for every work."""
    def apply(text: str) -> str | None:
        if not config.set_system_prompt(text):
            return None
        return "Prompt reset to the built-in one." if text == "" else "Prompt saved."

    show_prompt_screen("AI system prompt · main", name_note(student_name),
                   config.get_system_prompt, apply)
