"""Exit-code tests for main(). No network."""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import cli  # noqa: E402


class TestExitCodes(unittest.TestCase):
    def run_main(self, argv, result):
        with mock.patch.object(cli, "YouTube"), \
                mock.patch.object(cli, "process_one", return_value=result), \
                contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            return cli.main(argv + ["--no-cache"])

    def test_list_tracks_exits_zero(self):
        self.assertEqual(self.run_main(["https://youtu.be/x", "--list-tracks"], (None, [])), 0)

    def test_no_transcript_still_exits_one(self):
        self.assertEqual(self.run_main(["https://youtu.be/x"], (None, [])), 1)


if __name__ == "__main__":
    unittest.main()
