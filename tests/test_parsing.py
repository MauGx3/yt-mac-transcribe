"""Unit tests for parsing, cleanup, and formatting. No network required."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.captions import detect_format, parse_json3, parse_srt, parse_vtt  # noqa: E402
from ytt.formatter import render  # noqa: E402
from ytt.model import Transcript  # noqa: E402
from ytt.segments import (  # noqa: E402
    Segment,
    clean_segments,
    merge_paragraphs,
    quality_report,
    strip_sound_tags,
    word_count,
)
from ytt.util import sanitize_filename  # noqa: E402


STATIC_JSON3 = {
    "events": [
        {"tStartMs": 4220, "dDurationMs": 1180, "segs": [{"utf8": "This is a 3."}]},
        {"tStartMs": 6060, "dDurationMs": 4653,
         "segs": [{"utf8": "It's sloppily written and rendered at an extremely low resolution of 28x28 pixels,"}]},
        {"tStartMs": 10713, "dDurationMs": 3007,
         "segs": [{"utf8": "but your brain has no trouble recognizing it as a 3."}]},
    ]
}

# Modern auto captions: rolling windows, newline markers, per-word offsets.
ROLLING_JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 2800, "wWinId": 1, "segs": [{"utf8": "[Applause]"}]},
        {"tStartMs": 230, "dDurationMs": 2570, "wWinId": 1, "aAppend": 1,
         "segs": [{"utf8": "\n"}]},
        {"tStartMs": 240, "dDurationMs": 4400, "wWinId": 1, "segs": [
            {"utf8": "Hello", "acAsrConf": 0},
            {"utf8": " everyone.", "tOffsetMs": 240, "acAsrConf": 0},
            {"utf8": " Good", "tOffsetMs": 800, "acAsrConf": 0},
            {"utf8": " morning.", "tOffsetMs": 1200, "acAsrConf": 0},
        ]},
        {"tStartMs": 2790, "dDurationMs": 1850, "wWinId": 1, "aAppend": 1,
         "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2800, "dDurationMs": 4240, "wWinId": 1,
         "segs": [{"utf8": "that today is the start of Gemini"}]},
    ]
}

# Rolling window that re-emits the previous line's text verbatim.
DUPLICATE_JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello there."}]},
        {"tStartMs": 900, "dDurationMs": 1500, "segs": [{"utf8": "Hello there."}]},
        {"tStartMs": 2000, "dDurationMs": 2000, "segs": [{"utf8": "General Kenobi."}]},
    ]
}

VTT_FIXTURE = """WEBVTT
Kind: captions
Language: en

00:00:04.220 --> 00:00:05.400 align:start position:0%
This is a 3.

00:00:06.060 --> 00:00:10.713 align:start position:0%
It's sloppily written and<00:00:07.000><c> rendered</c>
"""

SRT_FIXTURE = """1
00:00:04,220 --> 00:00:05,400
This is a 3.

