"""Cancelling ytt must stop its child processes and delete temp files."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")


@unittest.skipUnless(hasattr(os, "killpg"), "POSIX only")
class CancelTests(unittest.TestCase):
    def test_sigterm_to_group_stops_children_and_runs_finally(self):
        marker_dir = tempfile.mkdtemp()
        script = textwrap.dedent(
            """
            import os, shutil, subprocess, sys, tempfile
            sys.path.insert(0, %r)
            from ytt import cli
            cli.install_signal_handling({"YTT_PROCESS_GROUP": "1"})
            tmp = tempfile.mkdtemp(dir=%r)
            try:
                print(os.getpgid(0) == os.getpid(), flush=True)
                subprocess.run(["sleep", "30"])
            finally:
                shutil.rmtree(tmp)
            """
        ) % (SRC, marker_dir)
        proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout.readline().strip(), "True")
        time.sleep(0.3)
        start = time.time()
        os.killpg(proc.pid, signal.SIGTERM)
        code = proc.wait(timeout=10)
        self.assertLess(time.time() - start, 5)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(os.listdir(marker_dir), [])
        os.rmdir(marker_dir)


if __name__ == "__main__":
    unittest.main()
