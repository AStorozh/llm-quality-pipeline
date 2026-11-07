"""Shared test helpers."""
import importlib.util
import os
import tempfile
import unittest


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class TempDirTestCase(unittest.TestCase):
    """Gives each test a fresh temporary directory in ``self.tmp``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, *parts: str) -> str:
        return os.path.join(self.tmp, *parts)
