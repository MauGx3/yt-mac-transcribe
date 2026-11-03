"""Tests for local context-aware transcript rewriting."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.model import Transcript
from ytt.rewriter import rewrite_transcript
from ytt.segments import Segment


class TestLocalRewriter(unittest.TestCase):
    def make_transcript(self):
        return Transcript(
            video_id="test",
            title="Test",
            url="https://youtu.be/test",
            segments=[
                Segment(1000, 2000, "their going home"),
                Segment(2100, 3200, "because its late"),
            ],
            duration_ms=5000,
            lang="en",
            kind="auto",
            engine="captions",
        )

    def test_rewriter_passes_full_context_and_preserves_timing(self):
        script = (
            "import json,sys; "
            "p=json.load(sys.stdin); "
            "assert len(p['segments']) == 2; "
            "assert p['segments'][0]['next_text'] == 'because its late'; "
            "print(json.dumps({'segments': ["
            "{'text':'They are going home'},"
            "{'text':'because it is late'}]}))"
        )
        out = rewrite_transcript(
            self.make_transcript(), [sys.executable, "-c", script]
        )
        self.assertEqual([s.text for s in out.segments], [
            "They are going home", "because it is late"
        ])
        self.assertEqual([(s.start_ms, s.end_ms) for s in out.segments], [
            (1000, 2000), (2100, 3200)
        ])
        self.assertEqual(out.engine, "rewrite")
        self.assertEqual(out.extra["rewritten_from"], "captions")

    def test_rewriter_rejects_wrong_segment_count(self):
        script = "import json; print(json.dumps({'segments':[{'text':'only one'}]}))"
        with self.assertRaises(ValueError):
            rewrite_transcript(self.make_transcript(), [sys.executable, "-c", script])


class TestRewritePath(unittest.TestCase):
    def test_companion_path(self):
        from ytt.cli import rewritten_output_path
        self.assertEqual(rewritten_output_path("out/video.srt"), "out/video.rewritten.srt")
        self.assertEqual(rewritten_output_path("video"), "video.rewritten")


if __name__ == "__main__":
    unittest.main(verbosity=2)
