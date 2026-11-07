import sys
from unittest import mock

from helpers import TempDirTestCase

from newlxp import editor, ui


class EditorTest(TempDirTestCase):
    def test_round_trip_with_bom(self):
        path = self.path("sub", "prompt.txt")
        editor.write("Привет\nмир\n", path)
        with open(path, "rb") as handle:
            self.assertTrue(handle.read().startswith(b"\xef\xbb\xbf"))  # BOM for notepads
        self.assertEqual(editor.read(path), "Привет\nмир")

    def test_read_without_bom(self):
        path = self.path("plain.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("  текст  ")
        self.assertEqual(editor.read(path), "текст")

    def test_macos_uses_textedit(self):
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(editor.subprocess, "call", return_value=0) as call:
            self.assertEqual(editor.open_in_notepad("/x.txt"), "TextEdit")
        call.assert_called_once_with(["open", "-e", "/x.txt"])

    def test_no_gui_returns_none(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(editor.os, "name", "posix"), \
                mock.patch.dict(editor.os.environ, {}, clear=True):
            self.assertIsNone(editor.open_in_notepad("/x.txt"))

    def test_terminal_editor_prefers_env(self):
        with mock.patch.dict(editor.os.environ, {"EDITOR": "vim"}, clear=True):
            self.assertEqual(editor.terminal_editor(), "vim")


class WrapTest(TempDirTestCase):
    def test_wrap_keeps_paragraphs(self):
        lines = ui.wrap("один два три\n\nчетыре", 8)
        self.assertEqual(lines, ["один два", "три", "", "четыре"])
