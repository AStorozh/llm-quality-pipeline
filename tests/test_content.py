import json
import unittest

from newlxp import content


def topic_with(blocks):
    return {"name": "Тема", "content": {
        "whyStudyIt": "<p>Потому что</p>",
        "blocks": [{"name": "Раздел", "body": json.dumps(blocks)}],
    }}


class ContentTest(unittest.TestCase):
    def test_html_to_text(self):
        self.assertEqual(content.html_to_text("<b>a &amp; b</b>"), "a & b")

    def test_body_to_text(self):
        body = json.dumps([
            {"type": "header", "data": {"text": "Заголовок", "level": 2}},
            {"type": "paragraph", "data": {"text": "Текст"}},
            {"type": "list", "data": {"items": ["один", {"content": "два"}]}},
            {"type": "table", "data": {"content": [["a", "b"]]}},
        ])
        self.assertEqual(content.body_to_text(body),
                         "## Заголовок\n\nТекст\n\n- один\n- два\n\na | b")

    def test_body_that_is_not_json(self):
        self.assertEqual(content.body_to_text("<p>просто</p>"), "просто")

    def test_topic_to_text(self):
        title, body = content.topic_to_text(topic_with(
            [{"type": "paragraph", "data": {"text": "Текст"}}]))
        self.assertEqual(title, "Тема")
        self.assertIn("## Зачем изучать\n\nПотому что", body)
        self.assertIn("## Раздел\n\nТекст", body)

    def test_topic_attachments(self):
        topic = topic_with([
            {"type": "uploaderFileTool", "data": {"file": {"name": "a.pdf", "url": "https://x/a.pdf"}}},
            {"type": "attaches", "data": {"file": {"url": "https://x/b.docx"}}},
            {"type": "image", "data": {"file": {"url": "https://x/c.png"}}},
            {"type": "uploaderFileTool", "data": {"file": {}}},
        ])
        self.assertEqual(content.topic_attachments(topic), [
            ("a.pdf", "https://x/a.pdf"), ("https://x/b.docx", "https://x/b.docx")])

    def test_safe_filename(self):
        self.assertEqual(content.safe_filename("КТ 1: Эссе / черновик?"), "КТ_1_Эссе_черновик")
        self.assertEqual(content.safe_filename("///"), "topic")
