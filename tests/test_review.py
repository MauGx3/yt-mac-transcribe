"""Tests for the AI-enhancement review document."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.model import Transcript
from ytt.review import (
    AI_UNSURE, apply_decisions, build_review, clean_uncertain, diff_segment,
)
from ytt.rewriter import rewrite_transcript
from ytt.segments import Segment


def transcript(*texts):
    return Transcript(
        video_id="v", title="T", url="https://youtu.be/v",
        segments=[Segment(i * 1000, i * 1000 + 900, t) for i, t in enumerate(texts)],
        engine="asr", lang="en",
    )


class TestDiffSegment(unittest.TestCase):
    def test_no_change_has_no_hunks(self):
        self.assertEqual(diff_segment("same text", "same text")["hunks"], [])

    def test_replace_hunk_reports_word_ranges(self):
        hunks = diff_segment("their going home", "They're going home")["hunks"]
        self.assertEqual(len(hunks), 1)
        self.assertEqual(hunks[0]["op"], "replace")
        self.assertEqual(hunks[0]["orig"], [0, 1])
        self.assertEqual(hunks[0]["new"], [0, 1])
        self.assertEqual(hunks[0]["orig_text"], "their")
        self.assertEqual(hunks[0]["new_text"], "They're")

    def test_insert_and_delete(self):
        self.assertEqual(diff_segment("a c", "a b c")["hunks"][0]["op"], "insert")
        self.assertEqual(diff_segment("a b c", "a c")["hunks"][0]["op"], "delete")

    def test_uncertain_span_flags_overlapping_hunk_only(self):
        spans = [{"start": 0, "end": 7, "kind": AI_UNSURE}]
        hunks = diff_segment("their going home now", "They're going home, now",
                             spans)["hunks"]
        flags = {h["new_text"]: h["flags"] for h in hunks}
        self.assertEqual(flags["They're"], [AI_UNSURE])
        self.assertEqual(flags["home,"], [])

    def test_unsure_span_on_unchanged_text_flags_nothing(self):
        spans = [{"start": 8, "end": 13, "kind": AI_UNSURE}]
        hunks = diff_segment("their going home", "They're going home", spans)["hunks"]
        self.assertEqual(hunks[0]["flags"], [])


class TestCleanUncertain(unittest.TestCase):
    def test_drops_malformed_and_clamps(self):
        items = [
            {"start": 0, "end": 4, "score": 2, "reason": " low "},
            {"start": 5, "end": 5},
            {"start": "a", "end": 3},
            {"start": True, "end": 3},
            "nope",
            {"start": 3, "end": 99},
        ]
        out = clean_uncertain(items, "hello world")
        self.assertEqual(out[0], {"start": 0, "end": 4, "kind": AI_UNSURE,
                                  "score": 1.0, "reason": "low"})
        self.assertEqual(out[1]["end"], 11)
        self.assertEqual(len(out), 2)

    def test_non_list_is_empty(self):
        self.assertEqual(clean_uncertain(None, "x"), [])
        self.assertEqual(clean_uncertain({"start": 0}, "x"), [])


class TestBuildReview(unittest.TestCase):
    def run_rewriter(self, original, response):
        script = "import json; print(json.dumps(%r))" % (response,)
        return rewrite_transcript(original, [sys.executable, "-c", script])

    def test_review_includes_stats_and_flags_from_runner(self):
        original = transcript("their going home", "because its late")
        enhanced = self.run_rewriter(original, {"segments": [
            {"text": "They're going home",
             "uncertain": [{"start": 0, "end": 7, "score": 0.3}]},
            {"text": "because it's late"},
        ]})
        review = build_review(original, enhanced)
        self.assertEqual(review["stats"], {
            "segments": 2, "changed": 2, "flagged": 1, "has_confidence": True})
        self.assertEqual(review["segments"][0]["hunks"][0]["flags"], [AI_UNSURE])
        self.assertEqual(review["segments"][1]["hunks"][0]["flags"], [])
        json.dumps(review)  # must be serialisable

    def test_old_runner_without_uncertain_still_diffs(self):
        original = transcript("their going home")
        enhanced = self.run_rewriter(original, {"segments": [{"text": "They're going home"}]})
        review = build_review(original, enhanced)
        self.assertFalse(review["stats"]["has_confidence"] and review["stats"]["flagged"])
        self.assertEqual(review["stats"]["changed"], 1)

    def test_segment_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            build_review(transcript("a"), transcript("a", "b"))


class TestApplyDecisions(unittest.TestCase):
    def review(self):
        original = transcript("their going home now", "ok")
        enhanced = transcript("They're going home, now", "ok")
        return build_review(original, enhanced)

    def test_accept_all_is_enhanced_text(self):
        self.assertEqual(apply_decisions(self.review()),
                         ["They're going home, now", "ok"])

    def test_reject_one_hunk_keeps_original_wording_there(self):
        review = self.review()
        self.assertEqual(len(review["segments"][0]["hunks"]), 2)
        out = apply_decisions(review, {0: [0]})
        self.assertEqual(out[0], "their going home, now")

    def test_reject_all_restores_original(self):
        out = apply_decisions(self.review(), {0: [0, 1]})
        self.assertEqual(out[0], "their going home now")


if __name__ == "__main__":
    unittest.main()
