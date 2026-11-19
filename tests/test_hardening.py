"""Cache privacy, cookies, output paths, rate limits and report escaping."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr, cli
from ytt import cache as cache_mod
from ytt.cache import Cache
from ytt.report import render_report
from ytt.util import Log
from ytt.youtube import RateLimited, YouTube, trim_metadata

FULL_META = {
    "id": "aircAruvnKk",
    "title": "T",
    "duration": 60,
    "uploader": "U",
    "webpage_url": "https://www.youtube.com/watch?v=aircAruvnKk",
    "language": "en",
    "formats": [{"url": "https://rr1.googlevideo.com/x", "cookies": "SID=secret"}],
    "thumbnails": [{"url": "https://i.ytimg.com/x.jpg"}],
    "subtitles": {"en": [{"ext": "json3", "url": "https://y/tt", "name": "English", "x": 1}]},
    "automatic_captions": {},
}


class TrimMetadataTests(unittest.TestCase):
    def test_keeps_only_what_ytt_reads(self):
        trimmed = trim_metadata(FULL_META)
        self.assertNotIn("formats", trimmed)
        self.assertNotIn("secret", json.dumps(trimmed))
        self.assertEqual(
            trimmed["subtitles"]["en"], [{"ext": "json3", "url": "https://y/tt", "name": "English"}]
        )
        self.assertEqual(trimmed["title"], "T")

    def test_metadata_caches_trimmed_copy_and_returns_full(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        c = Cache(enabled=True)
        c.root = tmp
        with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
            yt = YouTube(Log(quiet=True), cache=c)
        proc = mock.Mock(returncode=0, stdout=json.dumps(FULL_META), stderr="")
        with mock.patch("subprocess.run", return_value=proc):
            self.assertIn("formats", yt.metadata("https://youtu.be/aircAruvnKk"))
        self.assertNotIn("formats", yt.metadata("https://youtu.be/aircAruvnKk"))
        for name in os.listdir(tmp):
            with open(os.path.join(tmp, name)) as fh:
                self.assertNotIn("secret", fh.read())

    def test_metadata_429_raises_rate_limited(self):
        with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
            yt = YouTube(Log(quiet=True))
        proc = mock.Mock(returncode=1, stdout="", stderr="ERROR: HTTP Error 429: Too Many Requests")
        with mock.patch("subprocess.run", return_value=proc), self.assertRaises(RateLimited):
            yt.metadata("https://youtu.be/aircAruvnKk")


class CachePrivacyTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_cache_dir_is_private(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.base}):
            path = cache_mod.cache_dir()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    def test_unwritable_location_falls_back_to_private_temp_dir(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.base}), mock.patch(
            "os.makedirs", side_effect=OSError("read-only")
        ):
            path = cache_mod.cache_dir()
        self.addCleanup(shutil.rmtree, path, True)
        self.assertNotEqual(path, os.path.join(tempfile.gettempdir(), "yt-transcribe-cache"))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    def test_entries_are_0600_and_ignore_planted_tmp_symlink(self):
        c = Cache(enabled=True)
        c.root = self.base
        target = os.path.join(self.base, "victim")
        with open(target, "w") as fh:
            fh.write("keep")
        entry = c._path("cap", "v") + ".txt"
        os.symlink(target, entry + ".tmp")
        c.set_text("payload", "cap", "v")
        with open(target) as fh:
            self.assertEqual(fh.read(), "keep")
        self.assertEqual(stat.S_IMODE(os.stat(entry).st_mode), 0o600)

    def test_prune_removes_only_expired_entries(self):
        c = Cache(enabled=True, ttl=60)
        c.root = self.base
        c.set_text("old", "cap", "old")
        c.set_text("new", "cap", "new")
        old = c._path("cap", "old") + ".txt"
        past = time.time() - cache_mod.DEFAULT_TTL - 10
        os.utime(old, (past, past))
        self.assertEqual(c.prune(), 1)
        self.assertIsNone(c.get_text("cap", "old"))
        self.assertEqual(c.get_text("cap", "new"), "new")

    def test_prune_runs_at_most_daily(self):
        c = Cache(enabled=True)
        c.root = self.base
        with mock.patch.object(c, "prune", return_value=0) as prune:
            c.prune_if_due()
            c.prune_if_due()
        self.assertEqual(prune.call_count, 1)


class CookiesTests(unittest.TestCase):
    def test_audio_download_forwards_cookies_before_double_dash(self):
        cmd = asr.audio_download_command("/y", "https://youtu.be/aircAruvnKk", "/t", "chrome")
        self.assertLess(cmd.index("--cookies-from-browser"), cmd.index("--"))
        self.assertEqual(cmd[-1], "https://youtu.be/aircAruvnKk")

    def test_cli_passes_cookies_to_asr(self):
        args = cli.build_parser().parse_args(
            ["https://youtu.be/aircAruvnKk", "--cookies-from-browser", "safari", "--asr", "always"]
        )
        yt = mock.Mock()
        yt.metadata.return_value = {"id": "aircAruvnKk", "title": "T"}
        yt.tracks.return_value = []
        with mock.patch.object(asr, "asr_ready", return_value=True), mock.patch.object(
            asr, "transcribe_audio", side_effect=RuntimeError("stop")
        ) as ta:
            cli.process_one("https://youtu.be/aircAruvnKk", args, Log(quiet=True), False, yt=yt)
        self.assertEqual(ta.call_args.kwargs["cookies"], "safari")


class OutputPathTests(unittest.TestCase):
    def test_file_out_with_several_videos_gets_one_file_each(self):
        a = cli.output_path("notes.txt", "A", "id1", "txt", True)
        b = cli.output_path("notes.txt", "B", "id2", "txt", True)
        self.assertEqual((a, b), ("notes [id1].txt", "notes [id2].txt"))

    def test_single_video_file_out_unchanged(self):
        self.assertEqual(cli.output_path("notes.txt", "A", "id1", "txt", False), "notes.txt")
        self.assertEqual(cli.output_path("notes.txt", "A", "id1", "srt", False), "notes.srt")


class ModelSearchTests(unittest.TestCase):
    def test_current_directory_is_searched_last(self):
        dirs = asr.model_search_dirs()
        self.assertGreater(
            dirs.index(os.getcwd()), dirs.index(os.path.expanduser("~/.cache/whisper"))
        )


class ReportEscapingTests(unittest.TestCase):
    def test_comment_and_script_tags_cannot_break_the_data_block(self):
        review = {
            "title": "x",
            "url": "",
            "stats": {},
            "segments": [
                {
                    "index": 0,
                    "start_ms": 0,
                    "original": "<!--<script> & </script>",
                    "enhanced": "<!--<script> & </script>",
                    "hunks": [],
                }
            ],
        }
        page = render_report(review)
        data = page.split('id="review-data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", data)
        self.assertEqual(json.loads(data), review)


class BatchDelayTests(unittest.TestCase):
    def test_no_pause_after_a_video_served_from_cache(self):
        yt = mock.Mock(requests=0)
        yt.prefetch_metadata.return_value = 0
        sleeps = []
        with mock.patch.object(cli, "YouTube", return_value=yt), mock.patch.object(
            cli, "process_one", return_value=(object(), [])
        ), mock.patch("time.sleep", side_effect=sleeps.append), contextlib.redirect_stderr(
            io.StringIO()
        ):
            cli.main(["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb", "--no-cache"])
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
