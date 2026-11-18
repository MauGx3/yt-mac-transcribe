# [AI-GENERATED] Regression tests for PR #1 review findings (LLM-authored,
# pending human review). Covers CLI parsing, failure propagation, original
# output preservation, and rewrite provenance serialization.
"""CLI-level tests for the local rewrite integration."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import __version__, cli
from ytt.formatter import render_json, render_md
from ytt.model import Transcript
from ytt.segments import Segment
from ytt.util import Log


def make_transcript(engine="captions", extra=None):
    return Transcript(
        video_id="vid",
        title="Video",
        url="https://youtu.be/vid",
        segments=[Segment(0, 1000, "hello there"), Segment(1000, 2000, "general")],
        duration_ms=2000,
        lang="en",
        kind="manual",
        engine=engine,
        extra=dict(extra or {}),
    )


class TestParser(unittest.TestCase):
    def test_version_flag_is_registered(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            cli.build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(__version__, out.getvalue())

    def test_rewrite_command_keeps_option_like_runner_arguments(self):
        args = cli.build_parser().parse_args([
            "https://youtu.be/vid", "--rewrite-timeout", "9",
            "--rewrite-command", "./rw", "--model", "qwen2.5:7b",
        ])
        self.assertEqual(args.urls, ["https://youtu.be/vid"])
        self.assertEqual(args.rewrite_command, ["./rw", "--model", "qwen2.5:7b"])
        self.assertEqual(args.rewrite_timeout, 9)
        # ytt's own ASR model must not be hijacked by the runner's --model.
        self.assertNotEqual(args.model, "qwen2.5:7b")

    def test_empty_rewrite_command_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["https://youtu.be/vid", "--rewrite-command"])


class TestWriteOutputs(unittest.TestCase):
    def args(self, out, command):
        return cli.build_parser().parse_args(
            ["u", "-o", out, "-f", "txt", "json", "--rewrite-command"] + command)

    def test_original_written_even_when_rewrite_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, [sys.executable, "-c", "import sys; sys.exit(3)"])
            with self.assertRaises(cli.RewriteFailed) as ctx:
                cli.write_outputs(make_transcript(), args, "Video", "vid", False,
                                  Log(quiet=True))
            written = ctx.exception.written
            self.assertEqual([os.path.basename(p) for p in written],
                             ["Video.txt", "Video.json"])
            for path in written:
                self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(os.path.join(tmp, "Video.rewritten.txt")))

    def test_companions_written_after_originals_on_success(self):
        script = ("import json,sys; p=json.load(sys.stdin); "
                  "print(json.dumps({'segments':[{'text':s['text'].upper()} "
                  "for s in p['segments']]}))")
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, [sys.executable, "-c", script])
            written = cli.write_outputs(make_transcript(), args, "Video", "vid",
                                        False, Log(quiet=True))
            self.assertEqual([os.path.basename(p) for p in written], [
                "Video.txt", "Video.json", "Video.rewritten.txt", "Video.rewritten.json",
                "Video.review.json"])
            with open(os.path.join(tmp, "Video.rewritten.txt"), encoding="utf-8") as fh:
                self.assertIn("HELLO THERE", fh.read())
            with open(os.path.join(tmp, "Video.review.json"), encoding="utf-8") as fh:
                review = json.load(fh)
            self.assertEqual(review["version"], 1)
            self.assertGreater(review["stats"]["changed"], 0)


class TestMainReportsRewriteFailure(unittest.TestCase):
    def test_rewrite_failure_is_recorded_and_original_paths_printed(self):
        def fake_process_one(url, args, log, multi, cache):
            if url.endswith("bad"):
                raise cli.RewriteFailed("boom", ["/tmp/bad.txt"])
            return make_transcript(), ["/tmp/good.txt"]

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "YouTube"), \
                mock.patch.object(cli, "process_one", side_effect=fake_process_one), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["https://youtu.be/good", "https://youtu.be/bad",
                             "--delay", "0", "--rewrite-command", "x"])
        self.assertEqual(code, 0)  # existing contract: 0 when any video succeeded
        self.assertEqual(out.getvalue().split(), ["/tmp/good.txt", "/tmp/bad.txt"])
        self.assertIn("failed: https://youtu.be/bad", err.getvalue())

    def test_single_video_rewrite_failure_exits_nonzero(self):
        out = io.StringIO()
        with mock.patch.object(cli, "YouTube"), \
                mock.patch.object(cli, "process_one",
                                  side_effect=cli.RewriteFailed("boom", ["/tmp/a.txt"])), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["https://youtu.be/a", "--rewrite-command", "x"])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue().split(), ["/tmp/a.txt"])


class TestProvenance(unittest.TestCase):
    def test_json_exposes_rewritten_from(self):
        t = make_transcript(engine="rewrite", extra={"rewritten_from": "captions"})
        source = json.loads(render_json(t))["source"]
        self.assertEqual(source["engine"], "rewrite")
        self.assertEqual(source["rewritten_from"], "captions")

    def test_json_omits_rewritten_from_for_originals(self):
        self.assertNotIn("rewritten_from", json.loads(render_json(make_transcript()))["source"])

    def test_markdown_exposes_rewritten_from(self):
        t = make_transcript(engine="rewrite", extra={"rewritten_from": "asr"})
        self.assertIn("- **Rewritten from:** asr", render_md(t))


if __name__ == "__main__":
    unittest.main(verbosity=2)
