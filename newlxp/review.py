"""A second look at a finished work, with a way back.

The mechanical checks in :mod:`newlxp.checks` recompute sums and look for the
words of a section's name. They cannot see that a step of the task was done
on the wrong group, that a sentence contradicts its own table, or that a goal
set at the start is missed by the calculation further down. Nor can they
tell that an answer contradicts the work's own stated rule further down, or
that a term, account number or classification is wrong for the subject.
Those were the defects that kept reaching a teacher.

The model is asked for a short list of exact-text replacements, never for a
rewrite. Each replacement is applied only when

* the quoted passage occurs in the work exactly once,
* it does not shrink the passage, drop a table row, or cut the work,
* the mechanical checks find nothing new afterwards.

A replacement that fails any of these is dropped on its own, and a model that
answers badly or not at all leaves the work exactly as it was.
"""
from __future__ import annotations

import json
import re

from . import ai, arithmetic, checks, coursework, export, polish, schema

# Tasks with fewer numbered steps than this and no calculation are essays:
# the first pass already does them well and a second request is not worth it.
MIN_STEPS = 3
MAX_EDITS = 12
# A quote shorter than this is not a safe anchor.
MIN_ANCHOR_CHARS = 12
# The work after every edit must keep this share of its words.
MIN_KEPT_SHARE = 0.95
# One edit of a passage this long or longer may not cut it below this share.
LONG_PASSAGE_WORDS = 10
MIN_EDIT_SHARE = 0.5

EDITS_SCHEMA = {
    "type": "object",
    "required": ["edits"],
    "properties": {
        "issues": {"type": "array", "items": {"type": "string"}},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["old", "new"],
                "properties": {"old": {"type": "string"},
                               "new": {"type": "string"}},
            },
        },
    },
}

SYSTEM = (
    "Ты проверяющий преподаватель и редактор в одном лице. Тебе дают "
    "учебное задание и студенческую работу. Найди места, где работа не "
    "выполняет задание или противоречит сама себе, и предложи точечные "
    "исправления.\n\n"
    "Что искать:\n"
    "1. Шаг задания выполнен не так, как написан, или пропущен: взята не "
    "та группа или выборка, не та метрика, нет требуемой таблицы, расчёта "
    "или сравнения. Сверяй работу с каждым пунктом задания по очереди.\n"
    "2. Текст расходится с таблицами: число, название или вывод не "
    "подтверждены таблицей; группы разного размера сравниваются по суммам, "
    "а не по средним или долям.\n"
    "3. Цель, лимит или плановое значение названы в начале, а расчёт или "
    "итог им не соответствуют.\n"
    "4. Логическая несостыковка: действие опирается на то, чего по плану "
    "ещё нет; заявленная частота или срок не совпадают с планом.\n"
    "5. Грамматическая или смысловая ошибка в предложении.\n"
    "6. Ответ на конкретный вопрос противоречит выводу или объяснению в "
    "этой же работе: например, итоговое предложение описывает правило "
    "иначе, чем конкретный ответ выше, который должен следовать тому же "
    "правилу.\n"
    "7. Предметная ошибка, в которой ты твёрдо уверен: термин, определение, "
    "номер счёта, формула или классификация не соответствуют "
    "общепринятым правилам дисциплины, даже если текст сам себе не "
    "противоречит. Правь это только когда уверен; при малейшем сомнении "
    "оставь как есть - для спорного места лучше просто отметить его в "
    "\"issues\", чем предлагать правку.\n\n"
    "Как исправлять:\n"
    "- \"old\" - дословная цитата из работы, символ в символ, которая "
    "встречается в тексте ровно один раз (предложение или абзац, не короче "
    "двенадцати символов).\n"
    "- \"new\" - замена в стиле автора: от первого лица, простыми словами, "
    "без длинных тире и штампов. Все числа в замене должны быть посчитаны "
    "верно и совпадать с таблицами работы.\n"
    "- Чтобы добавить недостающее, возьми в \"old\" соседнее предложение и "
    "верни его в \"new\" вместе с добавленным текстом. Таблицу пиши в "
    "Markdown.\n"
    "- Не добавляй, не удаляй и не меняй заголовки (строки с «#») и "
    "нумерацию. Новый текст вставляй внутри существующего раздела, рядом с "
    "тем, к чему он относится.\n"
    "- В таблице не повторяй шапку и уже имеющиеся строки: в \"old\" бери "
    "одну строку данных, а в \"new\" верни её же и новые строки после неё.\n"
    "- Не переписывай работу целиком, не сокращай и не удаляй разделы и "
    "таблицы. Всё, что верно, оставь как есть. Не больше %d правок.\n"
    "- Если проблем нет, верни пустые списки. Не придумывай проблем.\n\n"
    'Верни один объект JSON: {"issues": ["короткое описание проблемы"], '
    '"edits": [{"old": "цитата", "new": "замена"}]}. Ничего кроме JSON.'
    % MAX_EDITS
)


