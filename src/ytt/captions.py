"""Parsers for YouTube caption payloads (json3 and WebVTT).

json3 is preferred: it is the smallest payload YouTube offers that still keeps
exact timings, and it carries per-word offsets for auto captions.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .segments import Segment, Word, clean_segments, normalize_text

_TS_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})"
)
_TAG_RE = re.compile(r"<[^>]*>")
_VTT_TIMESTAMP_RE = re.compile(r"<\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}>")


def parse_json3(payload: Any) -> List[Segment]:
    """Parse YouTube's json3 timed-text format.

    Handles both caption styles YouTube emits:
      * static cues  -> one non-overlapping line per event
      * rolling windows -> events overlap, `wWinId` set, newline markers
        carry `aAppend: 1`, and segs may carry per-word `tOffsetMs`
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        payload = json.loads(payload)

    segments: List[Segment] = []
    for ev in payload.get("events") or []:
        if ev.get("aAppend"):
            continue  # rolling-window newline marker, not speech
        parts = ev.get("segs") or []
        if not parts:
            continue

        start = int(ev.get("tStartMs") or 0)
        dur = int(ev.get("dDurationMs") or 0)

        words: List[Word] = []
        chunks: List[str] = []
        cursor = 0  # running offset for segs that omit tOffsetMs
        for part in parts:
            text = part.get("utf8") or ""
            if not text:
                continue
            offset = part.get("tOffsetMs")
            if offset is not None:
                cursor = int(offset)
            elif words:
                cursor = words[-1].end_ms - start  # continue after previous word
            w_start = start + max(0, cursor)
            words.append(Word(w_start, w_start, text))
            chunks.append(text)

        text = "".join(chunks)
        if not normalize_text(text):
            continue
        segments.append(Segment(start, start + dur if dur else start, text, words))

    # Fill in word end times from the following word (cheap, monotonic).
    for seg in segments:
        for i, w in enumerate(seg.words):
            if i + 1 < len(seg.words):
                w.end_ms = max(w.start_ms, seg.words[i + 1].start_ms)
            else:
                w.end_ms = max(w.start_ms + 200, seg.end_ms)

    return clean_segments(segments)


def _ts_to_ms(h: str, m: str, s: str, frac: str) -> int:
    ms = int(frac.ljust(3, "0")[:3])
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + ms


def parse_vtt(text: str) -> List[Segment]:
    """Parse WebVTT (used only when json3 is unavailable for a track)."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", "replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    segments: List[Segment] = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        idx = 0
        if "-->" not in lines[0] and len(lines) > 1:
            idx = 1  # skip cue identifier line
        if idx >= len(lines):
            continue
        m = _TS_RE.search(lines[idx])
        if not m:
            continue
        start = _ts_to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _ts_to_ms(m.group(5), m.group(6), m.group(7), m.group(8))
        body = " ".join(lines[idx + 1 :])
        body = _VTT_TIMESTAMP_RE.sub("", body)
        body = _TAG_RE.sub("", body)
        body = normalize_text(body)
        if body:
            segments.append(Segment(start, end, body))

    return clean_segments(segments)


def parse_srt(text: str) -> List[Segment]:
    """Parse SRT (rarely needed, kept for --sub-format flexibility)."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8", "replace")
    text = text.replace("\r\n", "\n")
    segments: List[Segment] = []
    for block in re.split(r"\n{2,}", text):
        m = _TS_RE.search(block)
        if not m:
            continue
        start = _ts_to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _ts_to_ms(m.group(5), m.group(6), m.group(7), m.group(8))
        body = block[m.end() :].strip()
        body = _TAG_RE.sub("", body)
        body = normalize_text(body)
        if body:
            segments.append(Segment(start, end, body))
    return clean_segments(segments)


def parse_whisper_json(payload: Dict[str, Any]) -> List[Segment]:
    """Parse whisper.cpp `-oj` output (offsets are in milliseconds)."""
    segments: List[Segment] = []
    for item in payload.get("transcription") or []:
        offsets = item.get("offsets") or {}
        text = normalize_text(item.get("text") or "")
        if not text:
            continue
        segments.append(Segment(int(offsets.get("from") or 0), int(offsets.get("to") or 0), text))
    return clean_segments(segments)


def parse_mlx_json(payload: Dict[str, Any]) -> List[Segment]:
    """Parse mlx_whisper ``-f json`` output (segment times are in seconds)."""
    segments: List[Segment] = []
    for item in payload.get("segments") or []:
        text = normalize_text(item.get("text") or "")
        if not text:
            continue
        segments.append(
            Segment(
                int(round(float(item.get("start") or 0) * 1000)),
                int(round(float(item.get("end") or 0) * 1000)),
                text,
            )
        )
    return clean_segments(segments)


def detect_format(payload: str) -> str:
    head = payload.lstrip()[:400]
    if head.startswith("WEBVTT"):
        return "vtt"
    if head.startswith("{"):
        return "json3"
    if _TS_RE.search(head) and "-->" in head:
        return "srt"
    return "vtt"


def parse_any(payload: str, fmt: Optional[str] = None) -> List[Segment]:
    fmt = fmt or detect_format(payload)
    if fmt in ("json3", "json"):
        return parse_json3(payload)
    if fmt == "srt":
        return parse_srt(payload)
    return parse_vtt(payload)
