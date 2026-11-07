"""A long assignment keeps its own steps: they are the last block of the topic."""
import unittest
from unittest import mock

from newlxp import coursework

STEPS = "## Задание\n\n1. Изучите блокчейн.\n2. Создайте токен.\n3. Подготовьте отчет."


def topic(article_chars):
    return "## Что такое NFT\n\n" + "слово " * (article_chars // 6) + "\n\n" + STEPS


class ClipTaskTest(unittest.TestCase):
    def test_a_short_topic_is_unchanged(self):
        text = topic(200)
        self.assertEqual(coursework._clip_task(text, 5000), text.strip())

    def test_the_steps_survive_a_long_article(self):
        clipped = coursework._clip_task(topic(40_000), 10_000)
        self.assertTrue(clipped.endswith("3. Подготовьте отчет."), clipped[-80:])
        self.assertIn("Что такое NFT", clipped)
        self.assertLessEqual(len(clipped), 10_000)

    def test_the_cut_is_marked(self):
        self.assertIn("середина пропущена", coursework._clip_task(topic(40_000), 10_000))

    def test_without_a_separate_last_block_it_falls_back_to_the_old_clip(self):
        text = "слово " * 5000
        self.assertEqual(coursework._clip_task(text, 100), coursework._clip(text, 100))

    def test_a_last_block_larger_than_the_limit_falls_back(self):
        text = "## Вступление\n\nкоротко\n\n## Задание\n\n" + "шаг " * 3000
        self.assertEqual(coursework._clip_task(text, 1000), coursework._clip(text, 1000))


class TargetTopicTest(unittest.TestCase):
    def test_the_target_keeps_its_steps_and_background_keeps_its_start(self):
        cache = {"t": ("NFT", topic(40_000))}
        _, background = coursework._topic_text("tok", "t", cache, limit=6000)
        _, target = coursework._topic_text("tok", "t", cache, limit=30_000, keep_tail=True)
        self.assertNotIn("Подготовьте отчет", background)
        self.assertIn("Подготовьте отчет", target)

    def test_the_default_is_the_old_behaviour(self):
        cache = {"t": ("NFT", topic(40_000))}
        _, body = coursework._topic_text("tok", "t", cache, limit=6000)
        self.assertEqual(body, coursework._clip(cache["t"][1], 6000))

    def test_build_prompt_gives_the_model_the_steps(self):
        topics = [{"id": "m", "name": "Материал", "is_checkpoint": False},
                  {"id": "k", "name": "КТ 1", "is_checkpoint": True}]
        bodies = {"m": ("Материал", "теория"), "k": ("КТ 1", topic(40_000))}
        with mock.patch.object(coursework, "_fetch_topic",
                               side_effect=lambda token, tid: bodies[tid]):
            prompt, task = coursework.build_prompt("tok", topics, 1, {}, {})
        self.assertIn("3. Подготовьте отчет.", task)
        self.assertIn("3. Подготовьте отчет.", prompt)


if __name__ == "__main__":
    unittest.main()
