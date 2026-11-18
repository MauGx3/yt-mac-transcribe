"""Unit tests for caption-track selection. No network required."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.util import Log
from ytt.youtube import Track, YouTube


def mk(lang, kind, fmts=("json3", "vtt")):
    return Track(lang=lang, name=lang, kind=kind,
                 formats=list(fmts), urls={f: "http://x/%s.%s" % (lang, f) for f in fmts})


class TestTrackSelection(unittest.TestCase):
    def setUp(self):
        self.yt = YouTube.__new__(YouTube)  # bypass yt-dlp presence check
        self.yt.log = Log(quiet=True)

    def pick(self, tracks, langs):
        t = self.yt.pick_track(tracks, langs)
        return t.lang if t else None

    def test_manual_beats_auto(self):
        tracks = [mk("en", "auto"), mk("en", "manual")]
        self.assertEqual(self.pick(tracks, ["en"]), "en")
        picked = self.yt.pick_track(tracks, ["en"])
        self.assertEqual(picked.kind, "manual")

    def test_manual_other_language_beats_auto_english(self):
        # A human transcript in any language is better raw material than ASR.
        tracks = [mk("en", "auto"), mk("de", "manual")]
        self.assertEqual(self.yt.pick_track(tracks, ["en"]).kind, "manual")

    def test_language_preference_order(self):
        tracks = [mk("en", "auto"), mk("pt", "auto")]
        self.assertEqual(self.pick(tracks, ["pt", "en"]), "pt")
        self.assertEqual(self.pick(tracks, ["en", "pt"]), "en")

    def test_region_variant_matches_base(self):
        tracks = [mk("en-GB", "manual")]
        self.assertEqual(self.pick(tracks, ["en"]), "en-GB")

    def test_base_matches_region_request(self):
        tracks = [mk("pt", "auto")]
        self.assertEqual(self.pick(tracks, ["pt-BR"]), "pt")

    def test_translation_is_last_resort(self):
        tracks = [mk("en-pt", "auto-translated"), mk("en", "auto")]
        picked = self.yt.pick_track(tracks, ["pt"])
        self.assertEqual(picked.lang, "en")  # original ASR beats a translation

    def test_translation_used_when_only_option(self):
        tracks = [mk("en-pt", "auto-translated")]
        self.assertEqual(self.pick(tracks, ["pt"]), "en-pt")

    def test_original_preferred_over_other_language(self):
        tracks = [mk("ja", "auto"), mk("ja-en", "auto-translated")]
        picked = self.yt.pick_track(tracks, ["xx"])  # no match at all
        self.assertEqual(picked.lang, "ja")

    def test_empty(self):
        self.assertIsNone(self.yt.pick_track([], ["en"]))

    def test_best_format_prefers_json3(self):
        t = mk("en", "auto", fmts=("ttml", "srv1", "json3", "vtt"))
        self.assertEqual(t.best_format, "json3")

    def test_best_format_falls_back(self):
        t = mk("en", "auto", fmts=("ttml",))
        self.assertEqual(t.best_format, "ttml")


class TestTrackFiltering(unittest.TestCase):
    """`live_chat` is advertised as a subtitle but its payload is HTML."""

    def setUp(self):
        self.yt = YouTube.__new__(YouTube)
        self.yt.log = Log(quiet=True)

    def test_live_chat_excluded(self):
        meta = {
            "subtitles": {},
            "automatic_captions": {
                "live_chat": [{"ext": "json", "url": "http://x/chat", "name": "live chat"}],
                "en": [{"ext": "json3", "url": "http://x/en.json3", "name": "English"}],
            },
        }
        tracks = self.yt.tracks(meta)
        self.assertEqual([t.lang for t in tracks], ["en"])

    def test_unparseable_formats_excluded(self):
        meta = {
            "subtitles": {"en": [{"ext": "json", "url": "http://x/chat"}]},
            "automatic_captions": {},
        }
        self.assertEqual(self.yt.tracks(meta), [])

    def test_auto_translation_classified(self):
        meta = {
            "subtitles": {},
            "automatic_captions": {
                "en-pt": [{"ext": "json3", "url": "http://x/a"}],
                "en": [{"ext": "json3", "url": "http://x/b"}],
            },
        }
        by_lang = {t.lang: t.kind for t in self.yt.tracks(meta)}
        self.assertEqual(by_lang["en-pt"], "auto-translated")
        self.assertEqual(by_lang["en"], "auto")

    def test_original_suffix_not_a_translation(self):
        meta = {
            "subtitles": {},
            "automatic_captions": {"en-orig": [{"ext": "json3", "url": "http://x/a"}]},
        }
        self.assertEqual(self.yt.tracks(meta)[0].kind, "auto")


class TestOutputPaths(unittest.TestCase):
    def setUp(self):
        from ytt.cli import output_path
        self.output_path = output_path

    def test_directory_target(self):
        p = self.output_path("transcripts", "My Video", "abc123", "txt", False)
        self.assertEqual(p, os.path.join("transcripts", "My Video.txt"))

    def test_new_directory_without_extension(self):
        # `-o out3` must be a directory even before it exists.
        p = self.output_path("out3", "My Video", "abc", "srt", False)
        self.assertEqual(p, os.path.join("out3", "My Video.srt"))

    def test_explicit_file_path(self):
        p = self.output_path("notes.txt", "My Video", "abc", "txt", False)
        self.assertEqual(p, "notes.txt")

    def test_explicit_file_path_other_format(self):
        p = self.output_path("notes.txt", "My Video", "abc", "srt", False)
        self.assertEqual(p, "notes.srt")

    def test_batch_keeps_video_id(self):
        p = self.output_path("out", "A Very Long Title " * 10, "vid12345", "txt", True)
        self.assertIn("[vid12345]", p)

    def test_current_dir(self):
        p = self.output_path(".", "T", "id", "json", False)
        self.assertEqual(p, os.path.join(".", "T.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
