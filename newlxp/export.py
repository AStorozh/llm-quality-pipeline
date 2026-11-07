"""Export a generated work to different file formats.

The AI returns plain text (lightly Markdown-flavoured). These helpers turn it
into a Markdown, Word (.docx) or PowerPoint (.pptx) file. The Word and
PowerPoint writers need optional libraries (``python-docx`` / ``python-pptx``);
when they are missing the helper returns a clear hint instead of a path.
"""
from __future__ import annotations

import os
import re
import shutil

# Code -> human label. Order defines how formats are listed in Settings.
FORMATS = [
    ("md", "Plain text (.md)"),
    ("docx", "Word (.docx)"),
    ("pptx", "Slides (.pptx)"),
]
FORMAT_LABELS = dict(FORMATS)

# "**bold**" and "`code`" are always markup. "__x__" is not: in this
# domain it is usually an identifier (__init__, __str__), so it is only
# unwrapped when it holds a phrase rather than a single token.
_EMPHASIS_RE = re.compile(r"(\*\*|`)(.+?)\1")
_UNDERSCORE_EMPHASIS_RE = re.compile(r"__((?:(?!__).)+?)__", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_BULLET_RE = re.compile(r"^[-*•]\s+")
# A Markdown table row: "| a | b |". The "|---|:--:|" line under the header
# is the separator and carries no data.
_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")
# Sentence boundary: end punctuation, whitespace, then an upper-case letter,
# a digit or an opening quote/bracket. A variable-width look-behind is not
# allowed, so abbreviations are rejoined afterwards in _sentences().
_SENTENCE_RE = re.compile(r"(?<=[.!?\u2026])\s+(?=[\u00ab\"(\[A-ZА-ЯЁ0-9])")
# "В 1992 г. Москва изменилась" is one sentence, not two.
_ABBREVIATIONS = frozenset((
    "г", "гг", "в", "вв", "рис", "табл", "стр", "см", "т", "тыс", "млн",
    "млрд", "руб", "им", "ул", "д", "коп", "др", "пр", "напр", "ок"))
_LAST_WORD_RE = re.compile(r"([^\W\d_]+)\.$", re.UNICODE)


def save_all(directory: str, name: str, heading: list, text: str, formats) -> list:
    """Write the work in each requested format as ``<directory>/<name>.<ext>``.

    ``heading`` is the signature placed above the work, centred where the
    format allows: ``[discipline, "КТ1: title", student]``.
    Returns a list of ``(format_code, path_or_None, error_or_None)``.

    A file that already exists is first copied to ``<name>_previous.<ext>``,
    so generating a checkpoint again never silently loses the last version.
    """
    writers = {"md": _save_md, "docx": _save_docx, "pptx": _save_pptx}
    results = []
    for code in formats or ["md"]:
        writer = writers.get(code)
        if not writer:
            continue
        path = os.path.join(directory, "%s.%s" % (name, code))
        try:
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(directory, "%s_previous.%s" % (name, code)))
            err = writer(path, heading, text)
        except Exception as exc:  # noqa: BLE001 - report, keep other formats
            err = str(exc)
        results.append((code, None if err else path, err))
    return results


# --------------------------------------------------------------------------- #
# Text parsing shared by the Word and PowerPoint writers
# --------------------------------------------------------------------------- #

def clean_inline(text: str) -> str:
    """Drop inline Markdown markers (``**bold**``, ```code```, ``__a b__``)."""
    text = _UNDERSCORE_EMPHASIS_RE.sub(_unwrap_underscores, text)
    return _EMPHASIS_RE.sub(r"\2", text).strip()


def _unwrap_underscores(match) -> str:
    """``__a phrase__`` is emphasis; ``__init__`` is a name. Keep names."""
    inner = match.group(1)
    return inner if " " in inner else match.group(0)


def parse_blocks(text: str) -> list:
    """Split AI text into ``[(kind, text), ...]`` blocks.

    ``kind`` is ``"heading"``, ``"bullet"``, ``"paragraph"``, ``"code"`` or
    ``"table"``. Inline Markdown is removed, except inside a fenced block,
    whose lines are kept verbatim as one ``"code"`` block — an ASCII diagram
    only survives with its spacing intact. A ``"table"`` value is a list of
    rows, each a list of cell strings, the header row first.
    """
    blocks, fenced, table = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if fenced is None and _TABLE_ROW_RE.match(line):
            if table is None:
                table = []
                blocks.append(("table", table))
            if not _TABLE_SEPARATOR_RE.match(line):
                table.append([clean_inline(cell.strip()) for cell in line[1:-1].split("|")])
            continue
        table = None
        if line.startswith("```"):
            if fenced is None:
                fenced = []
            else:
                blocks.append(("code", "\n".join(fenced).strip("\n")))
                fenced = None
            continue
        if fenced is not None:
            fenced.append(raw.rstrip())
        elif not line or set(line) <= {"-", "*", "_"}:  # blank or a --- rule
            continue
        elif _HEADING_RE.match(line):
            blocks.append(("heading", clean_inline(_HEADING_RE.sub("", line))))
        elif _BULLET_RE.match(line):
            blocks.append(("bullet", clean_inline(_BULLET_RE.sub("", line))))
        else:
            blocks.append(("paragraph", clean_inline(line.lstrip("> "))))
    if fenced:  # unterminated fence
        blocks.append(("code", "\n".join(fenced).strip("\n")))
    return [(kind, _padded(value) if kind == "table" else value)
            for kind, value in blocks if value]


