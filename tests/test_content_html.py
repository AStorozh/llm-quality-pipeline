"""Assignments stored as HTML inside JSON must keep their steps readable."""
import json
import unittest

from newlxp import content, requirements

TASK_HTML = (
    "<p>Задание: разработайте стратегию. Ваши действия:</p>"
    "<ol><li>Исследуйте целевую аудиторию:</li></ol>"
    "<ul><li>Кто является аудиторией?</li><li>Какие у неё проблемы?</li></ul>"
    "<ol><li>Определите цели:</li></ol>"
    "<ul><li>Чего вы хотите достичь?</li></ul>"
    "<ol><li>Создайте контент-план:</li></ol>"
    "<p>&nbsp;</p><p>Обратите внимание на <strong>цели</strong>.</p>"
)


def html_body(*parts):
    return json.dumps({"isHtml": True, "content": list(parts)}, ensure_ascii=False)


class HtmlBodyTest(unittest.TestCase):
    def test_steps_and_questions_stay_on_their_own_lines(self):
        text = content.body_to_text(html_body(TASK_HTML))
        lines = text.splitlines()
        self.assertIn("1. Исследуйте целевую аудиторию:", lines)
        self.assertIn("- Кто является аудиторией?", lines)
        self.assertIn("1. Создайте контент-план:", lines)
        self.assertIn("Обратите внимание на цели.", lines)

    def test_neighbouring_items_are_not_glued(self):
        text = content.body_to_text(html_body("<ul><li>Поставьте цели</li>"
                                              "<li>Определите ЦА</li></ul>"))
        self.assertNotIn("целиОпределите", text)
        self.assertEqual(text.splitlines(), ["- Поставьте цели", "- Определите ЦА"])

    def test_json_wrapping_does_not_leak_into_the_text(self):
        text = content.body_to_text(html_body(TASK_HTML))
        self.assertNotIn("isHtml", text)
        self.assertNotIn("{", text)

    def test_the_steps_are_found_by_the_requirements_parser(self):
        text = content.body_to_text(html_body(TASK_HTML))
        sections = requirements.from_text(text)["sections"]
        self.assertEqual(sections, ["Исследуйте целевую аудиторию",
                                    "Определите цели", "Создайте контент-план"])

    def test_nonbreaking_spaces_and_entities_are_cleaned(self):
        text = content.body_to_text(html_body("<p>Цена&nbsp;100&nbsp;&amp;&nbsp;выше</p>"))
        self.assertEqual(text, "Цена 100 & выше")

    def test_a_table_keeps_its_rows(self):
        text = content.body_to_text(html_body(
            "<table><tr><td>Канал</td><td>Бюджет</td></tr>"
            "<tr><td>Директ</td><td>100</td></tr></table>"))
        self.assertEqual(text.splitlines(), ["Канал | Бюджет", "Директ | 100"])

    def test_several_html_parts_are_separated_by_a_blank_line(self):
        text = content.body_to_text(html_body("<p>Первая часть.</p>", "<p>Вторая часть.</p>"))
        self.assertEqual(text, "Первая часть.\n\nВторая часть.")


class OtherBodiesUnchangedTest(unittest.TestCase):
    def test_editorjs_blocks_render_as_before(self):
        body = json.dumps([
            {"type": "paragraph", "data": {"text": "Абзац <b>текста</b>."}},
            {"type": "list", "data": {"style": "ordered",
                                      "items": [{"content": "Раз"}, {"content": "Два"}]}},
        ], ensure_ascii=False)
        self.assertEqual(content.body_to_text(body), "Абзац текста.\n\n1. Раз\n2. Два")

    def test_plain_text_still_has_its_tags_stripped(self):
        self.assertEqual(content.body_to_text("Просто <b>текст</b>"), "Просто текст")

    def test_a_json_object_that_is_not_html_falls_back(self):
        body = json.dumps({"isHtml": False, "content": ["x"]})
        self.assertIn("isHtml", content.body_to_text(body))

    def test_html_content_that_is_not_a_list_falls_back(self):
        body = json.dumps({"isHtml": True, "content": "<p>строка</p>"},
                          ensure_ascii=False)
        self.assertEqual(content.body_to_text(body).count("строка"), 1)


if __name__ == "__main__":
    unittest.main()
