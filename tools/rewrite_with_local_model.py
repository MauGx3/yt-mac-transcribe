#!/usr/bin/env python3
"""Clean up a ytt transcript with a local MLX-LM model on Apple silicon.

This is a runner for ``ytt --rewrite-command``. It reads the rewrite request
JSON on stdin and writes ``{"segments": [{"text": ...}, ...]}`` on stdout,
with exactly one item per input segment. See docs/local-rewriting.md.

Usage:

    pip install mlx-lm
    ytt URL -f txt srt --rewrite-command \\
        python3 tools/rewrite_with_local_model.py --model MODEL

The transcript is rewritten in chunks so that long videos fit in the model's
context. Each chunk also sees a few segments before and after it, as read-only
context. If the model returns a chunk with the wrong number of segments, the
chunk is retried; if it still fails, the runner exits non-zero so ytt keeps
only the original transcript (or, with --keep-original-on-failure, that chunk
keeps its original wording).

When the model can score its output, each changed word whose lowest token
probability is under --unsure-below is reported in an optional ``uncertain``
list on its segment (protocol v2), which ytt turns into "AI unsure" marks.

Diagnostics go to stderr. stdout carries only the response JSON.
"""

import argparse
import difflib
import json
import math
import re
import sys

DEFAULT_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
DEFAULT_CHUNK_SIZE = 40
DEFAULT_CONTEXT = 3
DEFAULT_RETRIES = 1
DEFAULT_UNSURE_BELOW = 0.5

SYSTEM_PROMPT = (
    "You clean up speech transcripts. You fix misheard words, homophones, "
    "grammar, capitalization, and punctuation using the surrounding context. "
    "You never add facts, summarize, translate, or merge or split segments. "
    "You reply with JSON only."
)


class RewriteError(Exception):
    """A chunk could not be rewritten into a valid response."""


def log(message):
    print("rewrite_with_local_model: %s" % message, file=sys.stderr)


def chunk_ranges(count, size):
    """Return (start, end) index pairs covering ``count`` items."""
    size = max(1, size)
    return [(start, min(start + size, count)) for start in range(0, count, size)]


def build_prompt(request, segments, start, end, context):
    """Build the user message for segments[start:end]."""
    before = [s["text"] for s in segments[max(0, start - context) : start]]
    after = [s["text"] for s in segments[end : end + context]]
    lines = [s["text"] for s in segments[start:end]]
    parts = []
    if request.get("title"):
        parts.append("Video title: %s" % request["title"])
    if request.get("language"):
        parts.append("Language: %s (keep this language)" % request["language"])
    if request.get("instructions"):
        parts.append("Task: %s" % request["instructions"])
    if before:
        parts.append(
            "Earlier segments, for context only (do not return them):\n"
            + json.dumps(before, ensure_ascii=False)
        )
    if after:
        parts.append(
            "Later segments, for context only (do not return them):\n"
            + json.dumps(after, ensure_ascii=False)
        )
    parts.append(
        "Segments to clean up (%d items):\n%s" % (len(lines), json.dumps(lines, ensure_ascii=False))
    )
    parts.append(
        "Return a JSON array of exactly %d strings, one per segment above, in "
        "the same order. Keep each segment about the same length so subtitle "
        "timing still fits. If a segment needs no change, return it unchanged." % len(lines)
    )
    return "\n\n".join(parts)


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def parse_response(text, expected):
    """Extract a list of ``expected`` strings from model output."""
    text = _THINK_RE.sub("", text).strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            value = value.get("segments")
        if not isinstance(value, list):
            continue
        items = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("text")
            if not isinstance(item, str):
                break
            items.append(item.strip())
        else:
            if len(items) == expected:
                return items
            raise RewriteError("model returned %d segments; expected %d" % (len(items), expected))
    raise RewriteError("model output did not contain a JSON array of strings")


class ScoredText(str):
    """Model output plus, optionally, the probability of each output character.

    ``char_probs[i]`` is the probability the model gave the token that
    produced character ``i``. Models that cannot score output return plain
    ``str``, and the rewrite then simply reports no uncertain spans.
    """

    def __new__(cls, text, char_probs=None):
        obj = super().__new__(cls, text)
        obj.char_probs = char_probs
        return obj


def locate_items(raw, items):
    """Start offset of each item's text inside the raw model output.

    Items are searched in order, as JSON-escaped text, after any ``</think>``
    block. An item that cannot be found gets ``None`` and no uncertainty.
    """
    cursor = raw.rfind("</think>")
    cursor = 0 if cursor < 0 else cursor + len("</think>")
    offsets = []
    for item in items:
        needle = json.dumps(item, ensure_ascii=False)[1:-1]
        at = raw.find(needle, cursor) if item else -1
        if at >= 0:
            cursor = at + len(needle)
            # JSON escapes shift character positions; only plain text maps 1:1.
            offsets.append(at if needle == item else None)
        else:
            offsets.append(None)
    return offsets


