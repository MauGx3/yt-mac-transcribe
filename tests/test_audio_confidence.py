"""Speech recognition confidence: parsing it and marking "Unclear audio"."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr  # noqa: E402
from ytt.captions import parse_mlx_json, parse_whisper_json  # noqa: E402
from ytt.formatter import render_json  # noqa: E402
from ytt.model import Transcript  # noqa: E402
from ytt.review import (  # noqa: E402
    AI_UNSURE, UNCLEAR_AUDIO, build_review, word_confidences,
)
from ytt.segments import Segment, Word  # noqa: E402


def tok(text, p, start, end):
    return {"text": text, "p": p, "offsets": {"from": start, "to": end}}


def transcript(segments):
    return Transcript(video_id="v", title="T", url="u", segments=segments,
                      engine="asr", lang="en")


class TestParseWhisperTokens(unittest.TestCase):
    def test_tokens_group_into_words_with_lowest_probability(self):
        payload = {"transcription": [{
            "offsets": {"from": 0, "to": 2000},
            "text": " Hello wonderful world",
            "tokens": [
                tok("[_BEG_]", 1.0, 0, 0),
                tok(" Hello", 0.98, 0, 400),
                tok(" wonder", 0.9, 400, 800),
                tok("ful", 0.2, 800, 1000),
                tok(" world", 0.7, 1000, 1500),
                tok("[_TT_100]", 1.0, 2000, 2000),
            ],
        }]}
        seg = parse_whisper_json(payload)[0]
        self.assertEqual([w.text for w in seg.words], ["Hello", "wonderful", "world"])
        self.assertEqual([w.conf for w in seg.words], [0.98, 0.2, 0.7])
        self.assertEqual((seg.words[1].start_ms, seg.words[1].end_ms), (400, 1000))

    def test_plain_oj_output_still_parses_without_words(self):
        seg = parse_whisper_json({"transcription": [
            {"offsets": {"from": 0, "to": 900}, "text": " hi"}]})[0]
        self.assertEqual((seg.text, seg.words), ("hi", []))

    def test_command_asks_for_full_json(self):
        src = open(asr.__file__, encoding="utf-8").read()
        self.assertIn('"-ojf"', src)


class TestParseMlxWords(unittest.TestCase):
    def test_words_carry_probability_and_ms(self):
        seg = parse_mlx_json({"segments": [{
            "start": 0.0, "end": 1.5, "text": " Hi there",
            "words": [
                {"word": " Hi", "start": 0.0, "end": 0.4, "probability": 0.95},
                {"word": " there", "start": 0.4, "end": 1.2, "probability": 0.31},
            ],
        }]})[0]
        self.assertEqual([(w.text, w.start_ms, w.end_ms, w.conf) for w in seg.words],
                         [("Hi", 0, 400, 0.95), ("there", 400, 1200, 0.31)])

    def test_command_requests_word_timestamps(self):
        cmd = asr.mlx_command("/m", "r/x", "a.wav", "/o", "auto")
        i = cmd.index("--word-timestamps")
        self.assertEqual(cmd[i + 1], "True")


class TestWordConfidences(unittest.TestCase):
    def test_same_words_map_directly(self):
        words = [Word(0, 1, "a", 0.9), Word(1, 2, "b", 0.1)]
        self.assertEqual(word_confidences("a b", words), [0.9, 0.1])

    def test_punctuation_and_split_words_align_by_letters(self):
        words = [Word(0, 1, "It's", 0.9), Word(1, 2, "well", 0.3),
                 Word(2, 3, "-", 0.99), Word(3, 4, "known", 0.8)]
        self.assertEqual(word_confidences("It's well-known.", words), [0.9, 0.3])

    def test_no_confidence_gives_none(self):
        self.assertEqual(word_confidences("a b", [Word(0, 1, "a"), Word(1, 2, "b")]),
                         [None, None])
        self.assertEqual(word_confidences("a b", []), [None, None])

    def test_unmatched_word_is_none(self):
        self.assertEqual(word_confidences("a zzz", [Word(0, 1, "a", 0.4)]), [0.4, None])


class TestUnclearAudioInReview(unittest.TestCase):
    def build(self, text, confs, enhanced, uncertain=None):
        words = [Word(i, i + 1, w, c) for i, (w, c) in enumerate(zip(text.split(), confs))]
        original = transcript([Segment(0, 1000, text, words)])
        new = transcript([Segment(0, 1000, enhanced)])
        if uncertain is not None:
            new.extra["uncertain"] = [uncertain]
        return build_review(original, new)

    def test_changed_unclear_word_flags_its_hunk(self):
        review = self.build("the whether is nice", [0.9, 0.2, 0.9, 0.9], "the weather is nice")
        seg = review["segments"][0]
        self.assertEqual(seg["hunks"][0]["flags"], [UNCLEAR_AUDIO])
        audio = [f for f in seg["flags"] if f["kind"] == UNCLEAR_AUDIO]
        self.assertEqual(audio, [{"start": 4, "end": 11, "kind": UNCLEAR_AUDIO, "word": 1,
                                  "text": "whether", "score": 0.2, "changed": True}])
        self.assertEqual(review["stats"]["flagged"], 1)
        self.assertEqual(review["stats"]["unclear_words"], 1)
        self.assertTrue(review["stats"]["has_audio_confidence"])
        self.assertTrue(review["stats"]["has_confidence"])
        self.assertFalse(review["stats"]["has_ai_confidence"])

    def test_unchanged_unclear_word_still_counts_as_needing_a_look(self):
        review = self.build("we met at noon today", [0.9, 0.9, 0.9, 0.1, 0.9],
                            "We met at noon today")
        seg = review["segments"][0]
        self.assertEqual(seg["hunks"][0]["flags"], [])  # "we" → "We" is not shaky
        audio = [f for f in seg["flags"] if f["kind"] == UNCLEAR_AUDIO]
        self.assertEqual([(f["text"], f["changed"]) for f in audio], [("noon", False)])
        self.assertEqual(review["stats"]["flagged"], 1)

    def test_both_labels_on_one_hunk(self):
        review = self.build("their going", [0.3, 0.9], "They're going",
                            uncertain=[{"start": 0, "end": 7, "kind": AI_UNSURE}])
        self.assertEqual(review["segments"][0]["hunks"][0]["flags"],
                         [AI_UNSURE, UNCLEAR_AUDIO])

    def test_insert_next_to_unclear_word_is_flagged(self):
        review = self.build("go store", [0.9, 0.2], "go to store")
        hunk = review["segments"][0]["hunks"][0]
        self.assertEqual((hunk["op"], hunk["flags"]), ("insert", [UNCLEAR_AUDIO]))

    def test_confident_audio_flags_nothing(self):
        review = self.build("a b", [0.9, 0.95], "A b")
        self.assertEqual(review["stats"]["flagged"], 0)
        self.assertEqual(review["stats"]["unclear_words"], 0)
        self.assertTrue(review["stats"]["has_audio_confidence"])

    def test_threshold_is_adjustable(self):
        words = [Word(0, 1, "a", 0.6)]
        original = transcript([Segment(0, 1000, "a", words)])
        new = transcript([Segment(0, 1000, "A")])
        self.assertEqual(build_review(original, new)["stats"]["unclear_words"], 0)
        self.assertEqual(build_review(original, new, unclear_below=0.7)["stats"]["unclear_words"], 1)


class TestJsonOutputKeepsConfidence(unittest.TestCase):
    def test_conf_written_only_when_known(self):
        t = transcript([Segment(0, 1000, "a b", [Word(0, 1, "a", 0.51234), Word(1, 2, "b")])])
        words = json.loads(render_json(t))["segments"][0]["words"]
        self.assertEqual(words[0]["conf"], 0.5123)
        self.assertNotIn("conf", words[1])


if __name__ == "__main__":
    unittest.main()
