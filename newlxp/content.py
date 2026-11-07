"""Convert a topic's Editor.js content into readable Markdown.

The Russian literals in this module are not interface text: they are headings
and markers embedded in the material that is handed to the model, which reads
and writes Russian. Translating them would leave the prompt half English.

Topic bodies are stored as Editor.js block JSON. These helpers render the
common block types to plain Markdown, assemble the topic text and list
the files attached to a topic.
"""
from __future__ import annotations

import html
import json
import re

# Only strip things that actually look like a tag or a comment: a bare
# "<" in prose ("если a < b и c > d") must survive.
_TAG_RE = re.compile(r"<!--.*?-->|</?[A-Za-z][^<>]*/?>", re.DOTALL)
_UNSAFE_FILENAME_RE = re.compile(r"[^\w\s().-]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

# Editor.js block types that hold an attached file.
_FILE_BLOCKS = ("uploaderFileTool", "attaches")


def html_to_text(value: str) -> str:
    """Strip inline HTML tags and decode entities."""
    return html.unescape(_TAG_RE.sub("", value or "")).strip()


def _render_block(block: dict) -> str:
    """Render a single Editor.js block to text (never raises)."""
    if not isinstance(block, dict):
        return ""
    block_type = block.get("type")
    data = block.get("data") or {}
    try:
        if block_type == "header":
            level = data.get("level", 3)
            level = level if isinstance(level, int) else 3
            return "#" * level + " " + html_to_text(data.get("text"))
        if block_type == "paragraph":
            return html_to_text(data.get("text"))
        if block_type == "list":
            # Numbering is load-bearing: assignments state their requirements
            # as numbered steps, and those numbers are matched later.
            ordered = data.get("style") == "ordered"
            items = []
            for number, entry in enumerate(data.get("items") or [], 1):
                text = entry.get("content") if isinstance(entry, dict) else entry
                marker = "%d. " % number if ordered else "- "
                items.append(marker + html_to_text(text))
            return "\n".join(items)
        if block_type in _FILE_BLOCKS:
            file = data.get("file") or {}
            return "[Файл] %s — %s" % (file.get("name"), file.get("url"))
        if block_type == "image":
            url = (data.get("file") or {}).get("url") or data.get("url", "")
            return "[Изображение] " + url
        if block_type == "table":
            rows = data.get("content") or []
            return "\n".join(" | ".join(html_to_text(c) for c in row) for row in rows)
        # Unknown block: fall back to its raw data so nothing is silently lost.
        return html_to_text(json.dumps(data, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - one bad block must not break the export
        return ""


def _parse_body(body: str):
    """Parse an Editor.js body; return the block list or ``None``."""
    try:
        blocks = json.loads(body)
    except (TypeError, ValueError):
        return None
    return blocks if isinstance(blocks, list) else None


# Tags that end a line of text; the rest (strong, em, a, span ...) are dropped.
_LINE_TAGS = frozenset(("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
                        "tr", "table", "blockquote"))
_TAG_TOKEN_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)\b[^<>]*>")


def _html_parts(body: str):
    """The HTML strings of an ``{"isHtml": true, "content": [...]}`` body.

    Some assignments are stored as HTML wrapped in JSON rather than as
    Editor.js blocks. ``None`` for any other body.
    """
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and data.get("isHtml") and isinstance(data.get("content"), list):
        return [part for part in data["content"] if isinstance(part, str)]
    return None


def html_to_lines(fragment: str) -> str:
    """Block-level HTML to lines of text, keeping the list numbering.

    Stripping the tags alone glues neighbouring items together
    ("цели<li>Определите ЦА" becomes "целиОпределите ЦА") and loses the
    numbered steps an assignment is made of.
    """
    lines: list = []
    current: list = []
    lists: list = []  # [ordered, counter] per open <ol>/<ul>

    def flush() -> None:
        line = html.unescape("".join(current)).replace("\xa0", " ")
        line = re.sub(r"[ \t]+", " ", line).strip(" |")
        current.clear()
        if line.strip():
            lines.append(line.strip())

    for token in re.split(r"(<[^<>]+>)", fragment or ""):
        tag = _TAG_TOKEN_RE.fullmatch(token)
        if tag is None:
            if not token.startswith("<!--"):
                current.append(token)
            continue
        closing, name = tag.group(1) == "/", tag.group(2).lower()
        if name in ("ol", "ul"):
            flush()
            if closing:
                if lists:
                    lists.pop()
            else:
                lists.append([name == "ol", 0])
        elif name == "li":
            flush()
            if not closing:
                if lists:
                    lists[-1][1] += 1
                ordered = bool(lists) and lists[-1][0]
                current.append("%d. " % lists[-1][1] if ordered else "- ")
        elif name in ("td", "th"):
            if closing:
                current.append(" | ")
        elif name in _LINE_TAGS:
            flush()
    flush()
    return "\n".join(lines)


def body_to_text(body: str) -> str:
    """Render an Editor.js block array (JSON string) to Markdown."""
    blocks = _parse_body(body)
    if blocks is None:
        parts = _html_parts(body)
        if parts is not None:
            return "\n\n".join(t for t in (html_to_lines(p) for p in parts) if t)
        return html_to_text(body)
    return "\n\n".join(text for text in (_render_block(b) for b in blocks) if text)


def topic_attachments(topic: dict) -> list[tuple[str, str]]:
    """Return ``(file name, url)`` for every file attached to a topic.

    Duplicates are dropped: the same file listed twice would otherwise be
    downloaded, quoted and paid for twice in the same prompt.
    """
    files, seen = [], set()
    for section in (topic.get("content") or {}).get("blocks") or []:
        if not isinstance(section, dict):
            continue
        for block in _parse_body(section.get("body")) or []:
            if isinstance(block, dict) and block.get("type") in _FILE_BLOCKS:
                file = (block.get("data") or {}).get("file") or {}
                url = file.get("url")
                if url and url not in seen:
                    seen.add(url)
                    files.append((file.get("name") or url, url))
    return files


def safe_filename(name: str) -> str:
    """Make a filesystem-safe base name from a topic title.

    The result is used as a directory component, so a name consisting only
    of dots - which the server could return - must not become ``..``.
    """
    name = _UNSAFE_FILENAME_RE.sub("", name or "").strip().strip(".")
    name = _WHITESPACE_RE.sub("_", name)
    return (name or "topic")[:80]


def topic_to_text(topic: dict) -> tuple[str, str]:
    """Render a topic's content body to Markdown.

    Returns a ``(title, body)`` tuple. ``body`` holds the sections and
    content blocks without the title heading, ready to embed in an AI prompt.
    """
    title = topic.get("name") or "Без названия"
    parts: list[str] = []

    content = topic.get("content") or {}
    if content.get("whyStudyIt"):
        parts += ["## Зачем изучать", html_to_text(content["whyStudyIt"])]
    if content.get("howStudyIt"):
        parts += ["## Как изучать", html_to_text(content["howStudyIt"])]
    for block in content.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        heading = (block.get("name") or "").strip()
        if heading:
            parts.append("## " + heading)
        parts.append(body_to_text(block.get("body")))

    return title, "\n\n".join(p for p in parts if p).strip()
