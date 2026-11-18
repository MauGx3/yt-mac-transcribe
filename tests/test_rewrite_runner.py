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
