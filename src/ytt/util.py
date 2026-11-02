"""Small shared helpers: logging, timing, formatting."""
from __future__ import annotations

import re
import sys
import time


class Log:
    """Tiny stderr logger. Stdout is reserved for transcripts."""

    def __init__(self, quiet: bool = False, verbose: bool = False) -> None:
        self.quiet = quiet
        self.verbose = verbose

    def info(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=sys.stderr, flush=True)

    def debug(self, msg: str) -> None:
        if self.verbose and not self.quiet:
            print("  · " + msg, file=sys.stderr, flush=True)

    def warn(self, msg: str) -> None:
        print("warning: " + msg, file=sys.stderr, flush=True)

    def error(self, msg: str) -> None:
        print("error: " + msg, file=sys.stderr, flush=True)


class Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    @property
    def ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def fmt_duration(ms: int) -> str:
    """1120000 -> '18:40'  (or '1:02:03' past an hour)."""
    s = max(0, int(round(ms / 1000.0)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def fmt_elapsed(ms: int) -> str:
    if ms < 1000:
        return "%d ms" % ms
    if ms < 60000:
        return "%.1f s" % (ms / 1000.0)
    return fmt_duration(ms)


def fmt_int(n: int) -> str:
    return "{:,}".format(n)


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Make a string safe for a POSIX filename, keeping it readable."""
    keep = []
    for ch in name:
        if ch.isalnum() or ch in " -_()[]&,+.'":
            keep.append(ch)
        elif ch in "/\\:|*?\"<>":
            keep.append("-")
        elif ch.isspace():
            keep.append(" ")
    out = "".join(keep).strip()
    out = " ".join(out.split())
    while "  " in out:
        out = out.replace("  ", " ")
    # Tidy punctuation runs left behind by replacements, e.g. "net- - Deep".
    out = re.sub(r"(\s*-\s*)+", " - ", out)
    out = re.sub(r"\s*-\s*$", "", out)
    out = re.sub(r"^\s*-\s*", "", out)
    out = " ".join(out.split()).strip(" .-")
    if len(out) > max_len:
        out = out[:max_len].rstrip(" .-")
        out = re.sub(r"\s*-\s*$", "", out)
    return out or "transcript"
