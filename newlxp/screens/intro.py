"""Animated welcome screen shown once at start-up.

The logo is assembled from per-letter glyphs so the spacing stays even, and
a moving gradient runs through it while the instructions are on screen.
"""
from __future__ import annotations

from ..ui import Color, animate_until_key

# Per-letter 4-row glyphs; the logo is assembled with an even one-space gap
# between every letter so the spacing is uniform (no glued/scattered letters).
_GLYPHS = {
    "n": [" _ __", "| '_ \\", "| | | |", "|_| |_|"],
    "e": ["  ___", " / _ \\", "|  __/", " \\___|"],
    "w": ["__      __", "\\ \\ /\\ / /", " \\ V  V /", "  \\_/\\_/"],
    "l": [" _", "| |", "| |", "|_|"],
    "x": ["__  __", "\\ \\/ /", " >  <", "/_/\\_\\"],
    "p": [" ____", "|  _ \\", "|  __/", "|_|"],
}


def _build_logo(word: str = "newlxp") -> list:
    """Render ``word`` from the glyphs with uniform one-space letter spacing."""
    glyphs = []
    for char in word:
        rows = _GLYPHS[char]
        width = max(len(r) for r in rows)
        glyphs.append([r.ljust(width) for r in rows])
    return ["  " + " ".join(g[row] for g in glyphs) for row in range(4)]


_LOGO = _build_logo()

_INSTRUCTIONS = [
    "  %sHow to use it%s" % (Color.BOLD, Color.RESET),
    "  %sNavigation: ↑↓ to move, Enter to open, q to go back.%s"
    % (Color.DIM, Color.RESET),
    "",
    "  %s1.%s Sign in with your newlxp.ru email and password." % (Color.PINK, Color.RESET),
    "  %s2.%s Optionally connect an AI: paste your own ChatGPT"
    % (Color.PINK, Color.RESET),
    "     or Claude key, right after login or in AI settings.",
    "  %s3.%s Disciplines and topics → discipline → checkpoint"
    % (Color.PINK, Color.RESET),
    "     (study topics are listed read-only).",
    "  %s4.%s The AI writes the work for a checkpoint from every" % (Color.PINK, Color.RESET),
    "     topic before it. Pick one checkpoint or all of them.",
    "",
    "  %sSystem prompt%s is the instruction the AI writes by."
    % (Color.CYAN, Color.RESET),
    "  In AI settings you can change it for good; on a checkpoint",
    "  screen you can change it for that one work only.",
    "",
    "  %sWriting style%s gives each user a random handwriting (structure,"
    % (Color.CYAN, Color.RESET),
    "  tone, focus) so works differ. It does not affect quality.",
    "  You can roll a new one in AI settings.",
    "",
    "  %sFinished works go to ai_output/ next to the program.%s"
    % (Color.DIM, Color.RESET),
    "  %sThe format (.docx / .pptx / .md) is set in AI settings.%s"
    % (Color.DIM, Color.RESET),
]


# Smooth looping gradient (256-color): magenta → purple → blue → cyan → back.
_GRADIENT = [213, 207, 171, 135, 99, 63, 69, 75, 81, 117, 159, 195,
             159, 117, 81, 75, 69, 63, 99, 135, 171, 207]


def _shimmer(text: str, frame: int) -> str:
    """Colour each non-space character by a moving gradient (cyclic)."""
    if not Color._enabled:
        return text
    out = []
    for x, char in enumerate(text):
        if char == " ":
            out.append(" ")
        else:
            color = _GRADIENT[(x + frame) % len(_GRADIENT)]
            out.append("\033[1m\033[38;5;%dm%s" % (color, char))
    return "".join(out) + Color.RESET


def show_intro() -> None:
    """Animated welcome + instructions; loops until the user presses Enter."""

    def frame(i: int) -> list:
        lines = [""]
        lines += [_shimmer(row, i) for row in _LOGO]  # gradient flows through letters
        lines.append("  " + _shimmer("═" * 43, i))
        lines.append("")
        lines += _INSTRUCTIONS
        lines.append("")
        lines.append("  %sPress Enter to continue…%s" % (Color.DIM, Color.RESET))
        return lines

    animate_until_key(frame, fps=14)