def _padded(rows: list) -> list:
    """Give every table row the same number of cells."""
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def table_lines(rows: list) -> list:
    """A table as plain lines, one per data row, for formats without tables.

    Each cell is prefixed with its column header: "Канал: поиск; Бюджет: 120".
    """
    header, body = rows[0], rows[1:] or [rows[0]]
    if not rows[1:]:
        return ["; ".join(cell for cell in header if cell)]
    return ["; ".join("%s: %s" % (h, c) if h else c
                      for h, c in zip(header, row) if c) for row in body]


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

def _save_md(path, heading, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("%s\n\n%s\n" % ("  \n".join(heading), text.strip()))
    return None


# --------------------------------------------------------------------------- #
# Word
# --------------------------------------------------------------------------- #

# Word spacing. A blank line at 12 pt single spacing is about 14 pt, so a
# heading gets two of them above and one below.
BODY_SPACE = 6        # Pt, after every ordinary paragraph
SPACE_ABOVE_HEADING = 28   # Pt, ≈ two blank lines
SPACE_BELOW_HEADING = 14   # Pt, ≈ one blank line


def _save_docx(path, heading, text):
    """Write a plain Word document: no colours, no template heading styles.

    Times New Roman 12, single spacing, left-aligned. The signature lines
    are centred at the top; headings inside the work are bold paragraphs set
    off by two blank lines above and one below, so sections are easy to tell
    apart when skimming.
    """
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt
    except ImportError:
        return "python-docx is required (pip install python-docx)"

    document = Document()

    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    # python-docx sets only the Latin font; set it for every script so
    # Cyrillic text is Times New Roman too.
    rfonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), "Times New Roman")
    normal.paragraph_format.line_spacing = 1.0
    normal.paragraph_format.space_after = Pt(BODY_SPACE)

    def bold_paragraph(value: str, heading: bool = False) -> None:
        paragraph = document.add_paragraph()
        paragraph.add_run(value).bold = True
        if heading:
            # The previous paragraph already contributes BODY_SPACE below it.
            fmt = paragraph.paragraph_format
            fmt.space_before = Pt(SPACE_ABOVE_HEADING - BODY_SPACE)
            fmt.space_after = Pt(SPACE_BELOW_HEADING)

    def code_paragraph(value: str) -> None:
        """A diagram or listing: monospace, so column alignment survives."""
        paragraph = document.add_paragraph()
        run = paragraph.add_run(value)
        run.font.name = "Courier New"
        run.font.size = Pt(9)
        run.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), "Courier New")

    def add_table(rows: list) -> None:
        """A real Word table with a bold header row, not text with pipes."""
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        table.style = "Table Grid"
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                paragraph = table.cell(r, c).paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.add_run(value).bold = r == 0
        document.add_paragraph()  # keep the next paragraph off the grid

    for line in heading:
        document.add_paragraph(line).alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph()  # blank line between the signature and the work
    for kind, value in parse_blocks(text):
        if kind == "heading":
            bold_paragraph(value, heading=True)
        elif kind == "code":
            code_paragraph(value)
        elif kind == "bullet":
            document.add_paragraph(value, style="List Bullet")
        elif kind == "table":
            add_table(value)
        else:
            document.add_paragraph(value)

    document.save(path)
    return None


# --------------------------------------------------------------------------- #
# PowerPoint
# --------------------------------------------------------------------------- #

MAX_SLIDE_BULLETS = 5
MAX_SLIDE_CHARS = 600
MAX_DERIVED_TITLE = 80
MIN_DERIVED_TITLE = 15
_CLAUSE_RE = re.compile(r"[,:;]\s|\s[—–-]\s")


def _ends_with_abbreviation(text: str) -> bool:
    match = _LAST_WORD_RE.search(text)
    return bool(match) and match.group(1).lower() in _ABBREVIATIONS


def _sentences(paragraph: str) -> list:
    """Split a paragraph into sentences, keeping abbreviations intact."""
    sentences: list = []
    for piece in (p.strip() for p in _SENTENCE_RE.split(paragraph)):
        if not piece:
            continue
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = "%s %s" % (sentences[-1], piece)
        else:
            sentences.append(piece)
    return sentences


