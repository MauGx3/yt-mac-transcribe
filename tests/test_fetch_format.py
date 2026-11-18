"""Regression tests: caption format must not be assumed on cache hits. No network."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.cache import Cache
from ytt.captions import parse_any
from ytt.util import Log
from ytt.youtube import Track, YouTube

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello world\n"


class TestFetchFormat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.yt = YouTube.__new__(YouTube)  # bypass yt-dlp presence check
        self.yt.log = Log(quiet=True)
        self.yt.cache = Cache(enabled=True)
        self.track = Track(
            lang="en",
            name="en",
            kind="auto",
            formats=["json3", "vtt"],
            urls={"json3": "http://x/a.json3", "vtt": "http://x/a.vtt"},
        )

    def test_cached_vtt_is_not_parsed_as_json3(self):
        self.yt.cache.set_text(VTT, "cap", "http://v", "en", "auto")
        payload, fmt = self.yt.fetch_track(self.track, "http://v")
        self.assertIsNone(fmt)
        segments = parse_any(payload, fmt)
        self.assertEqual(segments[0].text, "hello world")

    def test_ytdlp_fallback_reports_unknown_format(self):
        self.yt.cache = Cache(enabled=False)
        with mock.patch.object(
            self.yt, "fetch_text", side_effect=ValueError("bad")
        ), mock.patch.object(self.yt, "_fetch_via_ytdlp", return_value=VTT):
            payload, fmt = self.yt.fetch_track(self.track, "http://v")
        self.assertIsNone(fmt)
        self.assertEqual(parse_any(payload, fmt)[0].text, "hello world")


if __name__ == "__main__":
    unittest.main()
