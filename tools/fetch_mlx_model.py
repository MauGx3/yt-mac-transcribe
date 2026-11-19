#!/usr/bin/env python3
"""Download an MLX model from Hugging Face ahead of first use, with progress.

The macOS app runs this with its private AI runtime's Python, so that the
first enhanced transcript does not stall on a 2 GB download. It also works
from Terminal in any environment that has ``huggingface_hub``:

    python3 tools/fetch_mlx_model.py mlx-community/Qwen2.5-3B-Instruct-4bit

Models go to the normal Hugging Face cache (~/.cache/huggingface, or $HF_HOME),
where MLX-LM and mlx-whisper look for them, so nothing downloads twice.

stdout carries one JSON object per line:

    {"event": "start", "repo": "...", "total": 1712345678}
    {"event": "progress", "done": 123456, "total": 1712345678}
    {"event": "done", "repo": "...", "path": "/Users/.../snapshots/<rev>"}

Errors go to stderr, and the exit status is non-zero.
"""

import argparse
import contextlib
import fnmatch
import json
import os
import sys
import threading

# The files MLX-LM loads (mirrors mlx_lm.utils), plus whisper's weights.npz.
ALLOW_PATTERNS = [
    "*.json",
    "*.safetensors",
    "*.npz",
    "*.py",
    "tokenizer.model",
    "*.tiktoken",
    "tiktoken.model",
    "*.txt",
    "*.jsonl",
    "*.jinja",
]


def emit(event, **fields):
    fields["event"] = event
    sys.stdout.write(json.dumps(fields) + "\n")
    sys.stdout.flush()


def wanted(filename, patterns=ALLOW_PATTERNS):
    """Whether a repo file matches one of the download patterns."""
    return any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)


def total_size(siblings, patterns=ALLOW_PATTERNS):
    """Bytes to download: the sizes of the matching repo files."""
    return sum((getattr(s, "size", None) or 0) for s in siblings if wanted(s.rfilename, patterns))


def directory_size(path):
    """Bytes under ``path``, including partly downloaded files."""
    size = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                size += os.lstat(os.path.join(root, name)).st_size
    return size


def repo_cache_dir(repo):
    """Where huggingface_hub keeps this model's files."""
    from huggingface_hub.constants import HF_HUB_CACHE

    return os.path.join(HF_HUB_CACHE, "models--" + repo.replace("/", "--"))


def report_progress(path, total, stop, interval=0.5):
    """Print the cache folder's growth until ``stop`` is set."""
    start = directory_size(path)
    while not stop.wait(interval):
        done = max(0, directory_size(path) - start)
        emit("progress", done=min(done, total) if total else done, total=total)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "repo", help="Hugging Face repo id, for example mlx-community/Qwen2.5-3B-Instruct-4bit"
    )
    args = parser.parse_args(argv)

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print("fetch_mlx_model: huggingface_hub is not installed", file=sys.stderr)
        return 2

    try:
        info = HfApi().model_info(args.repo, files_metadata=True)
        total = total_size(info.siblings or [])
    except Exception as exc:  # Network or unknown repo: report it plainly.
        print("fetch_mlx_model: could not look up %s: %s" % (args.repo, exc), file=sys.stderr)
        return 1

    emit("start", repo=args.repo, total=total)
    stop = threading.Event()
    watcher = threading.Thread(
        target=report_progress, args=(repo_cache_dir(args.repo), total, stop), daemon=True
    )
    watcher.start()
    try:
        path = snapshot_download(args.repo, allow_patterns=ALLOW_PATTERNS)
    except Exception as exc:
        print("fetch_mlx_model: download failed: %s" % exc, file=sys.stderr)
        return 1
    finally:
        stop.set()
        watcher.join()
    emit("progress", done=total, total=total)
    emit("done", repo=args.repo, path=path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