def _sections(title: str, text: str) -> list:
    """Group blocks into ``[{"title", "bullets"}]`` sections.

    A heading starts a section; list items join the current one. Without
    headings every paragraph becomes a section whose sentences are the
    bullets and whose title comes from its first sentence (see
    :func:`_derived_title`), falling back to the work's title.
    """
    sections, under_heading = [], False
    for kind, value in parse_blocks(text):
        if kind == "heading":
            sections.append({"title": value, "bullets": []})
            under_heading = True
        elif kind in ("bullet", "code", "table"):  # continue the slide being built
            if not sections:
                sections.append({"title": title, "bullets": []})
            if kind == "table":
                sections[-1]["bullets"].extend(table_lines(value))
            else:
                sections[-1]["bullets"].append(value)
        elif under_heading:
            sections[-1]["bullets"].extend(_sentences(value))
        else:  # paragraph with no heading above it
            sentences = _sentences(value)
            head = _derived_title(sentences) if len(sentences) > 1 else ""
            if head == sentences[0].rstrip("."):
                sentences.pop(0)  # the whole sentence became the title
            sections.append({"title": head or title, "bullets": sentences})
    return sections or [{"title": title, "bullets": [text.strip()]}]


def _derived_title(sentences: list) -> str:
    """A slide title taken from a paragraph's first sentence (non-empty list).

    A short sentence is used whole; a long one contributes its leading
    clause (up to a comma, colon or dash), or its first words with "…".
    """
    first = sentences[0].rstrip(".")
    if len(first) <= MAX_DERIVED_TITLE:
        return first
    clause = _CLAUSE_RE.split(first, 1)[0].strip()
    if MIN_DERIVED_TITLE <= len(clause) <= MAX_DERIVED_TITLE:
        return clause
    cut = first[:MAX_DERIVED_TITLE].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—– ") + "…"


def _fill(bullets: list, char_limit: int) -> list:
    """Greedily group bullets into pages within the bullet/char budgets."""
    pages, page, size = [], [], 0
    for bullet in bullets:
        if page and (len(page) >= MAX_SLIDE_BULLETS or size + len(bullet) > char_limit):
            pages.append(page)
            page, size = [], 0
        page.append(bullet)
        size += len(bullet)
    return pages + [page]


def _balanced_pages(bullets: list) -> list:
    """Split bullets into the fewest pages, sized as evenly as possible.

    A plain greedy split can leave a lone bullet on the last page; instead the
    character limit is lowered towards the average page size for as long as
    the page count does not grow.
    """
    pages = _fill(bullets, MAX_SLIDE_CHARS)
    count = len(pages)
    if count == 1:
        return pages
    limit = -(-sum(map(len, bullets)) // count)  # ceiling of the average
    while len(_fill(bullets, limit)) > count:
        limit += 5
    return _fill(bullets, limit)


def _paginate(sections: list) -> list:
    """Split sections so no slide exceeds the bullet or character budget."""
    slides = []
    for section in sections:
        for number, bullets in enumerate(_balanced_pages(section["bullets"])):
            # Russian: this suffix is printed on the slide itself.
            head = section["title"] if number == 0 else section["title"] + " (продолжение)"
            slides.append({"title": head, "bullets": bullets})
    return slides


def slides_from_text(title: str, text: str) -> list:
    """Return the work split into slides: ``[{"title", "bullets"}, ...]``.

    Sections with nothing under them are dropped: two headings in a row, or
    a trailing one, would otherwise become a slide showing PowerPoint's
    "click to add text" placeholder.
    """
    filled = [s for s in _sections(title, text)
              if any(b.strip() for b in s["bullets"])]
    return _paginate(filled) if filled else []


def _save_pptx(path, heading, text):
    """Write a clean 16:9 deck: a title slide, then one slide per section.

    The title slide shows the «КТ1: title» line large, with the discipline
    and the student below it.
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except ImportError:
        return "python-pptx is required (pip install python-pptx)"

    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(13.333), Inches(7.5)
    margin, width = Inches(0.7), Inches(13.333 - 1.4)

    def place(shape, top, height):
        shape.left, shape.top, shape.width, shape.height = margin, top, width, height

    def style_text(frame, size, bold=False):
        frame.word_wrap = True
        for paragraph in frame.paragraphs:
            paragraph.space_after = Pt(size // 2)
            for run in paragraph.runs:
                run.font.size, run.font.bold = Pt(size), bold

    title = heading[1] if len(heading) > 1 else heading[0]
    subtitle = "\n".join(line for line in heading if line != title)

    # Title slide.
    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    place(slide.shapes.title, Inches(2.0), Inches(2.0))
    slide.shapes.title.text = title
    style_text(slide.shapes.title.text_frame, 36, bold=True)
    subtitle_box = slide.placeholders[1]
    place(subtitle_box, Inches(4.3), Inches(1.6))
    subtitle_box.text = subtitle
    style_text(subtitle_box.text_frame, 20)

    # Content slides.
    for item in slides_from_text(title, text):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        place(slide.shapes.title, Inches(0.4), Inches(1.2))
        slide.shapes.title.text = item["title"]
        style_text(slide.shapes.title.text_frame, 28, bold=True)

        body = slide.placeholders[1]
        place(body, Inches(1.8), Inches(5.3))
        frame = body.text_frame
        frame.clear()
        for index, bullet in enumerate(item["bullets"]):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = bullet
        style_text(frame, 18)

    presentation.save(path)
    return None
