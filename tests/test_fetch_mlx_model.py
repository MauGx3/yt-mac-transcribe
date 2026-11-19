"""Tests for tools/fetch_mlx_model.py (no network, no huggingface_hub)."""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location(
    "fetch_mlx_model", os.path.join(HERE, "..", "tools", "fetch_mlx_model.py")
)
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


class FetchModelTests(unittest.TestCase):
    def test_wanted_matches_model_files_only(self):
        self.assertTrue(fetch.wanted("model.safetensors"))
        self.assertTrue(fetch.wanted("config.json"))
        self.assertTrue(fetch.wanted("weights.npz"))
        self.assertTrue(fetch.wanted("tokenizer.model"))
        self.assertFalse(fetch.wanted("README.md"))
        self.assertFalse(fetch.wanted(".gitattributes"))
        self.assertFalse(fetch.wanted("pytorch_model.bin"))

    def test_total_size_counts_matching_files_and_tolerates_missing_sizes(self):
        siblings = [
            SimpleNamespace(rfilename="model.safetensors", size=1000),
            SimpleNamespace(rfilename="config.json", size=10),
            SimpleNamespace(rfilename="README.md", size=500),
            SimpleNamespace(rfilename="tokenizer.json", size=None),
        ]
        self.assertEqual(fetch.total_size(siblings), 1010)

    def test_directory_size_includes_nested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "blobs"))
            with open(os.path.join(tmp, "blobs", "a.incomplete"), "wb") as fh:
                fh.write(b"x" * 7)
            with open(os.path.join(tmp, "b"), "wb") as fh:
                fh.write(b"y" * 3)
            self.assertEqual(fetch.directory_size(tmp), 10)
            self.assertEqual(fetch.directory_size(os.path.join(tmp, "missing")), 0)

    def test_emit_writes_one_json_line(self):
        out = io.StringIO()
        with mock.patch.object(fetch.sys, "stdout", out):
            fetch.emit("progress", done=1, total=2)
        self.assertEqual(json.loads(out.getvalue()), {"event": "progress", "done": 1, "total": 2})

    def test_missing_huggingface_hub_exits_with_status_2(self):
        with mock.patch.dict("sys.modules", {"huggingface_hub": None}):
            err = io.StringIO()
            with mock.patch.object(fetch.sys, "stderr", err):
                self.assertEqual(fetch.main(["org/model"]), 2)
        self.assertIn("huggingface_hub", err.getvalue())


if __name__ == "__main__":
    unittest.main()
