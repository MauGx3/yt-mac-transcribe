"""URLs must never reach yt-dlp as options, and must be YouTube URLs."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr, cli
from ytt.util import Log
from ytt.youtube import InvalidURL, YouTube, validate_url


class ValidateURLTests(unittest.TestCase):
    def test_accepts_youtube_hosts(self):
        for url in (
            "https://www.youtube.com/watch?v=aircAruvnKk",
            "https://youtu.be/aircAruvnKk",
            "http://m.youtube.com/watch?v=aircAruvnKk",
            "https://music.youtube.com/watch?v=aircAruvnKk",
            "https://www.youtube.com/playlist?list=PLabc",
            "https://www.youtube-nocookie.com/embed/aircAruvnKk",
        ):
            self.assertEqual(validate_url(url), url)

    def test_bare_video_id_becomes_watch_url(self):
        self.assertEqual(validate_url("aircAruvnKk"), "https://www.youtube.com/watch?v=aircAruvnKk")

    def test_rejects_options_and_other_hosts(self):
        for bad in (
            "--exec=touch /tmp/pwned",
            "-o/tmp/x",
            "-----------",
            "file:///etc/passwd",
            "https://evil.example/watch?v=x",
            "https://youtube.com.evil.example/x",
            "ftp://youtube.com/x",
            "",
        ):
            with self.assertRaises(InvalidURL, msg=bad):
                validate_url(bad)


class YtDlpArgvTests(unittest.TestCase):
    def setUp(self):
        with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
            self.yt = YouTube(Log(quiet=True), cookies="safari")

    def test_double_dash_precedes_urls_and_cookies_stay_options(self):
        cmd = self.yt.ytdlp_command(["-J"], ["https://youtu.be/aircAruvnKk"])
        self.assertEqual(cmd[-2:], ["--", "https://youtu.be/aircAruvnKk"])
        self.assertLess(cmd.index("--cookies-from-browser"), cmd.index("--"))

    def test_metadata_call_uses_double_dash(self):
        seen = {}

        def fake_run(cmd, **_):
            seen["cmd"] = cmd
            return mock.Mock(returncode=0, stdout="{}", stderr="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            self.yt.metadata("https://youtu.be/aircAruvnKk")
        self.assertEqual(seen["cmd"][-2], "--")

    def test_audio_download_uses_double_dash(self):
        seen = []

        def fake_run(cmd, **_):
            seen.append(cmd)
            return mock.Mock(returncode=1, stdout="", stderr="boom")

        backends = {"yt-dlp": "/y", "ffmpeg": "/f", "whisper.cpp": "/w", "mlx_whisper": None}
        with mock.patch.object(asr, "detect_backends", return_value=backends), mock.patch.object(
            asr, "resolve_model", return_value="/m.bin"
        ), mock.patch("subprocess.run", side_effect=fake_run), self.assertRaises(
            asr.ASRUnavailable
        ):
            asr.transcribe_audio("https://youtu.be/aircAruvnKk", "small.en", Log(quiet=True))
        self.assertEqual(seen[0][-2:], ["--", "https://youtu.be/aircAruvnKk"])


class BatchFileTests(unittest.TestCase):
    def test_option_lines_in_batch_file_are_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("--exec=touch /tmp/pwned\nhttps://youtu.be/aircAruvnKk\n")
        self.addCleanup(os.unlink, fh.name)
        calls = []

        def fake_process(url, *a, **k):
            calls.append(url)
            return object(), []

        err = io.StringIO()
        with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"), mock.patch.object(
            cli, "process_one", side_effect=fake_process
        ), redirect_stderr(err):
            code = cli.main(["--batch", fh.name, "--no-cache"])
        self.assertEqual(calls, ["https://youtu.be/aircAruvnKk"])
        self.assertEqual(code, cli.EXIT_PARTIAL)
        self.assertIn("skipping", err.getvalue())


if __name__ == "__main__":
    unittest.main()
