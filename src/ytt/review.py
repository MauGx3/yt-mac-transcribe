"""Diff between an original transcript and its AI-enhanced rewrite.

The review document is what a review screen renders: for every segment, the
original and enhanced text, the word-level changes between them (hunks), and
the spans a rewrite runner reported as uncertain. It is plain JSON so the CLI,
the macOS app, and an HTML report can all read the same file.
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .model import Transcript

REVIEW_VERSION = 1
AI_UNSURE = "ai_unsure"
UNCLEAR_AUDIO = "unclear_audio"

_WORD_RE = re.compile(r"\S+")


def _words(text: str) -> List[Tuple[str, int, int]]:
    """Whitespace-separated words with their character offsets."""
    return [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def clean_uncertain(items: Any, text: str) -> List[Dict[str, Any]]:
    """Validate one segment's ``uncertain`` entries from a rewrite runner.

    Malformed entries are dropped rather than failing the rewrite: uncertainty
    is advisory, and a bad span must never lose the enhanced text.
    """
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if (not isinstance(start, int) or not isinstance(end, int)
                or isinstance(start, bool) or isinstance(end, bool)):
            continue
        start, end = max(0, start), min(len(text), end)
        if start >= end:
            continue
        span: Dict[str, Any] = {"start": start, "end": end, "kind": AI_UNSURE}
        score = item.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            span["score"] = max(0.0, min(1.0, float(score)))
        reason = item.get("reason")
        if isinstance(reason, str) and reason.strip():
            span["reason"] = reason.strip()
        out.append(span)
    return out


def _span_words(spans: Sequence[Dict[str, Any]],
                words: Sequence[Tuple[str, int, int]]) -> List[int]:
    """Indices of ``words`` that overlap any character span."""
    hit = []
    for i, (_, ws, we) in enumerate(words):
        if any(s["start"] < we and ws < s["end"] for s in spans):
            hit.append(i)
    return hit


def diff_segment(original: str, enhanced: str,
                 uncertain: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Word-level diff of one segment, with uncertainty mapped onto hunks."""
    a, b = _words(original), _words(enhanced)
    spans = list(uncertain or [])
    flagged_new = set(_span_words(spans, b))
    hunks: List[Dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(
        a=[w[0] for w in a], b=[w[0] for w in b], autojunk=False
    )
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        hunk: Dict[str, Any] = {
            "op": op,
            "orig": [i1, i2],
            "new": [j1, j2],
            "orig_text": " ".join(w[0] for w in a[i1:i2]),
            "new_text": " ".join(w[0] for w in b[j1:j2]),
        }
        flags = []
        if flagged_new.intersection(range(j1, j2)):
            flags.append(AI_UNSURE)
        elif op == "delete" and (j1 - 1 in flagged_new or j1 in flagged_new):
            # A deletion has no new words; flag it when its neighbours are shaky.
            flags.append(AI_UNSURE)
        hunk["flags"] = flags
        hunks.append(hunk)
    return {
        "original": original,
        "enhanced": enhanced,
        "hunks": hunks,
        "flags": spans,
    }


def build_review(original: Transcript, enhanced: Transcript) -> Dict[str, Any]:
    """Build the review document for a transcript and its rewrite."""
    if len(original.segments) != len(enhanced.segments):
        raise ValueError("original and enhanced transcripts differ in segment count")
    uncertain = enhanced.extra.get("uncertain") or []
    segments = []
    for i, (orig, new) in enumerate(zip(original.segments, enhanced.segments)):
        seg_uncertain = uncertain[i] if i < len(uncertain) else []
        entry = {"index": i, "start_ms": orig.start_ms, "end_ms": orig.end_ms}
        entry.update(diff_segment(orig.text, new.text, seg_uncertain))
        segments.append(entry)
    changed = sum(1 for s in segments if s["hunks"])
    flagged = sum(1 for s in segments if any(h["flags"] for h in s["hunks"]))
    return {
        "version": REVIEW_VERSION,
        "video_id": original.video_id,
        "title": original.title,
        "url": original.url,
        "original_engine": original.engine,
        "stats": {
            "segments": len(segments),
            "changed": changed,
            "flagged": flagged,
            "has_confidence": bool(uncertain),
        },
        "segments": segments,
    }


def render_review(review: Dict[str, Any]) -> str:
    return json.dumps(review, ensure_ascii=False, indent=2) + "\n"


def apply_decisions(review: Dict[str, Any],
                    rejected: Optional[Dict[int, Sequence[int]]] = None) -> List[str]:
    """Final text per segment after the user's decisions.

    ``rejected`` maps a segment index to the hunk indexes the user rejected
    (rejecting keeps the original wording). Every other change is accepted.
    """
    rejected = rejected or {}
    out: List[str] = []
    for seg in review["segments"]:
        refused = set(rejected.get(seg["index"], ()))
        if not refused:
            out.append(seg["enhanced"])
            continue
        a, b = seg["original"].split(), seg["enhanced"].split()
        words: List[str] = []
        b_pos = 0
        for h, hunk in enumerate(seg["hunks"]):
            i1, i2 = hunk["orig"]
            j1, j2 = hunk["new"]
            words.extend(b[b_pos:j1])  # unchanged words match on both sides
            words.extend(a[i1:i2] if h in refused else b[j1:j2])
            b_pos = j2
        words.extend(b[b_pos:])
        out.append(" ".join(words))
    return out
