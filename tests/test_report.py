"""Tests for the HTML review report."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.cli import main, report_output_path, reviewed_name
from ytt.model import Transcript
from ytt.report import render_report
from ytt.review import build_review
from ytt.segments import Segment, Word


def transcript(segments, title="Talk <b>&</b>", url="https://www.youtube.com/watch?v=abc"):
    return Transcript(
        video_id="abc", title=title, url=url, segments=segments, engine="asr", lang="en"
    )


def sample_review():
    words = [
        Word(i, i + 1, w, c)
        for i, (w, c) in enumerate(zip(["the", "whether", "is", "nice"], [0.9, 0.2, 0.9, 0.9]))
    ]
    kept = [
        Word(i, i + 1, w, c)
        for i, (w, c) in enumerate(zip(["we", "met", "at", "noon"], [0.9, 0.9, 0.9, 0.1]))
    ]
    original = transcript(
        [
            Segment(0, 900, "the whether is nice", words),
            Segment(65000, 66000, "we met at noon", kept),
            Segment(70000, 71000, "nothing to see", []),
        ]
    )
    enhanced = transcript(
        [
            Segment(0, 900, "the weather is nice"),
            Segment(65000, 66000, "we met at noon"),
            Segment(70000, 71000, "nothing to see"),
        ]
    )
    enhanced.extra["uncertain"] = [[{"start": 4, "end": 11, "score": 0.3}], [], []]
    return build_review(original, enhanced)


class TestRenderReport(unittest.TestCase):
    def setUp(self):
        self.page = render_report(sample_review(), "Talk.reviewed.txt")

    def test_escapes_title(self):
        self.assertIn("Review: Talk &lt;b&gt;&amp;&lt;/b&gt;", self.page)
        self.assertNotIn("<b>&</b>", self.page)

    def test_shows_both_labels_on_one_change(self):
        self.assertIn('class="hunk flag-ai flag-audio flagged"', self.page)
        self.assertIn("<del>whether</del> <ins>weather</ins>", self.page)

    def test_lists_unclear_words_the_rewrite_kept(self):
        self.assertIn('<mark class="audio"', self.page)
        self.assertIn("Unchanged, check against the audio: noon", self.page)

    def test_skips_untouched_segments_and_links_timestamps(self):
        self.assertNotIn("nothing to see</p>", self.page)
        self.assertIn('href="https://www.youtube.com/watch?v=abc&amp;t=65s">01:05</a>', self.page)

    def test_embedded_data_cannot_close_the_script(self):
        review = sample_review()
        review["title"] = "</script><script>alert(1)</script>"
        page = render_report(review)
        data = page.split('id="review-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(data)["title"], review["title"])

    def test_self_contained(self):
        self.assertNotIn("http://", self.page)
        self.assertNotIn("<link", self.page)
        self.assertNotIn("src=", self.page)

    def test_no_confidence_notes(self):
        page = render_report(
            build_review(transcript([Segment(0, 1, "a b")]), transcript([Segment(0, 1, "A b")]))
        )
        self.assertIn("no change is marked AI unsure", page)
        self.assertIn("nothing is marked Unclear audio", page)


class TestReportCli(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(report_output_path("/x/My Video.review.json"), "/x/My Video.review.html")
        self.assertEqual(reviewed_name("/x/My Video.review.json"), "My Video.reviewed.txt")

    def test_rebuilds_report_from_review_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Talk.review.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(sample_review(), fh)
            self.assertEqual(main(["-q", "--review-report", path]), 0)
            with open(os.path.join(tmp, "Talk.review.html"), encoding="utf-8") as fh:
                self.assertIn('data-reviewed="Talk.reviewed.txt"', fh.read())

    def test_bad_review_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.review.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[]")
            self.assertEqual(main(["-q", "--review-report", path]), 1)
            self.assertEqual(main(["-q", "--review-report", os.path.join(tmp, "missing")]), 1)


if __name__ == "__main__":
    unittest.main()
