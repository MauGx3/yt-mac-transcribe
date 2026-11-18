"""Model-path resolution for the whisper.cpp fallback. No network."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr


class TestResolveModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def touch(self, name):
        path = os.path.join(self.tmp.name, name)
        open(path, "w").close()
        return path

    def test_name_resolves_to_ggml_file(self):
        path = self.touch("ggml-small.en.bin")
        self.assertEqual(asr.resolve_model("small.en", [self.tmp.name]), path)

    def test_existing_path_is_returned_unchanged(self):
        path = self.touch("custom.bin")
        self.assertEqual(asr.resolve_model(path, []), path)

    def test_missing_model_raises_with_download_hint(self):
        with self.assertRaises(asr.ASRUnavailable) as ctx:
            asr.resolve_model("small.en", [self.tmp.name])
        message = str(ctx.exception)
        # Homebrew's whisper-cpp ships no download script, so the hint is a plain curl.
        self.assertNotIn("whisper-cpp-download-ggml-model", message)
        self.assertIn("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin",
                      message)
        self.assertIn("~/.cache/whisper/ggml-small.en.bin", message)

    def test_env_dir_is_searched_first(self):
        with mock.patch.dict(os.environ, {"YTT_MODEL_DIR": self.tmp.name}):
            self.assertEqual(asr.model_search_dirs()[0], self.tmp.name)


class TestDetectBackends(unittest.TestCase):
    def test_openai_whisper_is_not_treated_as_whisper_cpp(self):
        found = {"whisper": "/usr/bin/whisper"}
        with mock.patch.object(asr, "_which", side_effect=found.get):
            self.assertIsNone(asr.detect_backends()["whisper.cpp"])


if __name__ == "__main__":
    unittest.main()
