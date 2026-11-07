import io
import os
import unittest
from unittest import mock

from helpers import TempDirTestCase, has_module

from newlxp import attachments


class ParseTest(unittest.TestCase):
    def test_extension(self):
        self.assertEqual(attachments.extension("a/B.PDF?x=1"), ".pdf")
        self.assertEqual(attachments.extension("noext"), "")

    def test_is_supported(self):
        for name in ("a.pdf", "a.docx", "a.pptx", "a.txt"):
            self.assertTrue(attachments.is_supported(name), name)
        for name in ("a.mp3", "a.zip", "a.doc", "a"):
            self.assertFalse(attachments.is_supported(name), name)

    def test_plain_text(self):
        self.assertEqual(attachments.parse(".txt", "привет\n".encode()), "привет")

    def test_unsupported(self):
        with self.assertRaises(attachments.AttachmentError):
            attachments.parse(".mp3", b"")

    def test_broken_file(self):
        if has_module("docx"):
            with self.assertRaises(attachments.AttachmentError):
                attachments.parse(".docx", b"not a zip")

    @unittest.skipUnless(has_module("docx"), "python-docx not installed")
    def test_docx(self):
        from docx import Document

        document = Document()
        document.add_paragraph("Абзац")
        document.add_table(rows=1, cols=2).rows[0].cells[0].text = "ячейка"
        buffer = io.BytesIO()
        document.save(buffer)
        self.assertEqual(attachments.parse(".docx", buffer.getvalue()), "Абзац\nячейка |")

    @unittest.skipUnless(has_module("pptx"), "python-pptx not installed")
    def test_pptx(self):
        from pptx import Presentation

        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Заголовок"
        slide.placeholders[1].text = "Пункт"
        buffer = io.BytesIO()
        deck.save(buffer)
        self.assertEqual(attachments.parse(".pptx", buffer.getvalue()),
                         "Слайд 1:\nЗаголовок\nПункт")

    @unittest.skipUnless(has_module("pypdf"), "pypdf not installed")
    def test_pdf_without_text(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = io.BytesIO()
        writer.write(buffer)
        self.assertEqual(attachments.parse(".pdf", buffer.getvalue()), "")


class ExtractTest(TempDirTestCase):
    def test_downloads_once_and_caches(self):
        with mock.patch.object(attachments, "CACHE_DIR", self.path("cache")), \
                mock.patch.object(attachments, "_download", return_value=b"text") as download:
            self.assertEqual(attachments.extract_text("a.txt", "https://x/a.txt"), "text")
            self.assertEqual(attachments.extract_text("a.txt", "https://x/a.txt"), "text")
        download.assert_called_once()
        self.assertEqual(len(os.listdir(self.path("cache"))), 1)

    def test_too_large_download(self):
        handle = mock.MagicMock()
        oversized = b"x" * (attachments.MAX_DOWNLOAD_BYTES + 1)
        handle.__enter__.return_value.read.return_value = oversized
        with mock.patch.object(attachments.urllib.request, "urlopen", return_value=handle):
            with self.assertRaises(attachments.AttachmentError):
                attachments._download("https://x/big.pdf")
