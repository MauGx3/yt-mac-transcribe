"""MLX Whisper engine: model mapping, engine choice, parsing, command. No network."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr, cli  # noqa: E402
from ytt.captions import parse_mlx_json  # noqa: E402
from ytt.util import Log  # noqa: E402

NONE = {"yt-dlp": "/y", "ffmpeg": "/f", "whisper.cpp": None, "mlx_whisper": None}


class TestModels(unittest.TestCase):
    def test_short_names_map_to_mlx_community_repos(self):
        self.assertEqual(asr.resolve_mlx_model("small.en"), "mlx-community/whisper-small.en-mlx")
        self.assertEqual(asr.resolve_mlx_model("large-v3-turbo"), "mlx-community/whisper-large-v3-turbo")

    def test_every_default_hint_has_an_mlx_mapping(self):
        for name in asr.MODEL_HINTS:
            self.assertIn(name, asr.MLX_MODELS)

    def test_repo_ids_pass_through_and_junk_is_rejected(self):
        self.assertEqual(asr.resolve_mlx_model("me/custom"), "me/custom")
        with self.assertRaises(asr.ASRUnavailable):
            asr.resolve_mlx_model("nonsense")

    def test_cache_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"HF_HUB_CACHE": tmp}):
                repo = "mlx-community/whisper-small.en-mlx"
                self.assertFalse(asr.mlx_model_cached(repo))
                os.makedirs(os.path.join(tmp, "models--mlx-community--whisper-small.en-mlx", "snapshots", "abc"))
                self.assertTrue(asr.mlx_model_cached(repo))

    def test_download_without_hf_cli_explains(self):
        with mock.patch.object(asr, "mlx_model_cached", return_value=False), \
                mock.patch.object(asr, "_which", return_value=None):
            with self.assertRaises(asr.ASRUnavailable) as ctx:
                asr.download_mlx_model("tiny.en", Log(quiet=True))
        self.assertIn("first use", str(ctx.exception))

    def test_download_runs_hf_cli(self):
        ok = mock.Mock(returncode=0, stderr="")
        with mock.patch.object(asr, "mlx_model_cached", return_value=False), \
                mock.patch.object(asr, "_which", return_value="/bin/hf"), \
                mock.patch.object(asr.subprocess, "run", return_value=ok) as run:
            repo = asr.download_mlx_model("tiny.en", Log(quiet=True))
        self.assertEqual(run.call_args[0][0], ["/bin/hf", "download", repo])


class TestEngineChoice(unittest.TestCase):
    def test_auto_prefers_whisper_cpp(self):
        b = dict(NONE, **{"whisper.cpp": "/w", "mlx_whisper": "/m"})
        self.assertEqual(asr.pick_engine("auto", b), "whisper-cpp")

    def test_auto_falls_back_to_mlx(self):
        self.assertEqual(asr.pick_engine("auto", dict(NONE, mlx_whisper="/m")), "mlx")

    def test_auto_with_nothing_installed(self):
        self.assertIsNone(asr.pick_engine("auto", NONE))

    def test_explicit_engine_wins(self):
        b = dict(NONE, **{"whisper.cpp": "/w", "mlx_whisper": "/m"})
        self.assertEqual(asr.pick_engine("mlx", b), "mlx")

    def test_asr_ready_per_engine(self):
        b = dict(NONE, mlx_whisper="/m")
        with mock.patch.object(asr, "detect_backends", return_value=b):
            self.assertTrue(asr.asr_ready("mlx"))
            self.assertTrue(asr.asr_ready("auto"))
            self.assertFalse(asr.asr_ready("whisper-cpp"))


class TestParsingAndCommand(unittest.TestCase):
    def test_parse_mlx_json_seconds_to_ms(self):
        segs = parse_mlx_json({"segments": [
            {"start": 0.0, "end": 2.5, "text": " Hello there."},
            {"start": 2.5, "end": 4.0, "text": "   "},
            {"start": 4.0, "end": 6.25, "text": " General Kenobi."},
        ]})
        self.assertEqual([(s.start_ms, s.end_ms, s.text) for s in segs],
                         [(0, 2500, "Hello there."), (4000, 6250, "General Kenobi.")])

    def test_command_flags(self):
        cmd = asr.mlx_command("/m", "r/x", "a.wav", "/o", "pt")
        self.assertEqual(cmd[:3], ["/m", "a.wav", "--model"])
        self.assertIn("--language", cmd)
        self.assertNotIn("--language", asr.mlx_command("/m", "r/x", "a.wav", "/o", "auto"))


class TestCli(unittest.TestCase):
    def test_engine_flag_parses(self):
        args = cli.build_parser().parse_args(["u", "--engine", "mlx"])
        self.assertEqual(args.engine, "mlx")
        self.assertEqual(cli.build_parser().parse_args(["u"]).engine, "auto")

    def test_list_models_exits_zero(self):
        self.assertEqual(cli.main(["--list-models", "-q"]), 0)

    def test_download_model_rejects_whisper_cpp(self):
        self.assertEqual(cli.main(["--download-model", "--engine", "whisper-cpp"]), 2)


if __name__ == "__main__":
    unittest.main()
