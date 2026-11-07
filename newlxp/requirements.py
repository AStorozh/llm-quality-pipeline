"""Turn an assignment's prose into a machine-readable checklist.

The task text is written for a human: numbered steps, formatting notes and a
size buried in a sentence. Asking the model for that same information as a
JSON object gives something the program can check the finished work against,
which is what :mod:`newlxp.checks` then does.

The model is not trusted: the answer is parsed, validated against
:data:`SCHEMA`, and a failure falls back to what can be read out of the text
with plain regular expressions.
"""
from __future__ import annotations

import json
import re

from . import ai, coursework, schema

SCHEMA = {
    "type": "object",
    "required": ["sections", "artifacts", "min_words", "max_words"],
    "properties": {
        "sections": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "min_words": {"type": "integer"},
        "max_words": {"type": "integer"},
        "needs_headings": {"type": "boolean"},
        "needs_appendix": {"type": "boolean"},
    },
}

EXTRACTION_PROMPT = (
    "Ты разбираешь текст учебного задания и выписываешь из него требования.\n\n"
    "Верни один объект JSON и ничего кроме него, с полями:\n"
    '  "sections"  - список обязательных разделов или пунктов задания, '
    "короткими фразами на русском;\n"
    '  "artifacts" - список обязательных приложений, образцов, шаблонов, '
    "схем и таблиц;\n"
    '  "keywords"  - термины и названия методов, которые работа обязана '
    "использовать (SWOT, матрица и т. п.);\n"
    '  "min_words", "max_words" - требуемый объём в словах; если задание его '
    "не называет, поставь 0 и 0;\n"
    '  "needs_headings" - true, если задание требует заголовков или '
    "нумерованных списков;\n"
    '  "needs_appendix" - true, если задание требует раздел с приложениями.\n\n'
    "Выписывай только то, что в задании действительно есть. Ничего не "
    "придумывай и не добавляй от себя."
)

def extract(config: dict, task_text: str) -> dict:
    """Return the checklist for ``task_text``.

    Asks the model for structured output; on any failure falls back to
    :func:`from_text`, so a checklist is always produced.
    """
    try:
        answer = ai.complete(config, EXTRACTION_PROMPT, task_text, json_mode=True)
        parsed = _parse(answer.text)
    except (ai.AIError, ValueError):
        parsed = None
    checklist = schema.coerce(parsed, SCHEMA) if parsed is not None else None
    if checklist is None:
        return from_text(task_text)
    return _with_text_floor(checklist, task_text)


def from_text(task_text: str) -> dict:
    """A checklist read straight from the text, with no model involved."""
    stated = coursework.read_volume(task_text)
    return {
        "sections": _numbered_items(task_text),
        "artifacts": _artifacts(task_text),
        "keywords": _methods(task_text),
        "min_words": stated.floor,
        "max_words": stated.ceiling,
        "needs_headings": bool(re.search(r"заголовк|нумерованн", task_text, re.I)),
        "needs_appendix": mentions_appendix(task_text),
        "needs_calculation": bool(_CALCULATION_RE.search(task_text)),
    }


# A task that cannot be done without numbers: a calculation, a budget, a
# segmentation or a summary table.
_CALCULATION_RE = re.compile(
    r"рассчита|расч[её]т|посчита|вычисл|медиа-?план|\bRFM\b|когорт|"
    r"сводн\w+\s+таблиц|бюджет", re.I)


def _parse(text: str) -> dict:
    """Parse a JSON object out of the model's reply."""
    text = text.strip()
    if text.startswith("```"):  # a fenced block slipped through
        text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def _with_text_floor(checklist: dict, task_text: str) -> dict:
    """Trust the parser over the model for the stated size.

    Also fills the two flags the model may omit, which the checks read
    with ``.get`` and would otherwise silently skip.
    """
    stated = coursework.read_volume(task_text)
    if stated.floor:
        checklist["min_words"] = stated.floor
    if stated.ceiling:
        checklist["max_words"] = stated.ceiling
    checklist.setdefault("keywords", [])
    from_regex = from_text(task_text)
    for flag in ("needs_headings", "needs_appendix", "needs_calculation"):
        checklist.setdefault(flag, from_regex[flag])
    return checklist


def _numbered_items(task_text: str) -> list:
    """Top-level numbered steps of a task ("1. Исследование компании:")."""
    items = []
    for line in task_text.splitlines():
        match = re.match(r"\s*(\d{1,2})[.)]?\s+(\S.{2,90})", line)
        # "5. баллов за оформление" is a grading scale, not a requirement.
        if match and not re.match(r"балл", match.group(2), re.I):
            items.append(match.group(2).strip().rstrip(":."))
    return items


# "Приложение" is also a mobile app: "установка приложения", "продвижение
# мобильного приложения". Those mentions are not a request for an appendix.
_APP_CONTEXT_RE = re.compile(
    r"мобильн|установ|скач|загруз|смартфон|телефон|app\s*store|google\s*play|"
    r"\bвеб|интерфейс|push|пуш|экран|код из|для\s+управлени|"
    r"использовани\w+\s+приложени", re.I)


def mentions_appendix(task_text: str) -> bool:
    """True when the task asks for an appendix, not just names an app."""
    for match in re.finditer(r"приложени\w*", task_text, re.I):
        around = task_text[max(0, match.start() - 40):match.end() + 25]
        if not _APP_CONTEXT_RE.search(around):
            return True
    return False


def _artifacts(task_text: str) -> list:
    found = ["приложения"] if mentions_appendix(task_text) else []
    for word, label in (("шаблон", "шаблоны"),
                        ("образец", "образцы"), ("образц", "образцы"),
                        ("титульн", "титульный лист"), ("схем", "схемы"),
                        ("диаграмм", "диаграммы"), ("таблиц", "таблицы")):
        if re.search(word, task_text, re.I) and label not in found:
            found.append(label)
    return found


def _methods(task_text: str) -> list:
    methods = []
    for pattern, name in ((r"\bSWOT\b", "SWOT"), (r"\bPEST\b", "PEST"),
                          (r"\bSMART\b", "SMART"), (r"матриц", "матрица"),
                          (r"\bKPI\b", "KPI"), (r"реестр рисков", "реестр рисков")):
        if re.search(pattern, task_text, re.I):
            methods.append(name)
    return methods
