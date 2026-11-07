"""Automatic quality checks for a finished work.

Each check answers one question with a pass, a fail or a warning, and says
why. Together they replace reading every work by hand to find out whether a
prompt change helped: run them before and after, compare the scores.

The checks are deliberately mechanical. They cannot judge whether an argument
is any good; they catch the failures that kept recurring in practice - a
missing section, an invented statistic, leftover chat text, a work half the
length the task demands.
"""
from __future__ import annotations

import re

from . import arithmetic, export, polish

PASS, WARN, FAIL = "pass", "warn", "fail"

# Phrases that address the reader of a chat rather than the examiner.
_CHATTY = (r"если нужно,? я мог", r"если хотите,? мог", r"готов оформить",
           r"могу также", r"надеюсь, это помож", r"вот ваша работа")
# A figure that looks like hard data. Harmless on its own, suspect when the
# course materials contain no numbers at all.
_STATISTIC = re.compile(r"\d[\d\s]*[.,]?\d*\s?(?:%|процент\w*|млн|млрд|тыс\.?\s?руб|рублей)",
                        re.I)
# "в материалах", "из материалов", "по материалам", "согласно материалам",
# "из учебной темы". Not "каналы и материалы": a bare "и" is a conjunction.
_SOURCE_TELL = re.compile(
    r"\b(?:в|из|о|об|по|на\s+основе)\s+материал\w+|согласно\s+материал\w+|"
    r"\b(?:из|в|по)\s+учебн\w+\s+(?:тем\w+|материал\w+)", re.I)
_LONG_DASH = re.compile(r"[—–]")
# "Главная цель, это рост": a dash replaced by a comma, not by a hyphen.
_COMMA_ETO = re.compile(r"(?:^|[.!?:]\s+)[А-ЯЁ][\w-]*(?:\s+[\w-]+){0,3},\s+это\s", re.M)
# Phrases that give a generated text away: each found in real works here.
CLICHES = (
    r"это и есть", r"в итоге мо[яйеи]", r"кажется мне (?:сбалансирован|логичн|разумн)\w*",
    r"удобн\w+ (?:пример|инструмент|цикл|способ)", r"позволяет не только",
    r"игра\w+ (?:ключев|важн|значим)\w+ роль", r"явля\w+ неотъемлем\w+",
    r"в современн\w+ (?:мире|условиях|реалиях)",
    r"(?:важно|стоит|следует|необходимо) (?:отметить|подчеркнуть)", r"подводя итог",
    r"можно сделать вывод", r"становится не ", r"превращается из ",
    r"главн\w+ ценност\w+", r"прост\w+ логик\w+", r"строится вокруг",
    r"(?:мощн|универсальн)\w+ инструмент", r"открывает (?:новые )?возможност",
)
_CLICHE_RE = re.compile(r"\b(?:%s)" % "|".join(CLICHES), re.I)
# "не просто X, а Y" and "не X, а Y": fine once, a tell in bulk.
_NOT_X_BUT_Y = re.compile(r"\bне (?:просто )?[а-яё]+(?: [а-яё]+){0,4}, а\b", re.I)
MAX_NOT_X_BUT_Y_PER_1000_WORDS = 3

# Fewer figures than this in a calculation task means nothing was calculated.
MIN_CALCULATION_FIGURES = 10
# Words too common to tell whether a section was covered.
_STOPWORDS = {"который", "которые", "которая", "должен", "должна", "должны",
              "также", "может", "можно", "нужно", "этого", "этому", "будет",
              "своих", "своей", "более", "менее", "каждый", "каждая"}


class Result:
    """The outcome of one check.

    A ``blocking`` check is a precondition for the rest: when it fails the
    others are meaningless, so the whole score collapses to zero.
    """

    __slots__ = ("name", "status", "detail", "blocking")

    def __init__(self, name: str, status: str, detail: str = "",
                 blocking: bool = False):
        self.name = name
        self.status = status
        self.detail = detail
        self.blocking = blocking

    @property
    def ok(self) -> bool:
        return self.status != FAIL

    def __repr__(self) -> str:
        return "<%s %s: %s>" % (self.name, self.status, self.detail)


# Below this a work is not short, it is missing.
MIN_REAL_WORK_WORDS = 50


