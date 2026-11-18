"""Tests for `ytt demo` (src/ytt/demo.py). No engines or models needed."""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import wave
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import asr, cli, demo
from ytt import config as config_mod
from ytt.segments import Segment
from ytt.util import Log

HERE = os.path.dirname(__file__)
NONE = dict.fromkeys(("yt-dlp", "ffmpeg", "whisper.cpp", "whisper (openai)", "mlx_whisper"))


def write_silence(path, seconds=2.0):
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(b"\0\0" * int(16000 * seconds))


def fake_runner(tmpdir, segments):
    """A rewrite runner that always answers with ``segments``."""
    path = os.path.join(tmpdir, "runner.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "import json, sys\n"
            "json.load(sys.stdin)\n"
            "json.dump({'segments': [{'text': t} for t in %r]}, sys.stdout)\n" % (segments,)
        )
    return [sys.executable, path]


class TestScoring(unittest.TestCase):
    def test_wer_identical_and_different(self):
        self.assertEqual(demo.wer("Hello, world.", "hello world"), 0.0)
        self.assertAlmostEqual(demo.wer("a b c d", "a x c"), 0.5)
        self.assertEqual(demo.wer("", ""), 0.0)

    def test_its_and_it_s_stay_different(self):
        self.assertEqual(demo.normalize_words("It's its"), ["it's", "its"])
        self.assertGreater(demo.wer("its job", "it's job"), 0)

    def test_strict_counts_case_and_punctuation(self):
        self.assertEqual(demo.wer("Hello, world.", "hello world"), 0.0)
        self.assertEqual(demo.wer("Hello, world.", "hello world", strict=True), 1.0)

    def test_sample_and_noisy_line_up(self):
        self.assertEqual(len(demo.SAMPLE_SEGMENTS), len(demo.NOISY_SEGMENTS))
        for clean, noisy in zip(demo.SAMPLE_SEGMENTS, demo.NOISY_SEGMENTS):
            self.assertLess(demo.wer(clean, noisy), 0.35, noisy)
        self.assertGreater(demo.wer(demo.sample_text(), " ".join(demo.NOISY_SEGMENTS)), 0.05)

    def test_sample_has_no_digits(self):
        self.assertFalse(any(ch.isdigit() for ch in demo.sample_text()))


class TestSample(unittest.TestCase):
    def test_say_missing_explains_alternative(self):
        with mock.patch.object(demo.shutil, "which", return_value=None), self.assertRaises(
            asr.ASRUnavailable
        ) as ctx:
            demo.synthesize_sample("/tmp/x.wav")
        self.assertIn("--audio", str(ctx.exception))

    def test_say_command_line(self):
        def fake_run(cmd, **kw):
            write_silence(cmd[cmd.index("-o") + 1])
            return mock.Mock(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            demo.shutil, "which", return_value="/usr/bin/say"
        ), mock.patch.object(demo.subprocess, "run", side_effect=fake_run) as run:
            out = os.path.join(tmp, "s.wav")
            demo.synthesize_sample(out, voice="Samantha")
            self.assertAlmostEqual(demo.wav_duration(out), 2.0)
        cmd = run.call_args[0][0]
        self.assertIn("--data-format=LEI16@16000", cmd)
        self.assertIn("--file-format=WAVE", cmd)
        self.assertEqual(cmd[cmd.index("-v") + 1], "Samantha")


class TestASRBenchmark(unittest.TestCase):
    def test_candidates_report_missing_pieces(self):
        b = dict(NONE, mlx_whisper="/m")
        with mock.patch.object(
            asr, "mlx_model_cached", side_effect=lambda r: "tiny" in r
        ), mock.patch.object(asr, "resolve_model", side_effect=asr.ASRUnavailable("x")):
            rows = demo.asr_candidates(["whisper-cpp", "mlx"], ["tiny.en", "small.en"], b)
        by = {(r["engine"], r["model"]): r["status"] for r in rows}
        self.assertEqual(by[("whisper-cpp", "tiny.en")], "skipped")
        self.assertEqual(by[("mlx", "tiny.en")], "pending")
        self.assertEqual(by[("mlx", "small.en")], "not_downloaded")

    def test_run_scores_and_times(self):
        rows = [
            {"engine": "mlx", "model": "tiny.en", "model_ref": "r", "status": "pending"},
            {"engine": "mlx", "model": "small.en", "model_ref": "r", "status": "not_downloaded"},
        ]
        segs = [Segment(0, 1000, demo.sample_text())]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            asr, "transcribe_wav", return_value=segs
        ):
            wav = os.path.join(tmp, "a.wav")
            write_silence(wav)
            out = demo.run_asr_benchmark(
                wav, demo.sample_text(), rows, dict(NONE, mlx_whisper="/m"), Log(quiet=True)
            )
        self.assertEqual(out[0]["status"], "ok")
        self.assertEqual(out[0]["wer"], 0.0)
        self.assertGreater(out[0]["realtime_x"], 0)
        self.assertEqual(out[1]["status"], "not_downloaded")


class TestLLMBenchmark(unittest.TestCase):
    def test_fake_runner_fixes_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = fake_runner(tmp, demo.SAMPLE_SEGMENTS)
            rows = [{"model": "m/perfect", "status": "pending"}]
            out = demo.run_llm_benchmark(runner, rows, Log(quiet=True))
        self.assertEqual(out[0]["status"], "ok")
        self.assertEqual(out[0]["strict"], 0.0)
        self.assertGreater(out[0]["strict_before"], 0.2)

    def test_wrong_segment_count_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = fake_runner(tmp, ["only one"])
            out = demo.run_llm_benchmark(runner, [{"model": "m", "status": "pending"}], Log(True))
        self.assertEqual(out[0]["status"], "failed")
        self.assertIn("segments", out[0]["reason"])

    def test_candidates_note_memory(self):
        with mock.patch.object(asr, "mlx_model_cached", return_value=True):
            rows = demo.llm_candidates(["mlx-community/Qwen2.5-7B-Instruct-4bit"], 8)
        self.assertEqual(rows[0]["status"], "pending")
        self.assertIn("16 GB", rows[0]["note"])


