"""Score and grade computation for the student disciplines table.

The logic here intentionally mirrors the website's own rendering so the
numbers shown by this tool match the UI exactly, rather than being
re-derived with heuristics. See :func:`parse_discipline` for the field
selection rules reverse-engineered from the frontend.
"""
from __future__ import annotations

from typing import Any

# Server grade enums map to the Russian five-point scale.
GRADE_ENUM = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def to_number(value: Any) -> float | None:
    """Coerce a value to ``float`` or return ``None``."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def format_number(value: Any) -> str:
    """Format a number without a trailing ``.0`` (e.g. ``50`` not ``50.0``)."""
    number = to_number(value)
    if number is None or number != number or number in (float("inf"), float("-inf")):
        return "0"  # missing, NaN or infinite: nothing sensible to show
    return str(int(number)) if number == int(number) else "%.1f" % number


def to_grade(value: Any) -> int | None:
    """Normalise a grade field: enum or number -> int, otherwise ``None``."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return GRADE_ENUM.get(value)


def parse_discipline(item: dict) -> dict:
    """Turn one ``searchStudentDisciplines`` entry into a display row.

    Score (numerator), matching the website:
        * with a retake: ``scoreForAttempt`` -> ``retakeScore``
          -> ``scoreForAnsweredRetakeTasks``;
        * otherwise: ``scoreForAnsweredTasks``.
      The denominator is the discipline's ``maxScore``.

    Grade (exact field selection, matching the website):
        * ``mainAttemptScore`` present -> ``retakeDisciplineGradeV2``;
        * else a retake score present -> ``retakeDisciplineGrade``;
        * else -> ``disciplineGrade``.
      A grade is only final for a finished study period; for an ongoing
      period the site shows no grade, which we represent as ``None`` (0).

    Returns a dict with ``id``, ``name``, ``score``, ``max``, ``grade``,
    ``period`` and ``period_end``.
    """
    discipline = item.get("discipline") or {}
    max_score = to_number(discipline.get("maxScore"))
    if max_score is None:
        max_score = 100  # the field is missing, not zero

    has_retake = bool(item.get("hasRetake") or item.get("hasRetakeV1"))
    finished = any(
        period.get("status") == "FINISHED"
        for period in (item.get("studyPeriod") or [])
        if isinstance(period, dict)
    )

    main = to_number((item.get("mainStudentAttempt") or {}).get("scoreForAttempt"))
    retake = to_number(item.get("retakeScore"))
    retake_tasks = to_number(item.get("scoreForAnsweredRetakeTasks"))
    tasks = to_number(item.get("scoreForAnsweredTasks"))

    if has_retake:
        if main is not None:
            score = main
        elif retake is not None:
            score = retake
        else:
            score = retake_tasks if retake_tasks is not None else 0
    else:
        score = tasks if tasks is not None else 0

    # ``is not None``, not truthiness: a retake scored 0 is still a retake,
    # and must not fall through to the pre-retake grade.
    if not finished:
        grade = None
    elif main is not None:
        grade = to_grade(item.get("retakeDisciplineGradeV2"))
    elif retake is not None or retake_tasks is not None:
        grade = to_grade(item.get("retakeDisciplineGrade"))
    else:
        grade = to_grade(item.get("disciplineGrade"))

    periods = [p for p in (item.get("studyPeriod") or []) if isinstance(p, dict)]
    return {
        "id": discipline.get("id"),
        "name": discipline.get("name") or "—",
        "score": score,
        "max": max_score,
        "grade": grade,
        "period": periods[0].get("name") if periods else "—",
        "period_end": (periods[0].get("endDate") if periods else "") or "",
        "group_id": (item.get("learningGroup") or {}).get("id"),
    }