class Outcome:
    """What the second look did: the text, what changed and what it cost."""

    __slots__ = ("text", "issues", "applied", "rejected", "replies")

    def __init__(self, text: str):
        self.text = text
        self.issues: list = []     # what the model said was wrong
        self.applied = 0           # replacements that went in
        self.rejected: list = []   # (reason, start of the quote)
        self.replies: list = []    # ai.Answer objects, for the usage log

    @property
    def changed(self) -> bool:
        return self.applied > 0


def needs_review(checklist: dict) -> bool:
    """True for a structured task: several numbered steps or a calculation."""
    return (len(checklist.get("sections") or []) >= MIN_STEPS
            or bool(checklist.get("needs_calculation")))


def review(config: dict, work: str, task_text: str, checklist: dict,
           materials: str = "") -> Outcome:
    """Ask the model for fixes and apply the safe ones.

    Raises :class:`ai.AIError` when the request itself fails; every other
    problem with the answer just means no changes.
    """
    baseline = checks.run(work, checklist, materials)
    outcome = Outcome(work)
    answer = ai.complete(config, SYSTEM, _request(task_text, work, checklist,
                                                  baseline), json_mode=True)
    outcome.replies.append(answer)
    try:
        payload = schema.validate(_parse(answer.text), EDITS_SCHEMA)
    except (ValueError, schema.SchemaError):
        outcome.rejected.append(("the answer was not the expected JSON", ""))
        return outcome

    outcome.issues = [i.strip() for i in payload.get("issues") or [] if i.strip()]
    base_bad = _bad_names(baseline)
    base_words = len(work.split())
    text = work
    for edit in payload["edits"][:MAX_EDITS]:
        candidate, reason = _apply(text, edit, base_words, checklist,
                                   materials, base_bad)
        if reason:
            outcome.rejected.append((reason, edit["old"].strip()[:40]))
        elif candidate != text:
            text = candidate
            outcome.applied += 1
    outcome.text = text
    return outcome


def _request(task_text: str, work: str, checklist: dict, results: list) -> str:
    parts = ["# ЗАДАНИЕ\n\n" + task_text.strip()[:coursework.MAX_TASK_CHARS]]
    steps = checklist.get("sections") or []
    if steps:
        parts.append("# ПУНКТЫ ЗАДАНИЯ\n\n" + "\n".join(
            "%d. %s" % (i, s) for i, s in enumerate(steps, 1)))
    found = [r for r in results if r.status != checks.PASS]
    if found:
        parts.append("# АВТОМАТИЧЕСКАЯ ПРОВЕРКА НАШЛА\n\n" + "\n".join(
            "- %s: %s" % (r.name, r.detail) for r in found))
    parts.append("# РАБОТА\n\n" + work)
    return "\n\n".join(parts)


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):  # a fenced block slipped through
        text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def _bad_names(results: list) -> set:
    return {r.name for r in results if r.status != checks.PASS}


def _headings(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.lstrip().startswith("#")]


def _table_rows(text: str) -> int:
    return sum(len(rows) for kind, rows in export.parse_blocks(text)
               if kind == "table")


def _apply(text: str, edit: dict, base_words: int, checklist: dict,
           materials: str, base_bad: set):
    """Return ``(new_text, "")`` or ``(text, why_it_was_refused)``."""
    old, new = edit["old"].strip(), edit["new"].strip()
    if len(old) < MIN_ANCHOR_CHARS:
        return text, "the quote is too short to anchor"
    if old == new:
        return text, ""
    if "\n\n" in old:
        return text, "the quote spans several paragraphs"
    if _headings(new) != _headings(old):
        return text, "the replacement changes a heading"
    found = text.count(old)
    if found != 1:
        return text, ("the quote is not in the work" if not found
                      else "the quote occurs %d times" % found)
    new = polish.replace_dashes(new)
    old_words, new_words = len(old.split()), len(new.split())
    if old_words >= LONG_PASSAGE_WORDS and new_words < old_words * MIN_EDIT_SHARE:
        return text, "the replacement cuts the passage"
    candidate = text.replace(old, new, 1)
    if len(candidate.split()) < base_words * MIN_KEPT_SHARE:
        return text, "the work would lose too much text"
    if _table_rows(candidate) < _table_rows(text):
        return text, "the replacement removes a table row"
    if len(arithmetic.find_errors(candidate)) > len(arithmetic.find_errors(text)):
        return text, "the replacement adds an arithmetic error"
    if len(checks.numbering_findings(candidate)) > len(checks.numbering_findings(text)):
        return text, "the replacement repeats a number or a table row"
    introduced = _bad_names(checks.run(candidate, checklist, materials)) - base_bad
    if introduced:
        return text, "the replacement trips: %s" % ", ".join(sorted(introduced))
    return candidate, ""