class TestRecommend(unittest.TestCase):
    def report(self, asr_rows=(), llm_rows=(), ram=16):
        return {"system": {"ram_gb": ram}, "asr": list(asr_rows), "llm": list(llm_rows)}

    def test_fastest_among_equally_accurate(self):
        rows = [
            {
                "engine": "mlx",
                "model": "large-v3",
                "status": "ok",
                "wer": 0.01,
                "seconds": 9,
                "realtime_x": 3,
            },
            {
                "engine": "mlx",
                "model": "small.en",
                "status": "ok",
                "wer": 0.02,
                "seconds": 2,
                "realtime_x": 15,
            },
            {
                "engine": "mlx",
                "model": "tiny.en",
                "status": "ok",
                "wer": 0.10,
                "seconds": 1,
                "realtime_x": 30,
            },
        ]
        rec = demo.recommend(self.report(rows), NONE)
        self.assertEqual(rec["asr"]["model"], "small.en")
        self.assertTrue(rec["asr"]["measured"])

    def test_llm_that_makes_things_worse_is_ignored(self):
        llm = [
            {
                "model": "bad",
                "status": "ok",
                "wer_before": 0.1,
                "wer": 0.2,
                "strict": 0.0,
                "seconds": 1,
            },
            {
                "model": "good",
                "status": "ok",
                "wer_before": 0.1,
                "wer": 0.0,
                "strict": 0.05,
                "seconds": 5,
            },
        ]
        self.assertEqual(demo.recommend(self.report(llm_rows=llm), NONE)["llm"]["model"], "good")

    def test_fallback_by_memory(self):
        self.assertIn("1.5B", demo.recommend(self.report(ram=8), NONE)["llm"]["model"])
        self.assertEqual(
            demo.recommend(self.report(ram=16), NONE)["llm"]["model"], demo.DEFAULT_LLM
        )
        self.assertIn("7B", demo.recommend(self.report(ram=32), NONE)["llm"]["model"])
        self.assertFalse(demo.recommend(self.report(), NONE)["asr"]["measured"])

    def test_catalog_contains_default(self):
        self.assertIn(demo.DEFAULT_LLM, [m["repo"] for m in demo.LLM_CATALOG])


class TestMainAndConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = os.path.join(self.tmp.name, "cfg", "config.json")
        patcher = mock.patch.dict(os.environ, {"YTT_CONFIG": self.cfg})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_demo(self, argv):
        out = io.StringIO()
        b = dict(NONE, mlx_whisper="/m")
        with mock.patch.object(asr, "detect_backends", return_value=b), mock.patch.object(
            demo, "synthesize_sample", side_effect=lambda p, voice=None: write_silence(p)
        ), mock.patch.object(asr, "mlx_model_cached", return_value=True), mock.patch.object(
            asr, "transcribe_wav", return_value=[Segment(0, 1, demo.sample_text())]
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["demo", *argv])
        return code, out.getvalue()

    def test_json_report_and_save(self):
        runner = fake_runner(self.tmp.name, demo.SAMPLE_SEGMENTS)
        code, out = self.run_demo(
            ["--json", "--save", "--engines", "mlx", "--asr-models", "tiny.en",
             "--llm-models", "mlx-community/Qwen2.5-0.5B-Instruct-4bit", "--runner", *runner]
        )  # fmt: skip
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["asr"][0]["status"], "ok")
        self.assertEqual(report["llm"][0]["status"], "ok")
        self.assertEqual(report["recommendation"]["asr"]["model"], "tiny.en")
        self.assertEqual(
            config_mod.load(),
            {
                "asr_engine": "mlx",
                "asr_model": "tiny.en",
                "llm_model": "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
            },
        )
        # The saved choice becomes ytt's default; flags still win.
        args = cli.build_parser().parse_args(["URL"])
        self.assertEqual((args.engine, args.model), ("mlx", "tiny.en"))
        args = cli.build_parser().parse_args(["URL", "--model", "base.en"])
        self.assertEqual(args.model, "base.en")

    def test_text_report_without_saving(self):
        code, out = self.run_demo(["--asr-only", "--no-pick", "--asr-models", "tiny.en"])
        self.assertEqual(code, 0)
        self.assertIn("Recommended", out)
        self.assertFalse(os.path.exists(self.cfg))

    def test_audio_needs_reference(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            demo.main(["--audio", "x.wav"])

    def test_bad_config_is_ignored(self):
        os.makedirs(os.path.dirname(self.cfg))
        with open(self.cfg, "w") as fh:
            fh.write("not json")
        self.assertEqual(config_mod.load(), {})
        args = cli.build_parser().parse_args(["URL"])
        self.assertEqual(args.engine, "auto")

    def test_rewrite_runner_reads_saved_model(self):
        spec = importlib.util.spec_from_file_location(
            "rw", os.path.join(HERE, "..", "tools", "rewrite_with_local_model.py")
        )
        rw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rw)
        self.assertIsNone(rw.saved_model())
        config_mod.save({"llm_model": "me/model"})
        self.assertEqual(rw.parse_args([]).model, "me/model")
        with mock.patch.dict(os.environ, {"YTT_LLM_MODEL": "env/model"}):
            self.assertEqual(rw.parse_args([]).model, "env/model")


if __name__ == "__main__":
    unittest.main()