2
00:00:06,060 --> 00:00:10,713
It's sloppily written
and rendered.
"""


def make_transcript(segments):
    return Transcript(
        video_id="test", title="Test Video", url="https://youtu.be/test",
        segments=segments, duration_ms=60000, channel="Chan", lang="en",
        track_name="English", kind="manual", engine="captions",
    )


class TestJson3(unittest.TestCase):
    def test_static_captions(self):
        segs = parse_json3(STATIC_JSON3)
        self.assertEqual(len(segs), 3)
        self.assertEqual(segs[0].text, "This is a 3.")
        self.assertEqual(segs[0].start_ms, 4220)
        self.assertEqual(segs[0].end_ms, 5400)

    def test_rolling_captions_skip_append_markers(self):
        segs = parse_json3(ROLLING_JSON3)
        texts = [s.text for s in segs]
        self.assertNotIn("\n", texts)
        self.assertEqual(texts[0], "[Applause]")
        self.assertEqual(texts[1], "Hello everyone. Good morning.")
        self.assertEqual(len(segs), 3)

    def test_word_offsets_parsed(self):
        segs = parse_json3(ROLLING_JSON3)
        words = segs[1].words
        self.assertEqual(len(words), 4)
        self.assertEqual(words[1].start_ms, 240 + 240)
        self.assertGreaterEqual(words[0].end_ms, words[0].start_ms)

    def test_duplicate_lines_removed(self):
        segs = parse_json3(DUPLICATE_JSON3)
        texts = [s.text for s in segs]
        self.assertEqual(texts, ["Hello there.", "General Kenobi."])

    def test_grown_window_keeps_longer_line(self):
        payload = {"events": [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello"}]},
            {"tStartMs": 100, "dDurationMs": 2000, "segs": [{"utf8": "Hello there friend"}]},
        ]}
        segs = parse_json3(payload)
        self.assertEqual([s.text for s in segs], ["Hello there friend"])

    def test_overlaps_clamped(self):
        segs = parse_json3(ROLLING_JSON3)
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a.end_ms, b.start_ms + 1)

    def test_accepts_bytes_and_string(self):
        self.assertEqual(len(parse_json3(json.dumps(STATIC_JSON3))), 3)
        self.assertEqual(len(parse_json3(json.dumps(STATIC_JSON3).encode())), 3)

    def test_empty_events(self):
        self.assertEqual(parse_json3({"events": []}), [])


class TestOtherFormats(unittest.TestCase):
    def test_vtt(self):
        segs = parse_vtt(VTT_FIXTURE)
        self.assertEqual(segs[0].text, "This is a 3.")
        self.assertEqual(segs[0].start_ms, 4220)
        self.assertNotIn("<c>", segs[1].text)
        self.assertNotIn("align:start", segs[1].text)

    def test_srt(self):
        segs = parse_srt(SRT_FIXTURE)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[1].text, "It's sloppily written and rendered.")

    def test_detect_format(self):
        self.assertEqual(detect_format("WEBVTT\n\n"), "vtt")
        self.assertEqual(detect_format('{"events":[]}'), "json3")
        self.assertEqual(detect_format("1\n00:00:01,000 --> 00:00:02,000\nhi"), "srt")


class TestSegments(unittest.TestCase):
    def test_newlines_collapsed(self):
        segs = clean_segments([Segment(0, 1000, "Hello\nthere")])
        self.assertEqual(segs[0].text, "Hello there")

    def test_whitespace_normalised(self):
        segs = clean_segments([Segment(0, 1000, "  a   b\tc  ")])
        self.assertEqual(segs[0].text, "a b c")

    def test_empty_dropped(self):
        segs = clean_segments([
            Segment(0, 100, "ok"),
            Segment(200, 300, "   "),
            Segment(400, 500, ""),
            Segment(600, 700, "\u200b"),
        ])
        self.assertEqual([s.text for s in segs], ["ok"])

    def test_strip_sound_tags(self):
        segs = [Segment(0, 1000, "[Music]"), Segment(1000, 2000, "[Applause]"),
                Segment(2000, 3000, "Real words here.")]
        out = strip_sound_tags(segs)
        self.assertEqual([s.text for s in out], ["Real words here."])

    def test_zero_duration_repaired(self):
        segs = clean_segments([Segment(1000, 1000, "text here")])
        self.assertGreater(segs[0].end_ms, segs[0].start_ms)

    def test_word_count(self):
        self.assertEqual(word_count([Segment(0, 1, "one two three")]), 3)

    def test_merge_paragraphs_respects_gap(self):
        segs = clean_segments([
            Segment(0, 1000, "First sentence."),
            Segment(1000, 2000, "Second sentence."),
            Segment(10000, 11000, "After a long pause."),
        ])
        paras = merge_paragraphs(segs, max_gap_ms=2200)
        self.assertEqual(len(paras), 2)
        self.assertIn("Second sentence.", paras[0][1])

    def test_merge_paragraphs_does_not_split_mid_sentence(self):
        # 1200 chars of non-sentence-ending fragments should stay together
        # until a sentence boundary is reached.
        segs = [Segment(i * 1000, i * 1000 + 900, "fragment %d" % i) for i in range(60)]
        segs.append(Segment(60000, 61000, "The end."))
        paras = merge_paragraphs(segs, max_chars=300)
        self.assertTrue(any(p[1].endswith("The end.") for p in paras))
        for _, text in paras:
            self.assertFalse(text.startswith(" "))

    def test_merge_joins_hyphenated_breaks(self):
        segs = [Segment(0, 1000, "inter-"), Segment(1000, 2000, "national")]
        paras = merge_paragraphs(segs)
        self.assertEqual(paras[0][1], "international")


class TestQuality(unittest.TestCase):
    def test_good_captions_pass(self):
        segs = clean_segments([
            Segment(i * 2000, i * 2000 + 1900, "word%d other%d unique%d" % (i, i, i))
            for i in range(20)
        ])
        self.assertEqual(quality_report(segs, 40000), [])

    def test_empty_flagged(self):
        self.assertTrue(quality_report([], 60000))

    def test_sparse_flagged(self):
        segs = [Segment(0, 1000, "hi")]
        self.assertTrue(any("sparse" in p for p in quality_report(segs, 600000)))

    def test_repetitive_flagged(self):
        # A degenerate ASR loop: same short phrase over and over.
        segs = [Segment(i * 1000, i * 1000 + 900, "the the the the") for i in range(200)]
        self.assertTrue(any("repetitive" in p for p in quality_report(segs, 200000)))

    def test_normal_long_text_not_flagged_as_repetitive(self):
        # Real English has a low overall type/token ratio but healthy local
        # diversity; this must not trip the loop detector.
        vocab = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
        segs = []
        for i in range(200):
            words = [vocab[(i * 7 + j) % len(vocab)] for j in range(8)]
            words[0] = "word%d" % i
            words[1] = "term%d" % (i * 3)
            words[2] = "item%d" % (i * 5)
            words[3] = "unit%d" % (i * 11)
            segs.append(Segment(i * 1000, i * 1000 + 900, " ".join(words)))
        flags = quality_report(segs, 200000)
        self.assertFalse(any("repetitive" in p for p in flags), flags)

    def test_tag_heavy_flagged(self):
        segs = [Segment(i * 1000, i * 1000 + 900, "[Music]") for i in range(20)]
        self.assertTrue(any("non-speech" in p for p in quality_report(segs, 20000)))


class TestFormatters(unittest.TestCase):
    def setUp(self):
        self.t = make_transcript(clean_segments([
            Segment(4220, 5400, "This is a 3."),
            Segment(6060, 10713, "It's sloppily written and rendered at an extremely low resolution."),
            Segment(10713, 13720, "but your brain has no trouble recognizing it as a 3."),
        ]))

    def test_srt_structure(self):
        out = render(self.t, "srt")
        self.assertIn("00:00:04,220 --> 00:00:05,400", out)
        self.assertTrue(out.startswith("1\n"))
        self.assertIn("\n2\n", out)

    def test_vtt_structure(self):
        out = render(self.t, "vtt")
        self.assertTrue(out.startswith("WEBVTT"))
        self.assertIn("00:00:04.220 --> 00:00:05.400", out)

    def test_json_roundtrip(self):
        data = json.loads(render(self.t, "json"))
        self.assertEqual(data["video_id"], "test")
        self.assertEqual(data["source"]["engine"], "captions")
        self.assertEqual(len(data["segments"]), 3)
        self.assertEqual(data["segments"][0]["text"], "This is a 3.")

    def test_txt_paragraphs(self):
        out = render(self.t, "txt")
        self.assertIn("This is a 3.", out)
        self.assertNotIn("[", out)

    def test_txt_timestamps(self):
        out = render(self.t, "txt", timestamps=True)
        self.assertIn("[0:04]", out)

    def test_md(self):
        out = render(self.t, "md")
        self.assertIn("# Test Video", out)
        self.assertIn("**Source:**", out)

    def test_srt_wraps_long_lines(self):
        long_seg = Segment(0, 3000, "word " * 60)
        out = render(make_transcript([long_seg]), "srt")
        cue_lines = [ln for ln in out.split("\n") if ln.startswith("word")]
        self.assertTrue(all(len(ln) <= 60 for ln in cue_lines))

    def test_srt_has_no_overlap(self):
        out = render(self.t, "srt")
        self.assertNotIn("00:00:05,400 --> 00:00:06,060", out)


class TestUtil(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize_filename("a/b:c*d?"), "a - b - c - d")
        self.assertEqual(sanitize_filename("  spaced   out  "), "spaced out")
        self.assertLessEqual(len(sanitize_filename("x" * 300)), 80)
        self.assertEqual(sanitize_filename(""), "transcript")

    def test_sanitize_collapses_dash_runs(self):
        # A pipe becomes a dash; runs of dashes must not leak into the name.
        self.assertEqual(
            sanitize_filename("But what is a neural network? | Deep learning chapter 1"),
            "But what is a neural network - Deep learning chapter 1",
        )
        self.assertEqual(sanitize_filename("a --- b"), "a - b")
        self.assertEqual(sanitize_filename("Foo - Bar"), "Foo - Bar")

    def test_sanitize_keeps_unicode(self):
        self.assertIn("日本語", sanitize_filename("日本語のビデオ"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
