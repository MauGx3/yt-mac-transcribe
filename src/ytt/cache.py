"""Tiny on-disk cache for caption payloads and metadata.

Two reasons this matters:

* The `timedtext` endpoint throttles aggressively (HTTP 429). Re-running the
  same video — which happens constantly during iteration — should not cost a
  network round trip.
* Transcripts rarely change, so a short TTL is safe and makes batch re-runs
  effectively free.

Deliberately dependency-free and easy to disable (`--no-cache`).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from typing import Any, Optional

DEFAULT_TTL = 7 * 24 * 3600  # one week
# yt-dlp metadata embeds signed timedtext URLs that expire within hours, so
# it must not live as long as the caption payloads themselves.
META_TTL = 3600  # one hour


# Expired entries are deleted at most this often (checked via a marker file).
PRUNE_EVERY = 24 * 3600
_PRUNE_MARKER = ".last-prune"


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(base, "yt-transcribe")
    try:
        # Private to the user: entries hold video metadata and caption URLs.
        os.makedirs(path, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o700)
        # Fail loudly early if the location is not writable.
        fd, probe = tempfile.mkstemp(dir=path, prefix=".write-test-")
        os.close(fd)
        os.remove(probe)
        return path
    except OSError:
        # Never fall back to a fixed, shared path in /tmp: other local users
        # could read it or plant entries and symlinks there. A private
        # per-run directory keeps the run working without a cache that lasts.
        return tempfile.mkdtemp(prefix="yt-transcribe-cache-")


class Cache:
    def __init__(self, enabled: bool = True, ttl: int = DEFAULT_TTL) -> None:
        self.enabled = enabled
        self.ttl = ttl
        self.root = cache_dir() if enabled else ""
        self.hits = 0
        self.misses = 0
        if enabled:
            self.prune_if_due()

    def _path(self, *parts: str) -> str:
        key = hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()[:20]
        return os.path.join(self.root, key)

    def get_text(self, *parts: str, ttl: Optional[int] = None) -> Optional[str]:
        if not self.enabled:
            return None
        path = self._path(*parts) + ".txt"
        limit = self.ttl if ttl is None else min(ttl, self.ttl)
        try:
            if time.time() - os.path.getmtime(path) > limit:
                self.misses += 1
                return None
            with open(path, encoding="utf-8") as fh:
                data = fh.read()
            self.hits += 1
            return data
        except OSError:
            self.misses += 1
            return None

    def set_text(self, value: str, *parts: str) -> None:
        if not self.enabled:
            return
        path = self._path(*parts) + ".txt"
        _atomic_write(path, value)

    def get_json(self, *parts: str, ttl: Optional[int] = None) -> Optional[Any]:
        raw = self.get_text(*parts, ttl=ttl)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def set_json(self, value: Any, *parts: str) -> None:
        self.set_text(json.dumps(value), *parts)

    def clear(self) -> int:
        if not self.enabled or not os.path.isdir(self.root):
            return 0
        n = 0
        for name in os.listdir(self.root):
            try:
                os.remove(os.path.join(self.root, name))
                n += 1
            except OSError:
                pass
        return n

    def prune(self, max_age: Optional[int] = None) -> int:
        """Delete entries older than ``max_age`` (default: the longer of this
        cache's TTL and :data:`DEFAULT_TTL`). Returns how many were removed."""
        if not self.enabled or not os.path.isdir(self.root):
            return 0
        limit = max(self.ttl, DEFAULT_TTL) if max_age is None else max_age
        now = time.time()
        n = 0
        for name in os.listdir(self.root):
            if name == _PRUNE_MARKER:
                continue
            path = os.path.join(self.root, name)
            with contextlib.suppress(OSError):
                if now - os.path.getmtime(path) > limit:
                    os.remove(path)
                    n += 1
        return n

    def prune_if_due(self) -> int:
        """Run :meth:`prune` at most once per :data:`PRUNE_EVERY` seconds."""
        marker = os.path.join(self.root, _PRUNE_MARKER)
        try:
            if time.time() - os.path.getmtime(marker) < PRUNE_EVERY:
                return 0
        except OSError:
            pass
        removed = self.prune()
        with contextlib.suppress(OSError):
            _atomic_write(marker, "")
        return removed

    def size_bytes(self) -> int:
        if not self.enabled or not os.path.isdir(self.root):
            return 0
        total = 0
        for name in os.listdir(self.root):
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(self.root, name))
        return total


def _atomic_write(path: str, value: str) -> None:
    """Write via a unique 0600 temp file, so a planted ``.tmp`` symlink or a
    concurrent run can never redirect or corrupt the write."""
    tmp = ""
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
        os.replace(tmp, path)
    except OSError:
        if tmp:
            with contextlib.suppress(OSError):
                os.remove(tmp)