def run(work: str, checklist: dict, materials: str = "") -> list:
    """Run every check and return the results in a stable order."""
    return [
        check_not_empty(work),
        check_length(work, checklist),
        check_sections(work, checklist),
        check_artifacts(work, checklist),
        check_keywords(work, checklist),
        check_no_chat_leftovers(work),
        check_no_invented_figures(work, materials),
        check_no_source_tells(work),
        check_no_long_dashes(work),
        check_no_comma_dashes(work),
        check_no_cliches(work),
        check_structure(work, checklist),
        check_calculations(work, checklist),
        check_arithmetic(work),
        check_numbering(work),
        check_no_latex(work),
    ]


def score(results) -> float:
    """Share of checks that did not fail, from 0.0 to 1.0.

    Zero when a blocking check failed: an empty answer passes everything
    else by having nothing to object to, and must not look like 90%.
    """
    results = list(results)
    if not results:
        return 1.0
    if any(r.blocking and r.status == FAIL for r in results):
        return 0.0
    return sum(1 for r in results if r.ok) / len(results)


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #

def check_not_empty(work: str) -> Result:
    """The floor under every other check.

    Without it an empty answer scored a perfect 100%: with no stated size
    and nothing to look for, every other check has nothing to object to.
    """
    words = len((work or "").split())
    if words == 0:
        return Result("not empty", FAIL, "the work is empty", blocking=True)
    if words < MIN_REAL_WORK_WORDS:
        return Result("not empty", FAIL, "%d words is not a work" % words,
                      blocking=True)
    return Result("not empty", PASS, "", blocking=True)


def check_length(work: str, checklist: dict) -> Result:
    words = len(work.split())
    low, high = checklist.get("min_words") or 0, checklist.get("max_words") or 0
    if low and words < low:
        return Result("length", FAIL, "%d words, the task asks for %d" % (words, low))
    if high and words > high * 1.1:
        return Result("length", FAIL, "%d words, the task caps it at %d" % (words, high))
    if high and words > high:
        return Result("length", WARN, "%d words, slightly over the %d cap" % (words, high))
    return Result("length", PASS, "%d words" % words)


def check_sections(work: str, checklist: dict) -> Result:
    required = [s for s in checklist.get("sections") or [] if len(s) > 4]
    if not required:
        return Result("sections", PASS, "the task lists none")
    work_stems = _stems(work)
    missing = [s for s in required if not _mentions(work_stems, s)]
    if not missing:
        return Result("sections", PASS, "all %d covered" % len(required))
    status = FAIL if len(missing) > len(required) / 4 else WARN
    return Result("sections", status,
                  "%d of %d missing: %s" % (len(missing), len(required),
                                            "; ".join(_topic_of(m) for m in missing[:3])))


def _stems(text: str) -> set:
    """Content words cut to a stem, so Russian endings do not matter."""
    words = re.findall(r"[^\W\d_]{5,}", text.lower(), re.UNICODE)
    return {w[:6] for w in words if w not in _STOPWORDS}


# How much of a section's name has to appear before it counts as covered.
_SECTION_OVERLAP = 0.6
# Words of the name to look at; the tail of a long item is explanation.
_SECTION_WORDS = 5


def _topic_of(section: str) -> str:
    """The name of a task item, without the explanation that follows it.

    Items read like "Исследование компании: кратко охарактеризуйте ...".
    The part before the colon is the topic; the rest is instructions, which
    a work has no reason to repeat.
    """
    head = section.split(":", 1)[0]
    if len(head.split()) < 2:  # no useful colon, use the whole item
        head = section
    return " ".join(head.split()[:_SECTION_WORDS])


def _mentions(work_stems: set, section: str) -> bool:
    """True when the work covers a section named by the task."""
    wanted = _stems(_topic_of(section))
    if not wanted:
        return True  # nothing distinctive to look for
    present = wanted & work_stems
    return len(present) >= max(1, round(len(wanted) * _SECTION_OVERLAP))


def check_artifacts(work: str, checklist: dict) -> Result:
    if not checklist.get("needs_appendix"):
        return Result("artifacts", PASS, "no appendix required")
    if re.search(r"^#+\s*приложени|\bприложение\s*\d", work, re.I | re.M):
        return Result("artifacts", PASS, "appendix present")
    return Result("artifacts", FAIL, "the task asks for an appendix, none found")


