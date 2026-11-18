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


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    path = os.path.join(base, "yt-transcribe")
    try:
        os.makedirs(path, exist_ok=True)
        # Fail loudly early if the location is not writable.
        probe = os.path.join(path, ".write-test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return path
    except OSError:
        # Fall back to a temp dir rather than crashing the whole run.
        path = os.path.join(tempfile.gettempdir(), "yt-transcribe-cache")
        os.makedirs(path, exist_ok=True)
        return path


class Cache:
    def __init__(self, enabled: bool = True, ttl: int = DEFAULT_TTL) -> None:
        self.enabled = enabled
        self.ttl = ttl
        self.root = cache_dir() if enabled else ""
        self.hits = 0
        self.misses = 0

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
                return None
            with open(path, "r", encoding="utf-8") as fh:
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

    def size_bytes(self) -> int:
        if not self.enabled or not os.path.isdir(self.root):
            return 0
        total = 0
        for name in os.listdir(self.root):
            try:
                total += os.path.getsize(os.path.join(self.root, name))
            except OSError:
                pass
        return total


def _atomic_write(path: str, value: str) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(value)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
