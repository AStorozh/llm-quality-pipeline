"""Download topic attachments and extract their text for the AI context.

Failure messages are in Russian on purpose: the only place they appear is
inside the Russian prompt, next to the attachment they describe.

Supported formats: PDF (needs ``pypdf``), Word .docx (``python-docx``),
PowerPoint .pptx (``python-pptx``) and plain text. Extracted text is cached
on disk by URL, so a file is downloaded only once.
"""
from __future__ import annotations

import hashlib
import io
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .api import SSL_CONTEXT

DOWNLOAD_TIMEOUT = 60  # seconds without a single byte
# The timeout above does not stop a slow but steady download, which once held
# a run for ten minutes per file. This one bounds the whole transfer.
DOWNLOAD_DEADLINE = 240  # seconds for the whole file
_CHUNK_BYTES = 64 * 1024
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".newlxp_cache", "attachments")

TEXT_EXTENSIONS = {".txt", ".md", ".csv"}


class AttachmentError(Exception):
    """The attachment could not be downloaded or read."""


def extension(name: str) -> str:
    """Lower-case extension of a file name or URL (``""`` if none)."""
    return os.path.splitext(name.split("?", 1)[0])[1].lower()


def file_extension(name: str, url: str = "") -> str:
    """The extension to treat a file as, preferring a usable one.

    The URL is the actual file, so it wins: a block named "лекция.txt"
    pointing at a PDF must be parsed as a PDF, not decoded as text. A name
    is often not a file name at all ("Задание v1.2"), hence the fallback.
    The gate and the parser must agree here, or a file is downloaded and
    then thrown away on every run.
    """
    for candidate in (extension(url), extension(name)):
        if candidate in TEXT_EXTENSIONS or candidate in _EXTRACTORS:
            return candidate
    return extension(name) or extension(url)


def is_supported(name: str, url: str = "") -> bool:
    """True if text can be extracted from this file."""
    ext = file_extension(name, url)
    return ext in TEXT_EXTENSIONS or ext in _EXTRACTORS


def extract_text(name: str, url: str) -> str:
    """Return the text of the attachment at ``url`` (cached).

    Raises :class:`AttachmentError` when the file cannot be fetched or parsed.
    """
    cache_path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".txt")
    try:
        with open(cache_path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        pass  # missing or damaged: fetch it again

    text = parse(file_extension(name, url), _download(url))
    _store(cache_path, text)
    return text


def parse(ext: str, data: bytes) -> str:
    """Extract text from file bytes of the given extension."""
    if ext in TEXT_EXTENSIONS:
        return data.decode("utf-8", errors="replace").strip()
    extractor = _EXTRACTORS.get(ext)
    if extractor is None:
        raise AttachmentError("формат %s не поддерживается" % (ext or "без расширения"))
    try:
        return extractor(io.BytesIO(data)).strip()
    except ImportError as exc:
        raise AttachmentError("нужна библиотека %s" % (exc.name or exc))
    except Exception as exc:  # noqa: BLE001 - broken or unusual file
        raise AttachmentError("не удалось прочитать файл (%s)" % exc)


def _store(path: str, text: str) -> None:
    """Write a cache entry atomically.

    A half-written file would be returned as that attachment's text on
    every later run, with nothing to reveal that it is truncated.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + ".part"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except OSError:
        pass  # caching is an optimisation only


# Attachment URLs come from the platform's content blocks, which are not
# ours. Anything but http(s) - file://, data:, ftp:// - must never be
# fetched: whatever it returned would be pasted into a prompt and sent to
# the AI provider.
ALLOWED_SCHEMES = ("http", "https")


def _download(url: str) -> bytes:
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise AttachmentError("адрес не поддерживается (%s)" % (scheme or "без схемы"))
    try:
        with urllib.request.urlopen(url, context=SSL_CONTEXT, timeout=DOWNLOAD_TIMEOUT) as resp:
            started, parts, total = time.monotonic(), [], 0
            while True:
                chunk = resp.read(_CHUNK_BYTES)
                if not chunk:
                    break
                parts.append(chunk)
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES or len(chunk) < _CHUNK_BYTES:
                    break  # too big, or a short read: the end of the body
                if time.monotonic() - started > DOWNLOAD_DEADLINE:
                    raise AttachmentError("скачивание длится дольше %d с" % DOWNLOAD_DEADLINE)
            data = b"".join(parts)
    except urllib.error.HTTPError as exc:
        raise AttachmentError("HTTP %s" % exc.code)
    except Exception as exc:  # noqa: BLE001 - network failure or timeout
        raise AttachmentError("не удалось скачать (%s)" % exc)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise AttachmentError("файл больше %d МБ" % (MAX_DOWNLOAD_BYTES // 1024 // 1024))
    return data


def _pdf_text(stream) -> str:
    from pypdf import PdfReader

    return "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(stream).pages)


def _docx_text(stream) -> str:
    from docx import Document

    document = Document(stream)
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def _pptx_text(stream) -> str:
    from pptx import Presentation

    slides = []
    for number, slide in enumerate(Presentation(stream).slides, 1):
        lines = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                lines += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        if lines:
            slides.append("Слайд %d:\n%s" % (number, "\n".join(lines)))
    return "\n\n".join(slides)


_EXTRACTORS = {".pdf": _pdf_text, ".docx": _docx_text, ".pptx": _pptx_text}
