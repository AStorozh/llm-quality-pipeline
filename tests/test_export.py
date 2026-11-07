import os
import unittest
from unittest import mock

from helpers import TempDirTestCase, has_module

from newlxp import export

# One paragraph whose first sentence is short enough to become a slide
# title, one long paragraph that has to fall back to the work's title, and
# a list. Each paragraph must stay on a single line: a line break starts a
# new block.
LONG_PARAGRAPH = ("**Второй** абзац без короткого первого предложения, "
                  "поэтому заголовок берётся из названия работы.")
WORK = """Первый абзац о предмете. Он объясняет суть. И даёт пример.

%s

- пункт `один`
- пункт два
""" % LONG_PARAGRAPH


class ParsingTest(unittest.TestCase):
    def test_clean_inline(self):
        self.assertEqual(export.clean_inline("**жирный** и __фраза тут__ и `код`"),
                         "жирный и фраза тут и код")

    def test_identifiers_survive_the_emphasis_stripper(self):
        # "__init__" is a name, not bold text, and these works are about IT.
        for text in ("метод __init__ и __str__ в классе",
                     "__name__ == '__main__'",
                     "поля __slots__ и __dict__"):
            self.assertEqual(export.clean_inline(text), text, text)

    def test_parse_blocks(self):
        blocks = export.parse_blocks("## Заголовок\n\n---\n\n- пункт\n> цитата\nабзац")
        self.assertEqual(blocks, [("heading", "Заголовок"), ("bullet", "пункт"),
                                  ("paragraph", "цитата"), ("paragraph", "абзац")])

    def test_fenced_block_is_kept_verbatim(self):
        text = "До.\n\n```text\n  А  |  Б\n  --+--\n```\n\nПосле."
        self.assertEqual(export.parse_blocks(text), [
            ("paragraph", "До."), ("code", "  А  |  Б\n  --+--"),
            ("paragraph", "После.")])

    def test_markdown_table_becomes_a_table_block(self):
        text = ("До.\n\n| Канал | Бюджет |\n|---|---:|\n| **Поиск** | 120 |\n"
                "| Соцсети |\n\nПосле.")
        self.assertEqual(export.parse_blocks(text), [
            ("paragraph", "До."),
            ("table", [["Канал", "Бюджет"], ["Поиск", "120"], ["Соцсети", ""]]),
            ("paragraph", "После.")])

    def test_table_inside_a_fence_stays_code(self):
        self.assertEqual(export.parse_blocks("```\n| a | b |\n```"),
                         [("code", "| a | b |")])

    def test_table_on_slides_is_one_line_per_row(self):
        slides = export.slides_from_text("Р", "## План\n| Канал | Бюджет |\n|--|--|\n| Поиск | 120 |")
        self.assertEqual(slides[0]["bullets"], ["Канал: Поиск; Бюджет: 120"])

    def test_unterminated_fence_still_yields_a_block(self):
        self.assertEqual(export.parse_blocks("```\nсхема"), [("code", "схема")])

    def test_code_block_is_one_bullet_not_split_by_sentence(self):
        slides = export.slides_from_text("Р", "# Схема\n```\nА. Б. В.\n```")
        self.assertEqual(slides[0]["bullets"], ["А. Б. В."])

    def test_slides_from_paragraphs(self):
        slides = export.slides_from_text("Работа", WORK)
        self.assertEqual(slides[0]["title"], "Первый абзац о предмете")
        self.assertEqual(slides[0]["bullets"], ["Он объясняет суть.", "И даёт пример."])
        self.assertEqual(slides[1]["title"], "Работа")
        self.assertEqual(slides[1]["bullets"][-2:], ["пункт один", "пункт два"])

    def test_long_first_sentence_gives_its_leading_clause(self):
        text = ("Цифровая трансформация стала значимым фактором, влияющим на весь "
                "корпоративный менеджмент и на способы принятия решений. Второе.")
        slide = export.slides_from_text("Работа", text)[0]
        self.assertEqual(slide["title"], "Цифровая трансформация стала значимым фактором")
        self.assertEqual(len(slide["bullets"]), 2)  # the sentence itself is kept

    def test_long_unbroken_sentence_is_cut_at_a_word(self):
        title = export._derived_title(["слово " * 30, "Второе."])
        self.assertTrue(title.endswith("слово…"))
        self.assertLessEqual(len(title), export.MAX_DERIVED_TITLE + 1)

    def test_slides_from_headings(self):
        text = "# Введение\nТекст. Ещё текст.\n# Итог\nВсё."
        slides = export.slides_from_text("Работа", text)
        self.assertEqual([s["title"] for s in slides], ["Введение", "Итог"])
        self.assertEqual(slides[0]["bullets"], ["Текст.", "Ещё текст."])

    def test_long_sections_are_paginated(self):
        text = "# Раздел\n" + "\n".join("- пункт %d" % i for i in range(12))
        slides = export.slides_from_text("Работа", text)
        self.assertEqual([len(s["bullets"]) for s in slides], [4, 4, 4])  # balanced
        self.assertEqual(slides[1]["title"], "Раздел (продолжение)")
        for slide in export.slides_from_text("Работа", "# Р\n" + "Слово. " * 400):
            self.assertLessEqual(sum(map(len, slide["bullets"])), export.MAX_SLIDE_CHARS)


