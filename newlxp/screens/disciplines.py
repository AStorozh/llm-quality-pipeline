"""Browsing screens: the discipline list and a discipline's topics."""
from __future__ import annotations

from .. import api, coursework, grades
from ..session import Session
from ..ui import NAV_HINT, Color, Spinner, accent, option_line, select
from .generate import prepare_and_write

# Grade -> colour for the disciplines table.
_GRADE_COLOR = {5: Color.GREEN, 4: Color.CYAN, 3: Color.YELLOW, 2: Color.RED, 1: Color.RED}


# --------------------------------------------------------------------------- #
# Row renderers
# --------------------------------------------------------------------------- #

def _discipline_line(row: dict, selected: bool, name_width: int = 44) -> str:
    """Format a discipline row: name, score and grade."""
    name = row["name"]
    name = name if len(name) <= name_width else name[:name_width - 1] + "…"
    score = "%s/%s" % (grades.format_number(row["score"]), grades.format_number(row["max"]))
    grade = row["grade"]
    grade_color = _GRADE_COLOR.get(grade, Color.DIM)
    grade_text = str(grade) if grade else "0"

    marker, color = accent(selected)
    body = "%s%-*s%s %s%8s%s   %s%s%s" % (
        color, name_width, name, Color.RESET,
        Color.DIM, score, Color.RESET,
        grade_color + Color.BOLD, grade_text, Color.RESET,
    )
    return "  " + marker + body


def _topic_line(entry: dict, selected: bool, name_width: int = 54) -> str:
    """Format a topics-list row.

    ``entry`` is either the special ``{"kind": "all"}`` action or a
    ``{"kind": "topic", "topic": <flattened topic>}`` row.
    """
    marker, highlight = accent(selected)

    if entry.get("kind") == "all":
        return option_line("★ Write every checkpoint (AI)", selected)

    topic = entry["topic"]
    name = (topic.get("name") or "").strip()
    name = name if len(name) <= name_width else name[:name_width - 1] + "…"
    if topic.get("is_checkpoint"):
        tag = Color.YELLOW + Color.BOLD + "Checkpoint" + Color.RESET
        max_score = topic.get("max_score")
        if max_score:
            tag += "  %s%s pt%s" % (Color.DIM, grades.format_number(max_score), Color.RESET)
    else:
        tag = Color.DIM + "Study topic" + Color.RESET

    body = "%s%-*s%s %s" % (highlight, name_width, name, Color.RESET, tag)
    return "  " + marker + body


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #

def _discipline_entries(session: Session) -> tuple[list, int]:
    """Fetch disciplines and build grouped selector entries.

    Returns ``(entries, count)`` where entries mix period headers with
    selectable discipline rows, matching the website's order.
    """
    with Spinner("Loading disciplines"):
        raw = api.search_student_disciplines(session.valid_token(), session.user.get("id"))

    # Parse rows, de-duplicating by discipline + learning group (as the site does).
    rows, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = grades.parse_discipline(item)
        key = (row["id"], row["group_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    # Group by period; order groups by period end date (newest first).
    groups: dict[str, list[dict]] = {}
    end_dates: dict[str, str] = {}
    for row in rows:
        groups.setdefault(row["period"], []).append(row)
        end_dates.setdefault(row["period"], row["period_end"])

    entries: list = []
    for period in sorted(groups, key=lambda p: end_dates.get(p, ""), reverse=True):
        members = groups[period]
        entries.append(("header", "%s (%d)" % (period, len(members))))
        entries.extend(("item", row) for row in members)
    return entries, len(rows)


def show_disciplines(session: Session) -> None:
    """List all disciplines, grouped by study period, and open the chosen one."""
    entries, count = _discipline_entries(session)
    header = ["  %sStudies · %d disciplines%s\n" % (Color.BOLD, count, Color.RESET)]
    while True:
        chosen = select(
            entries,
            header_lines=header,
            hint=NAV_HINT,
            render_item=_discipline_line,
            label_item=lambda row: row["name"],
        )
        if chosen is None:
            return
        show_topics(session, chosen)


def show_topics(session: Session, discipline: dict) -> None:
    """List a discipline's topics; open a topic or generate a checkpoint work."""
    with Spinner("Loading topics"):
        data = api.get_discipline_with_topics(session.valid_token(), discipline["id"])

    discipline_name = data.get("name") or discipline["name"]
    topics = coursework.flatten_topics(data)  # ordered; each gets an index below
    for index, topic in enumerate(topics):
        topic["index"] = index
    points = coursework.checkpoints(topics)

    # Build the list: an optional "all checkpoints" action, then topics grouped
    # by chapter (the flattened order is already chapter-contiguous). Study
    # topics are shown but not selectable; only checkpoints can be chosen.
    entries: list = []
    if points:
        entries.append(("item", {"kind": "all"}))
    current_chapter = object()
    for topic in topics:
        if topic.get("chapter") != current_chapter:
            current_chapter = topic.get("chapter")
            if current_chapter:
                entries.append(("header", current_chapter))
        row = {"kind": "topic", "topic": topic}
        if topic.get("is_checkpoint"):
            entries.append(("item", row))
        else:
            entries.append(("text", _topic_line(row, False)))  # non-selectable

    header = ["  %s%s%s" % (Color.BOLD, discipline_name, Color.RESET),
              "  %s· %d topics%s\n" % (Color.DIM, len(topics), Color.RESET)]
    while True:
        chosen = select(
            entries,
            header_lines=header,
            hint=NAV_HINT,
            render_item=_topic_line,
            label_item=lambda e: ("Every checkpoint" if e.get("kind") == "all"
                                  else (e["topic"].get("name") or "").strip()),
        )
        if chosen is None:
            return
        if chosen.get("kind") == "all":
            prepare_and_write(session, discipline_name, topics, points, points)
        else:  # only checkpoints are selectable
            topic = chosen["topic"]
            prepare_and_write(session, discipline_name, topics, points,
                        [(topic["index"], topic)])