def check_keywords(work: str, checklist: dict) -> Result:
    keywords = checklist.get("keywords") or []
    if not keywords:
        return Result("keywords", PASS, "the task names no method")
    missing = [k for k in keywords if k.lower() not in work.lower()]
    if not missing:
        return Result("keywords", PASS, "all present: %s" % ", ".join(keywords))
    return Result("keywords", FAIL, "not used: %s" % ", ".join(missing))


def check_no_chat_leftovers(work: str) -> Result:
    hits = [p for p in _CHATTY if re.search(p, work, re.I)]
    if hits:
        return Result("no chat leftovers", FAIL, "%d phrase(s) addressed to a reader"
                      % len(hits))
    return Result("no chat leftovers", PASS, "")


def _digits(figure: str) -> str:
    """The number in a figure, so "47%" and "47 процентов" compare equal."""
    return re.sub(r"\D", "", figure)


def check_no_invented_figures(work: str, materials: str) -> Result:
    """Figures are fine when the materials have them, suspect otherwise."""
    in_work = set(_STATISTIC.findall(work))
    if not in_work:
        return Result("no invented figures", PASS, "no hard figures used")
    if materials and _STATISTIC.search(materials):
        # Compare the numbers themselves, not just whether the materials
        # have any. A figure may be derived by a calculation, so a miss is a
        # warning to check by hand, not a failure.
        known = {_digits(f) for f in _STATISTIC.findall(materials)}
        unknown = {_digits(f) for f in in_work} - known
        if not unknown:
            return Result("no invented figures", PASS, "all figures found in the materials")
        return Result("no invented figures", WARN,
                      "%d figure(s) not found in the materials, check them by hand"
                      % len(unknown))
    if not materials:
        return Result("no invented figures", WARN,
                      "%d figure(s), materials not supplied to check against"
                      % len(in_work))
    return Result("no invented figures", FAIL,
                  "%d figure(s) absent from the materials" % len(in_work))


def check_no_source_tells(work: str) -> Result:
    hits = _SOURCE_TELL.findall(work)
    if hits:
        return Result("no source tells", FAIL,
                      '%d reference(s) to "материалы" left in the text' % len(hits))
    return Result("no source tells", PASS, "")


def check_no_long_dashes(work: str) -> Result:
    hits = _LONG_DASH.findall(work)
    if hits:
        return Result("no long dashes", FAIL, "%d em/en dash(es)" % len(hits))
    return Result("no long dashes", PASS, "")


def check_no_comma_dashes(work: str) -> Result:
    hits = _COMMA_ETO.findall(work)
    if hits:
        return Result("no comma dashes", WARN,
                      '%d "X, это Y" where a dash belongs: %s'
                      % (len(hits), hits[0].strip(" .!?:")))
    return Result("no comma dashes", PASS, "")


def check_no_cliches(work: str) -> Result:
    """Stock phrases and the "не X, а Y" habit of generated text."""
    found = [m.group(0).strip() for m in _CLICHE_RE.finditer(work)]
    examples = list(dict.fromkeys(f.lower() for f in found))
    contrasts = len(_NOT_X_BUT_Y.findall(work))
    words = max(len(work.split()), 1)
    problems = []
    if found:
        problems.append('%d stock phrase(s): "%s"' % (len(found), '", "'.join(examples[:4])))
    if contrasts >= 3 and contrasts * 1000 / words > MAX_NOT_X_BUT_Y_PER_1000_WORDS:
        problems.append('%d "не X, а Y" (%.1f per 1000 words, at most %d reads natural)'
                        % (contrasts, contrasts * 1000 / words,
                           MAX_NOT_X_BUT_Y_PER_1000_WORDS))
    if problems:
        return Result("no cliches", WARN, "; ".join(problems))
    return Result("no cliches", PASS, "")