def unsure_spans(original, text, probs, threshold):
    """Character spans of ``text`` the model was unsure about.

    Only words the model changed count: unchanged words were not its
    decision. ``probs`` holds one probability per character of ``text``.
    """
    if not probs or threshold <= 0 or not text:
        return []
    old = original.split()
    words = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    changed = set()
    matcher = difflib.SequenceMatcher(a=old, b=[w[0] for w in words], autojunk=False)
    for op, _, _, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            changed.update(range(j1, j2))
    spans = []
    for i, (_, start, end) in enumerate(words):
        if i not in changed:
            continue
        low = min(probs[start:end], default=1.0)
        if low < threshold:
            spans.append(
                {
                    "start": start,
                    "end": end,
                    "score": round(low, 3),
                    "reason": "low token probability",
                }
            )
    return spans


class MLXModel:
    """Thin wrapper around mlx_lm so tests can swap in a fake model."""

    def __init__(self, name, max_tokens=None):
        try:
            from mlx_lm import load, stream_generate
        except ImportError as exc:
            raise SystemExit(
                "rewrite_with_local_model: mlx-lm is not installed. Install it "
                "on an Apple silicon Mac with: python3 -m pip install mlx-lm"
            ) from exc
        log("loading %s" % name)
        self._stream_generate = stream_generate
        self._model, self._tokenizer = load(name)
        self._max_tokens = max_tokens

    def complete(self, system, user, budget):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False
        )
        pieces, probs = [], []
        for step in self._stream_generate(
            self._model,
            self._tokenizer,
            prompt,
            max_tokens=self._max_tokens or budget,
        ):
            pieces.append(step.text)
            try:
                p = math.exp(float(step.logprobs[step.token]))
            except Exception:  # scoring is advisory; never fail the rewrite
                p = 1.0
            probs.extend([p] * len(step.text))
        return ScoredText("".join(pieces), probs)


def token_budget(lines):
    """Rough output-token allowance for a chunk: input size plus headroom."""
    chars = sum(len(line) for line in lines)
    return chars // 2 + 16 * len(lines) + 256


def chunk_items(raw, lines, items, threshold):
    """Response items for one chunk, with ``uncertain`` spans where scored."""
    probs = getattr(raw, "char_probs", None)
    offsets = locate_items(raw, items) if probs else [None] * len(items)
    out = []
    for line, text, at in zip(lines, items, offsets):
        item = {"text": text}
        if at is not None:
            spans = unsure_spans(line, text, probs[at : at + len(text)], threshold)
            if spans:
                item["uncertain"] = spans
        out.append(item)
    return out


def rewrite(
    request,
    model,
    chunk_size=DEFAULT_CHUNK_SIZE,
    context=DEFAULT_CONTEXT,
    retries=DEFAULT_RETRIES,
    keep_original_on_failure=False,
    unsure_below=DEFAULT_UNSURE_BELOW,
):
    """Return the response payload for a ytt rewrite request."""
    segments = request.get("segments")
    if not isinstance(segments, list):
        raise RewriteError("request has no segments array")
    out = []
    ranges = chunk_ranges(len(segments), chunk_size)
    for n, (start, end) in enumerate(ranges, 1):
        lines = [s["text"] for s in segments[start:end]]
        prompt = build_prompt(request, segments, start, end, context)
        last_error = None
        for attempt in range(retries + 1):
            try:
                raw = model.complete(SYSTEM_PROMPT, prompt, token_budget(lines))
                items = parse_response(raw, len(lines))
                out.extend(chunk_items(raw, lines, items, unsure_below))
                last_error = None
                break
            except RewriteError as exc:
                last_error = exc
                log("chunk %d/%d attempt %d failed: %s" % (n, len(ranges), attempt + 1, exc))
        if last_error is not None:
            if not keep_original_on_failure:
                raise last_error
            log("chunk %d/%d keeps its original text" % (n, len(ranges)))
            out.extend({"text": line} for line in lines)
        else:
            log("chunk %d/%d done" % (n, len(ranges)))
    return {"segments": out}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="ytt rewrite runner that cleans up transcripts with MLX-LM.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="MLX model repo or local path (default: %(default)s)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="segments per model call (default: %(default)s)",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=DEFAULT_CONTEXT,
        help="neighboring segments shown as read-only context (default: %(default)s)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="extra attempts for a chunk with an invalid reply (default: %(default)s)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="fixed generation limit per chunk (default: estimated from the chunk)",
    )
    parser.add_argument(
        "--unsure-below",
        type=float,
        default=DEFAULT_UNSURE_BELOW,
        help="report a changed word as uncertain when its lowest token "
        "probability is under this value; 0 turns it off (default: %(default)s)",
    )
    parser.add_argument(
        "--keep-original-on-failure",
        action="store_true",
        help="keep a chunk's original text instead of failing the whole rewrite",
    )
    return parser.parse_args(argv)


def main(argv=None, model_factory=MLXModel):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        request = json.load(sys.stdin)
    except ValueError as exc:
        log("invalid request JSON: %s" % exc)
        return 2
    if not isinstance(request, dict):
        log("request must be a JSON object")
        return 2
    segments = request.get("segments") or []
    if not segments:
        json.dump({"segments": []}, sys.stdout)
        return 0
    model = model_factory(args.model, max_tokens=args.max_tokens)
    try:
        response = rewrite(
            request,
            model,
            chunk_size=args.chunk_size,
            context=args.context,
            retries=max(0, args.retries),
            keep_original_on_failure=args.keep_original_on_failure,
            unsure_below=args.unsure_below,
        )
    except RewriteError as exc:
        log("rewrite failed: %s" % exc)
        return 1
    json.dump(response, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
