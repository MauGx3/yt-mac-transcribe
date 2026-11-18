"""Saved model choices, written by ``ytt demo --save`` (or its picker).

The file is plain JSON at ``~/.config/ytt/config.json`` (``$YTT_CONFIG``
overrides the path). Known keys:

- ``asr_engine``: ``auto``, ``whisper-cpp`` or ``mlx``
- ``asr_model``: a model short name or path for ``--model``
- ``llm_model``: the MLX-LM repo used by ``tools/rewrite_with_local_model.py``

Command-line flags always win over saved values.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

KEYS = ("asr_engine", "asr_model", "llm_model")


def config_path() -> str:
    env = os.environ.get("YTT_CONFIG")
    if env:
        return os.path.expanduser(env)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ytt", "config.json")


def load() -> Dict[str, Any]:
    """Return saved values, or an empty dict when the file is missing or invalid."""
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in KEYS and isinstance(v, str) and v}


def save(values: Dict[str, Any]) -> str:
    """Merge ``values`` into the saved config and return the file path."""
    data = load()
    for key, value in values.items():
        if key in KEYS and isinstance(value, str) and value:
            data[key] = value
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return path
