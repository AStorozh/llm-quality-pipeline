"""Strip leftovers the model adds around the work itself.

Even when the prompt forbids them, models still finish with an offer to
redo the work, open with "Я, <ФИО>, …" or sign the text at the bottom —
while the file already carries a signature of its own. These are removed
here rather than in the prompt, because a filter is reliable and a prompt
is not.
"""
from __future__ import annotations

import re

# A closing offer addressed to the reader of the chat, not part of the work:
# "Если нужно, я могу оформить…", "При желании могу добавить…".
#
# The match needs all three of: a first-person "могу"/"готов" (not "могут",
# not "готовность"), and one of the verbs below, close together. Matching
# the stem alone deleted ordinary final paragraphs such as "При
# необходимости могут применяться дополнительные меры контроля."
_OFFER_VERB = (r"оформ|переоформ|подготов|дополн|добав|расшир|сократ|передел|"
               r"дораб|сдела|состав|напис|привест|присла|показа|развернут")
_OFFER_RE = re.compile(
    r"\b(?:я\s+могу|могу\s+(?:также\s+|сразу\s+|дополнительно\s+)?|"
    r"готов[аы]?\s+(?:также\s+)?)[^.]{0,40}?(?:%s)" % _OFFER_VERB,
    re.IGNORECASE,
)

# What may follow the surname in a signature: initials only ("И.И.", "И. И.").
_INITIALS_RE = re.compile(r"\s*(?:[А-ЯЁA-Z]\.\s*){1,2}\.?\s*")

# "Я, Иванов Иван Иванович, рассматриваю…" → "Я рассматриваю…".
_SELF_INTRO = "я, %s, "

# Em and en dashes are replaced by a plain hyphen on request: a typographic
# preference for these documents. A dash between spaces keeps its spaces
# ("мысль — продолжение" → "мысль - продолжение"); inside a number range it
# does not ("1500–2000" → "1500-2000").
_DASHES = "\u2014\u2013\u2012\u2212"
_DASH_RE = re.compile("[%s]+" % _DASHES)


def clean_answer(text: str, student_name: str = "") -> str:
    """Return the work without chat leftovers, signatures or long dashes."""
    text = replace_latex(replace_dashes(text))
    paragraphs = [p.strip() for p in (text or "").strip().split("\n\n")]
    paragraphs = [p for p in paragraphs if p]

    # Offers and signatures can come in either order ("…могу оформить…"
    # followed by a signature, or the other way round), so both are stripped
    # until the tail stops changing.
    while True:
        before = len(paragraphs), paragraphs[-1] if paragraphs else ""
        while paragraphs and _is_offer(paragraphs[-1]):
            paragraphs.pop()
        if paragraphs:
            paragraphs[-1] = _drop_trailing_offer_lines(paragraphs[-1])
            if not paragraphs[-1]:
                paragraphs.pop()
        if student_name:
            while paragraphs and _is_signature(paragraphs[-1], student_name):
                paragraphs.pop()
        if (len(paragraphs), paragraphs[-1] if paragraphs else "") == before:
            break
    if student_name and paragraphs:
        paragraphs[0] = _drop_self_intro(paragraphs[0], student_name)

    return "\n\n".join(paragraphs).strip()


# Models write formulas as LaTeX ("\bar r_A = 21/12 = 1{,}75\%") although a Word
# document shows the markup as it is. Only the common, unambiguous commands
# are turned into plain text; anything else is left alone.
_LATEX_GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ",
                "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "Sigma": "Σ",
                "sum": "Σ"}
_LATEX_RULES = (
    (re.compile(r"\{,\}"), ","),
    (re.compile(r"\\%"), "%"),
    (re.compile(r"\\[(\[]|\\[)\]]"), ""),
    (re.compile(r"\\(?:left|right)\b"), ""),
    (re.compile(r"\\,"), " "),
    (re.compile(r"\\(?:times|cdot)\b"), "×"),
    (re.compile(r"\\approx\b"), "≈"),
    (re.compile(r"\\text\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}"), r"\1 / \2"),
    (re.compile(r"\\sqrt\{([^{}]*)\}"), r"√(\1)"),
    (re.compile(r"\\(?:bar|overline)\s*\{?([A-Za-zА-Яа-я])\}?"), r"\1"),
    (re.compile(r"\\(%s)(?![A-Za-z])" % "|".join(_LATEX_GREEK)),
     lambda m: _LATEX_GREEK[m.group(1)]),
    (re.compile(r"_\{([^{}]*)\}"), r"_\1"),
    (re.compile(r"\^\{2\}|\^2\b"), "²"),
    (re.compile(r"\^\{([^{}]*)\}"), r"^\1"),
)
_HAS_LATEX = re.compile(r"\\[A-Za-z(\[%,)\]]|\{,\}|_\{|\^\{")


def replace_latex(text: str) -> str:
    """Plain-text form of simple LaTeX formulas; other text is untouched."""
    if not text or not _HAS_LATEX.search(text):
        return text or ""
    for pattern, replacement in _LATEX_RULES:
        text = pattern.sub(replacement, text)
    return text


def replace_dashes(text: str) -> str:
    """Turn every em/en dash into a plain hyphen, keeping the spacing."""
    return _DASH_RE.sub("-", text or "")


def _drop_trailing_offer_lines(paragraph: str) -> str:
    """Strip offers that end a paragraph on their own line.

    Some models separate paragraphs with a single newline, in which case
    the whole answer is one "paragraph" and the loop above never sees the
    offer at all.
    """
    lines = paragraph.split("\n")
    while lines and (not lines[-1].strip() or _is_offer(lines[-1])):
        lines.pop()
    return "\n".join(lines).strip()


def _is_offer(paragraph: str) -> bool:
    """True for a closing offer to redo or extend the work."""
    text = paragraph.lstrip("-*# ").strip()
    if len(text) > 300 or "\n" in text:
        return False
    return bool(_OFFER_RE.search(text))


def _is_signature(paragraph: str, student_name: str) -> bool:
    """True for a trailing line that is only the student's name.

    Matches the full name and its shortened forms ("Иванов И.И."), but never
    a sentence that merely happens to begin with the surname.
    """
    stripped = paragraph.strip("*_# \t")
    if "\n" in stripped or len(stripped) > len(student_name) + 4:
        return False
    if stripped.casefold() == student_name.casefold():
        return True
    surname = (student_name.split() or [""])[0]
    return bool(surname) and bool(_INITIALS_RE.fullmatch(stripped, len(surname))) \
        and stripped[:len(surname)].casefold() == surname.casefold()


def _drop_self_intro(paragraph: str, student_name: str) -> str:
    """Turn "Я, <ФИО>, рассматриваю…" into "Я рассматриваю…"."""
    intro = _SELF_INTRO % student_name.lower()
    if paragraph.lower().startswith(intro):
        return "Я " + paragraph[len(intro):]
    return paragraph
