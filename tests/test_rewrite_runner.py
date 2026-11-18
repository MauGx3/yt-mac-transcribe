"""Tests for tools/rewrite_with_local_model.py using a fake model (no MLX)."""
import importlib.util
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location(
    "rewrite_with_local_model",
    os.path.join(HERE, "..", "tools", "rewrite_with_local_model.py"),
)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class FakeModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user, budget):
        self.prompts.append(user)
        return self.replies.pop(0)


def make_request(texts):
    return {
        "title": "T", "language": "en", "instructions": "fix",
        "segments": [{"index": i, "text": t} for i, t in enumerate(texts)],
    }


class TestParse(unittest.TestCase):
    def test_plain_array(self):
        self.assertEqual(runner.parse_response('["a", "b"]', 2), ["a", "b"])

    def test_fenced_and_chatty(self):
        raw = 'Sure!\n```json\n["a", "b"]\n```'
        self.assertEqual(runner.parse_response(raw, 2), ["a", "b"])

    def test_segments_object_and_think_block(self):
        raw = '<think>["x"]</think>{"segments": [{"text": "a"}]}'
        self.assertEqual(runner.parse_response(raw, 1), ["a"])

    def test_wrong_count_and_garbage(self):
        with self.assertRaises(runner.RewriteError):
            runner.parse_response('["a"]', 2)
        with self.assertRaises(runner.RewriteError):
            runner.parse_response("no json here", 1)


class TestRewrite(unittest.TestCase):
    def test_chunks_and_context(self):
        model = FakeModel(['["A", "B"]', '["C"]'])
        out = runner.rewrite(make_request(["a", "b", "c"]), model, chunk_size=2, context=1)
        self.assertEqual([s["text"] for s in out["segments"]], ["A", "B", "C"])
        self.assertIn("Later segments", model.prompts[0])
        self.assertIn("Earlier segments", model.prompts[1])

    def test_retry_then_success(self):
        model = FakeModel(["oops", '["A"]'])
        out = runner.rewrite(make_request(["a"]), model, retries=1)
        self.assertEqual(out["segments"], [{"text": "A"}])

    def test_failure_raises_or_keeps_original(self):
        with self.assertRaises(runner.RewriteError):
            runner.rewrite(make_request(["a"]), FakeModel(["x", "x"]), retries=1)
        out = runner.rewrite(
            make_request(["a"]), FakeModel(["x", "x"]), retries=1,
            keep_original_on_failure=True,
        )
        self.assertEqual(out["segments"], [{"text": "a"}])


def scored(text, low_word=None, low=0.2):
    """ScoredText where every char has p=0.99, except those of ``low_word``."""
    probs = [0.99] * len(text)
    if low_word:
        at = text.index(low_word)
        for i in range(at, at + len(low_word)):
            probs[i] = low
    return runner.ScoredText(text, probs)


class TestUncertainSpans(unittest.TestCase):
    def test_low_probability_changed_word_is_reported(self):
        model = FakeModel([scored('["They are going home"]', low_word="They")])
        out = runner.rewrite(make_request(["their going home"]), model)
        item = out["segments"][0]
        self.assertEqual(item["text"], "They are going home")
        self.assertEqual(item["uncertain"], [{
            "start": 0, "end": 4, "score": 0.2, "reason": "low token probability"}])

    def test_unchanged_low_probability_word_is_not_reported(self):
        model = FakeModel([scored('["their going home"]', low_word="going")])
        out = runner.rewrite(make_request(["their going home"]), model)
        self.assertEqual(out["segments"], [{"text": "their going home"}])

    def test_confident_edit_and_threshold_zero_report_nothing(self):
        model = FakeModel([scored('["They are going"]')])
        out = runner.rewrite(make_request(["their going"]), model)
        self.assertEqual(out["segments"], [{"text": "They are going"}])
        model = FakeModel([scored('["They are going"]', low_word="They")])
        out = runner.rewrite(make_request(["their going"]), model, unsure_below=0)
        self.assertEqual(out["segments"], [{"text": "They are going"}])

    def test_spans_map_to_the_right_segment_in_a_chunk(self):
        model = FakeModel([scored('["a b", "Their is late"]', low_word="Their")])
        out = runner.rewrite(make_request(["a b", "there is late"]), model)
        self.assertNotIn("uncertain", out["segments"][0])
        self.assertEqual(out["segments"][1]["uncertain"][0]["start"], 0)

    def test_escaped_text_skips_scoring_instead_of_misaligning(self):
        model = FakeModel([scored('["say \\"hi\\" now"]', low_word="hi")])
        out = runner.rewrite(make_request(["say hi now"]), model)
        self.assertNotIn("uncertain", out["segments"][0])

    def test_plain_string_models_still_work(self):
        out = runner.rewrite(make_request(["a"]), FakeModel(['["A"]']))
        self.assertEqual(out["segments"], [{"text": "A"}])


class TestMain(unittest.TestCase):
    def run_main(self, request, replies, argv=()):
        stdout = io.StringIO()
        model = FakeModel(replies)
        with mock.patch("sys.stdin", io.StringIO(json.dumps(request))), \
                mock.patch("sys.stdout", stdout):
            code = runner.main(list(argv), model_factory=lambda name, max_tokens=None: model)
        return code, stdout.getvalue()

    def test_success_emits_only_json(self):
        code, out = self.run_main(make_request(["their going"]), ['["They are going"]'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"segments": [{"text": "They are going"}]})

    def test_empty_segments_skip_model_load(self):
        stdout = io.StringIO()
        def boom(*a, **k):
            raise AssertionError("model should not load")
        with mock.patch("sys.stdin", io.StringIO('{"segments": []}')), \
                mock.patch("sys.stdout", stdout):
            self.assertEqual(runner.main([], model_factory=boom), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"segments": []})

    def test_failure_exit_code(self):
        code, out = self.run_main(make_request(["a"]), ["x", "x"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    def test_bad_request(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(runner.main([], model_factory=None), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
