import json
import os
import stat
from unittest import mock

from helpers import TempDirTestCase

from newlxp import config


class ConfigTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(config, "CONFIG_FILE", self.path("ai.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def stored(self) -> dict:
        with open(config.CONFIG_FILE, encoding="utf-8") as handle:
            return json.load(handle)

    def test_no_config_means_no_ai(self):
        self.assertIsNone(config.load())
        self.assertEqual(config.get_formats(), ["docx"])
        self.assertEqual(config.get_system_prompt(), "")
        self.assertIsNone(config.get_style())

    def test_preferences_persist_without_token(self):
        self.assertTrue(config.set_formats(["md", "pptx"]))
        self.assertTrue(config.set_style({"structure": 1, "tone": 2, "accent": 3}))
        self.assertTrue(config.set_system_prompt("мой промт"))
        self.assertIsNone(config.load())  # still no token
        self.assertEqual(config.get_formats(), ["md", "pptx"])
        self.assertEqual(config.get_style(), {"structure": 1, "tone": 2, "accent": 3})
        self.assertEqual(config.get_system_prompt(), "мой промт")

    def test_save_token_keeps_preferences(self):
        config.set_formats(["pptx"])
        config.set_system_prompt("промт")
        config.save("openai", "sk-test")
        loaded = config.load()
        self.assertEqual(loaded["model"], config.default_model("openai"))
        self.assertEqual(config.get_formats(), ["pptx"])
        self.assertEqual(config.get_system_prompt(), "промт")

    def test_default_model_is_one_of_the_recommended(self):
        for provider, info in config.PROVIDERS.items():
            models = [m for m, _ in info["models"]]
            self.assertIn(config.default_model(provider), models)
            self.assertEqual(len(set(models)), len(models))
            self.assertFalse(set(models) & config.RETIRED_MODELS)

    def test_save_without_model_uses_the_default(self):
        config.save("openai", "sk-test")
        self.assertEqual(config.load()["model"], "gpt-5.4-mini")
        config.save("anthropic", "key")
        self.assertEqual(config.load()["model"], "claude-sonnet-5-5")

    def test_set_model(self):
        config.save("openai", "sk-test")
        self.assertTrue(config.set_model("gpt-5.5"))
        self.assertEqual(config.load()["model"], "gpt-5.5")
        self.assertEqual(config.load()["api_key"], "sk-test")

    def test_empty_formats_fall_back_to_markdown(self):
        config.set_formats([])
        self.assertEqual(config.get_formats(), ["md"])

    def test_retired_model_is_replaced(self):
        config.save("anthropic", "key", "claude-3-5-haiku-20241022")
        expected = config.default_model("anthropic")
        self.assertEqual(config.load()["model"], expected)
        self.assertEqual(self.stored()["model"], expected)

    def test_custom_model_is_kept(self):
        config.save("anthropic", "key", "claude-sonnet-5-5")
        self.assertEqual(config.load()["model"], "claude-sonnet-5-5")

    def test_corrupt_file_is_ignored(self):
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(config.load())
        self.assertTrue(config.set_formats(["md"]))
        self.assertEqual(config.get_formats(), ["md"])

    def test_file_is_owner_only(self):
        config.save("openai", "sk-test")
        if os.name != "nt":
            mode = stat.S_IMODE(os.stat(config.CONFIG_FILE).st_mode)
            self.assertEqual(mode, 0o600)