HEADING = ["Корпоративный менеджмент", "КТ1: Эссе", "Иванов Иван Иванович"]


class SaveTest(TempDirTestCase):
    def save(self, fmt):
        results = export.save_all(self.tmp, "КТ1_Корпоративный_менеджмент_И.И.И",
                                  HEADING, WORK, [fmt])
        self.assertEqual(len(results), 1)
        code, path, err = results[0]
        self.assertIsNone(err)
        self.assertEqual(os.path.basename(path), "КТ1_Корпоративный_менеджмент_И.И.И.%s" % fmt)
        return path

    def test_markdown(self):
        with open(self.save("md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(text.startswith("Корпоративный менеджмент  \nКТ1: Эссе  \n"
                                        "Иванов Иван Иванович\n\nПервый абзац"))

    @unittest.skipUnless(has_module("docx"), "python-docx not installed")
    def test_docx_is_plain_and_signed(self):
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        document = Document(self.save("docx"))
        paragraphs = document.paragraphs
        self.assertEqual([p.text for p in paragraphs[:4]], HEADING + [""])
        for paragraph in paragraphs[:3]:
            self.assertEqual(paragraph.alignment, WD_ALIGN_PARAGRAPH.CENTER)
        self.assertTrue(paragraphs[4].text.startswith("Первый абзац"))
        self.assertIsNone(paragraphs[4].alignment)  # body stays left-aligned
        self.assertNotIn("**", "\n".join(p.text for p in paragraphs))
        for paragraph in paragraphs:
            self.assertFalse(paragraph.style.name.startswith("Heading"))
            for run in paragraph.runs:
                self.assertIsNone(run.font.color.rgb)  # no colouring
        normal = document.styles["Normal"].font
        self.assertEqual((normal.name, normal.size.pt), ("Times New Roman", 12))

    @unittest.skipUnless(has_module("docx"), "python-docx not installed")
    def test_docx_sets_off_headings_with_blank_lines(self):
        from docx import Document

        results = export.save_all(self.tmp, "spaced", ["Работа"],
                                  "Абзац.\n\n## Раздел\n\nТекст раздела.", ["docx"])
        document = Document(results[0][1])
        heading = next(p for p in document.paragraphs if p.text == "Раздел")
        body = next(p for p in document.paragraphs if p.text == "Текст раздела.")
        # Two blank lines above (the previous paragraph adds BODY_SPACE),
        # one below.
        self.assertEqual(heading.paragraph_format.space_before.pt
                         + export.BODY_SPACE, export.SPACE_ABOVE_HEADING)
        self.assertEqual(heading.paragraph_format.space_after.pt,
                         export.SPACE_BELOW_HEADING)
        self.assertGreater(heading.paragraph_format.space_after.pt,
                           document.styles["Normal"].paragraph_format.space_after.pt)
        self.assertIsNone(body.paragraph_format.space_before)  # inherits Normal

    @unittest.skipUnless(has_module("docx"), "python-docx not installed")
    def test_docx_renders_diagrams_in_monospace(self):
        from docx import Document

        results = export.save_all(self.tmp, "schema", ["Работа"],
                                  "Схема:\n\n```text\n A | B\n```", ["docx"])
        document = Document(results[0][1])
        diagram = [p for p in document.paragraphs if "A | B" in p.text]
        self.assertEqual(len(diagram), 1)
        self.assertEqual(diagram[0].runs[0].font.name, "Courier New")
        self.assertNotIn("```", "\n".join(p.text for p in document.paragraphs))

    @unittest.skipUnless(has_module("docx"), "python-docx not installed")
    def test_docx_renders_markdown_tables_as_word_tables(self):
        from docx import Document

        text = "Расчёт:\n\n| Канал | Бюджет |\n|---|---:|\n| Поиск | 120 |"
        results = export.save_all(self.tmp, "table", ["Работа"], text, ["docx"])
        document = Document(results[0][1])
        self.assertEqual(len(document.tables), 1)
        table = document.tables[0]
        self.assertEqual([[c.text for c in row.cells] for row in table.rows],
                         [["Канал", "Бюджет"], ["Поиск", "120"]])
        self.assertTrue(table.cell(0, 0).paragraphs[0].runs[0].bold)
        self.assertNotIn("|", "\n".join(p.text for p in document.paragraphs))

    @unittest.skipUnless(has_module("pptx"), "python-pptx not installed")
    def test_pptx(self):
        from pptx import Presentation

        deck = Presentation(self.save("pptx"))
        self.assertAlmostEqual(deck.slide_width / deck.slide_height, 16 / 9, places=2)
        slides = list(deck.slides)
        self.assertEqual(slides[0].shapes.title.text, "КТ1: Эссе")
        self.assertEqual(slides[0].placeholders[1].text,
                         "Корпоративный менеджмент\nИванов Иван Иванович")
        self.assertEqual(len(slides), 1 + len(export.slides_from_text("КТ1: Эссе", WORK)))

    def test_missing_library_is_reported(self):
        with mock.patch.dict("sys.modules", {"docx": None}):
            (_code, path, err), = export.save_all(self.tmp, "t", ["t"], "x", ["docx"])
        self.assertIsNone(path)
        self.assertIn("python-docx", err)
