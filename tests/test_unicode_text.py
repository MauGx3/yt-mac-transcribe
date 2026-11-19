"""Captions in non-Latin scripts must survive cleanup and quality checks."""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import ClassVar, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.captions import parse_json3, parse_vtt
from ytt.segments import Segment, clean_segments, quality_report, speech_units


def json3(lines):
    return json.dumps(
        {
            "events": [
                {"tStartMs": i * 2000, "dDurationMs": 2000, "segs": [{"utf8": t}]}
                for i, t in enumerate(lines)
            ]
        }
    )


class NonLatinTests(unittest.TestCase):
    SAMPLES: ClassVar[Dict[str, List[str]]] = {
        "ru": ["Привет, мир.", "Как дела?"],
        "ja": ["こんにちは。", "今日はいい天気ですね。"],
        "ar": ["مرحبا بالعالم", "كيف حالك؟"],
        "hi": ["नमस्ते दुनिया", "आप कैसे हैं?"],
        "el": ["Γειά σου κόσμε", "Τι κάνεις;"],
    }

    def test_clean_segments_keeps_every_script(self):
        for lang, lines in self.SAMPLES.items():
            segs = [Segment(i * 1000, i * 1000 + 900, t) for i, t in enumerate(lines)]
            self.assertEqual([s.text for s in clean_segments(segs)], lines, lang)

    def test_json3_and_vtt_parse_non_latin(self):
        lines = self.SAMPLES["ru"]
        self.assertEqual([s.text for s in parse_json3(json3(lines))], lines)
        vtt = (
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n%s\n\n00:00:02.000 --> 00:00:04.000\n%s\n"
            % (
                lines[0],
                lines[1],
            )
        )
        self.assertEqual([s.text for s in parse_vtt(vtt)], lines)

    def test_dedupe_still_collapses_repeats_in_any_script(self):
        segs = [Segment(0, 1000, "Привет"), Segment(1000, 2000, "Привет мир")]
        self.assertEqual([s.text for s in clean_segments(segs)], ["Привет мир"])

    def test_accented_lines_are_not_merged(self):
        segs = [Segment(0, 1000, "é"), Segment(1000, 2000, "e")]
        self.assertEqual(len(clean_segments(segs)), 2)

    def test_japanese_track_is_not_called_sparse(self):
        text = "今日はいい天気ですね。散歩に行きましょう。" * 3
        segs = [Segment(i * 3000, i * 3000 + 2900, text) for i in range(20)]
        self.assertEqual(quality_report(segs, 60000), [])

    def test_speech_units(self):
        self.assertEqual(speech_units("hello world"), 2)
        self.assertEqual(speech_units("こんにちは"), 2)


if __name__ == "__main__":
    unittest.main()