def check_calculations(work: str, checklist: dict) -> Result:
    """A calculation task answered with prose alone has not been done."""
    if not checklist.get("needs_calculation"):
        return Result("calculations", PASS, "the task asks for no calculation")
    tables = sum(1 for kind, _ in export.parse_blocks(work) if kind == "table")
    figures = len(re.findall(r"\d+(?:[.,]\d+)?", work))
    if tables:
        return Result("calculations", PASS, "%d table(s), %d figure(s)" % (tables, figures))
    if figures >= MIN_CALCULATION_FIGURES:
        return Result("calculations", WARN,
                      "a calculation task with no table, %d figure(s) in the text" % figures)
    return Result("calculations", FAIL,
                  "the task asks for a calculation, the work has no table and "
                  "%d figure(s)" % figures)


def check_arithmetic(work: str) -> Result:
    """Recompute sums, ratios and day counts; see :mod:`newlxp.arithmetic`."""
    findings = arithmetic.find_errors(work)
    if findings:
        return Result("arithmetic", FAIL, "; ".join(findings[:5])
                      + (" (+%d more)" % (len(findings) - 5) if len(findings) > 5 else ""))
    return Result("arithmetic", PASS, "")


# A number opening a heading: "5. Риски", "2.1 Рынок". Two digits at most per
# part, so a heading that opens with a year ("2024 год") is not a number.
_HEADING_NUMBER_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s")


def numbering_findings(work: str) -> list:
    """Repeated or backward heading numbers and repeated table rows.

    Both are slips a reader sees at once and a model makes when it adds a
    section or a table row to a finished text: two sections numbered "5.",
    a header row printed twice.
    """
    findings, seen, last_top = [], set(), 0
    for kind, value in export.parse_blocks(work):
        if kind == "heading":
            match = _HEADING_NUMBER_RE.match(value)
            if not match:
                continue
            number = tuple(int(part) for part in match.group(1).split("."))
            label = ".".join(str(part) for part in number)
            if number in seen:
                findings.append("heading number %s repeats" % label)
            seen.add(number)
            if len(number) == 1:
                if number[0] < last_top:
                    findings.append("heading number %s comes after %d" % (label, last_top))
                last_top = max(last_top, number[0])
        elif kind == "table":
            for previous, row in zip(value, value[1:]):
                if row == previous:
                    findings.append('table row "%s" is printed twice'
                                    % " | ".join(row)[:40])
    return findings


# Markup a Word document shows as it is: "\bar", "\frac", "1{,}75", "\%".
_LATEX_LEFTOVER = re.compile(
    r"\\(?:bar|frac|times|cdot|approx|text|sqrt|overline|left|right|sigma|mu|alpha|beta|"
    r"rho|Delta|sum)\b|\{,\}|\\%|\\\(|\\\[")


def check_no_latex(work: str) -> Result:
    """Formulas written as LaTeX are shown as code in a Word document."""
    hits = _LATEX_LEFTOVER.findall(work)
    if hits:
        return Result("no latex", WARN, "%d LaTeX fragment(s), e.g. %s"
                      % (len(hits), hits[0]))
    return Result("no latex", PASS, "")


def check_numbering(work: str) -> Result:
    """Heading numbers that repeat or run backwards, table rows printed twice."""
    findings = numbering_findings(work)
    if findings:
        return Result("numbering", WARN, "; ".join(findings[:3])
                      + (" (+%d more)" % (len(findings) - 3) if len(findings) > 3 else ""))
    return Result("numbering", PASS, "")


def check_structure(work: str, checklist: dict) -> Result:
    """Prose, not a skeleton of headings - unless the task wants headings."""
    blocks = export.parse_blocks(work)
    headings = sum(1 for kind, _ in blocks if kind == "heading")
    bullets = sum(1 for kind, _ in blocks if kind == "bullet")
    body = max(len(blocks), 1)
    if checklist.get("needs_headings") and headings == 0:
        return Result("structure", FAIL, "the task asks for headings, none used")
    if headings and len(work.split()) / headings < 60:
        return Result("structure", WARN,
                      "%d headings for %d words, very fragmented"
                      % (headings, len(work.split())))
    if bullets / body > 0.6:
        return Result("structure", WARN, "%d%% of the text is bullet points"
                      % round(100 * bullets / body))
    return Result("structure", PASS, "%d headings, %d%% bullets"
                  % (headings, round(100 * bullets / body)))


def clean(work: str, student_name: str = "") -> str:
    """The same tidy-up the client applies before saving, for eval fixtures."""
    return polish.clean_answer(work, student_name)
