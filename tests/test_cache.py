"""Unit tests for the on-disk cache. No network required."""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.cache import Cache  # noqa: E402


class TestCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ytt-cache-test-")
        self.cache = Cache(enabled=True, ttl=60)
        self.cache.root = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_miss_then_hit(self):
        self.assertIsNone(self.cache.get_text("cap", "vid1", "en"))
        self.cache.set_text("hello world", "cap", "vid1", "en")
        self.assertEqual(self.cache.get_text("cap", "vid1", "en"), "hello world")

    def test_keys_are_distinct(self):
        self.cache.set_text("a", "cap", "vid1", "en")
        self.cache.set_text("b", "cap", "vid1", "pt")
        self.cache.set_text("c", "cap", "vid2", "en")
        self.assertEqual(self.cache.get_text("cap", "vid1", "en"), "a")
        self.assertEqual(self.cache.get_text("cap", "vid1", "pt"), "b")
        self.assertEqual(self.cache.get_text("cap", "vid2", "en"), "c")

    def test_ttl_expiry(self):
        self.cache.ttl = 0
        self.cache.set_text("stale", "cap", "vid", "en")
        time.sleep(0.01)
        self.assertIsNone(self.cache.get_text("cap", "vid", "en"))

    def test_json_roundtrip(self):
        self.cache.set_json({"title": "T", "n": 3}, "meta", "url")
        self.assertEqual(self.cache.get_json("meta", "url"), {"title": "T", "n": 3})

    def test_corrupt_json_returns_none(self):
        self.cache.set_text("not json{", "meta", "url")
        self.assertIsNone(self.cache.get_json("meta", "url"))

    def test_disabled_cache_never_stores(self):
        c = Cache(enabled=False)
        c.set_text("x", "a")
        self.assertIsNone(c.get_text("a"))

    def test_clear(self):
        self.cache.set_text("x", "a")
        self.cache.set_text("y", "b")
        self.assertEqual(self.cache.clear(), 2)
        self.assertIsNone(self.cache.get_text("a"))

    def test_size_bytes(self):
        self.cache.set_text("x" * 100, "a")
        self.assertGreaterEqual(self.cache.size_bytes(), 100)

    def test_unicode_survives(self):
        self.cache.set_text("日本語のテキスト", "cap", "v", "ja")
        self.assertEqual(self.cache.get_text("cap", "v", "ja"), "日本語のテキスト")

    def test_hit_miss_counters(self):
        self.cache.get_text("missing")
        self.cache.set_text("v", "present")
        self.cache.get_text("present")
        self.assertEqual(self.cache.hits, 1)
        self.assertEqual(self.cache.misses, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
