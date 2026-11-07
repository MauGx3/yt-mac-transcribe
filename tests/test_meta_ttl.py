"""Metadata must expire sooner than caption payloads. No network."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.cache import META_TTL, Cache  # noqa: E402


class TestMetaTTL(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.cache = Cache(enabled=True)

    def age(self, seconds, *parts):
        path = self.cache._path(*parts) + ".txt"
        old = time.time() - seconds
        os.utime(path, (old, old))

    def test_metadata_expires_after_meta_ttl(self):
        self.cache.set_json({"id": "x"}, "meta", "u")
        self.age(META_TTL + 60, "meta", "u")
        self.assertIsNone(self.cache.get_json("meta", "u", ttl=META_TTL))

    def test_captions_survive_past_meta_ttl(self):
        self.cache.set_text("WEBVTT", "cap", "u", "en", "auto")
        self.age(META_TTL + 60, "cap", "u", "en", "auto")
        self.assertEqual(self.cache.get_text("cap", "u", "en", "auto"), "WEBVTT")

    def test_per_call_ttl_never_exceeds_user_ttl(self):
        short = Cache(enabled=True, ttl=10)
        short.set_json({"id": "x"}, "meta", "u")
        path = short._path("meta", "u") + ".txt"
        old = time.time() - 60
        os.utime(path, (old, old))
        self.assertIsNone(short.get_json("meta", "u", ttl=META_TTL))


if __name__ == "__main__":
    unittest.main()
