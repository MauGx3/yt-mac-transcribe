"""--rewrite-from, the ASR cache, metadata prefetch and reuse, and timeouts."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr, cli
from ytt.cache import Cache
from ytt.formatter import render_json
from ytt.model import Transcript, segments_from_data, segments_to_data, transcript_from_json
from ytt.segments import Segment, Word
from ytt.util import Log
from ytt.youtube import YouTube, video_id

RUNNER = [
    sys.executable,
    "-c",
    "import json,sys; r=json.load(sys.stdin); "
    "print(json.dumps({'segments':[{'text':s['text'].upper()} for s in r['segments']]}))",
]


def transcript():
    segs = [
        Segment(
            0, 1000, "hello there", [Word(0, 500, "hello", 0.4), Word(500, 1000, "there", 0.9)]
        ),
        Segment(1000, 2000, "general kenobi"),
    ]
    return Transcript(
        "aircAruvnKk", "Video", "https://youtu.be/aircAruvnKk", segs, engine="asr", kind="asr"
    )


class RoundTripTests(unittest.TestCase):
    def test_segments_round_trip_keeps_confidence(self):
        segs = transcript().segments
        back = segments_from_data(json.loads(json.dumps(segments_to_data(segs))))
        self.assertEqual(back, segs)

    def test_transcript_from_rendered_json(self):
        t = transcript_from_json(json.loads(render_json(transcript())))
        self.assertEqual((t.video_id, t.engine, t.kind), ("aircAruvnKk", "asr", "asr"))
        self.assertEqual(t.segments[0].words[0].conf, 0.4)


class RewriteFromTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "Video.json")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(render_json(transcript()))
        self.txt = os.path.join(self.tmp, "Video.txt")
        with open(self.txt, "w", encoding="utf-8") as fh:
            fh.write("my edits\n")

    def run_cli(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(
            io.StringIO()
        ), mock.patch.object(cli, "YouTube", side_effect=AssertionError("no network")):
            code = cli.main(["--rewrite-from", self.src, "-o", self.tmp, *extra])
        return code, out.getvalue().split("\n")

    def test_rewrites_without_network_and_keeps_existing_originals(self):
        code, lines = self.run_cli("-f", "txt", "--rewrite-command", *RUNNER)
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], self.txt)
        self.assertTrue(lines[1].endswith("Video.rewritten.txt"))
        self.assertTrue(lines[2].endswith("Video.review.json"))
        with open(self.txt, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "my edits\n")
        with open(lines[1], encoding="utf-8") as fh:
            self.assertIn("HELLO THERE", fh.read())

    def test_needs_rewrite_command(self):
        code, _ = self.run_cli()
        self.assertEqual(code, 2)


class ASRCacheTests(unittest.TestCase):
    def test_second_run_reuses_asr_result(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        c = Cache(enabled=True)
        c.root = tmp
        args = cli.build_parser().parse_args(
            ["https://youtu.be/aircAruvnKk", "--asr", "always", "-o", tmp]
        )
        yt = mock.Mock()
        yt.metadata.return_value = {"id": "aircAruvnKk", "title": "T", "formats": [{}]}
        yt.tracks.return_value = []
        with mock.patch.object(asr, "asr_ready", return_value=True), mock.patch.object(
            asr, "transcribe_audio", return_value=transcript().segments
        ) as ta:
            for _ in range(2):
                t, _paths = cli.process_one(args.urls[0], args, Log(quiet=True), False, c, yt)
                self.assertEqual(t.segments, transcript().segments)
        self.assertEqual(ta.call_count, 1)
        self.assertEqual(ta.call_args.kwargs["info"]["id"], "aircAruvnKk")


class AudioDownloadTests(unittest.TestCase):
    def test_load_info_json_replaces_url(self):
        cmd = asr.audio_download_command("/y", "https://youtu.be/x", "/t", None, "/t/info.json")
        self.assertEqual(cmd[-2:], ["--load-info-json", "/t/info.json"])
        self.assertNotIn("https://youtu.be/x", cmd)

    def test_whisper_cpp_uses_performance_cores(self):
        with mock.patch.object(asr, "performance_cores", return_value=6), mock.patch(
            "subprocess.run", return_value=mock.Mock(returncode=1, stderr="x")
        ) as run, self.assertRaises(asr.ASRUnavailable):
            asr.transcribe_wav("/a.wav", "whisper-cpp", "/w", "/m.bin", Log(quiet=True))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-t") + 1], "6")


class PrefetchTests(unittest.TestCase):
    def test_video_id(self):
        self.assertEqual(video_id("https://www.youtube.com/watch?v=aircAruvnKk&t=3"), "aircAruvnKk")
        self.assertEqual(video_id("https://youtu.be/aircAruvnKk"), "aircAruvnKk")
        self.assertIsNone(video_id("https://www.youtube.com/playlist?list=PL1"))

    def test_one_process_for_many_videos(self):
        with mock.patch("shutil.which", return_value="/usr/bin/yt-dlp"):
            yt = YouTube(Log(quiet=True))
        urls = ["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"]
        lines = "\n".join(json.dumps({"id": u[-11:], "title": u[-1]}) for u in urls)
        with mock.patch(
            "subprocess.run", return_value=mock.Mock(returncode=1, stdout=lines)
        ) as run:
            self.assertEqual(yt.prefetch_metadata(urls), 2)
            self.assertEqual(yt.metadata(urls[1])["title"], "b")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-3:], ["--", *urls])


class TimeoutTests(unittest.TestCase):
    def test_default_scales_with_length(self):
        args = cli.build_parser().parse_args(["x"])
        t = transcript()
        t.segments = t.segments * 500
        self.assertEqual(cli.rewrite_timeout(args, t), 120 + 2 * 1000)
        args.rewrite_timeout = 30
        self.assertEqual(cli.rewrite_timeout(args, t), 30)


if __name__ == "__main__":
    unittest.main()
