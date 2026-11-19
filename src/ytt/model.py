"""Result model shared by the caption and ASR engines."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .segments import Segment, Word, word_count


def segments_to_data(segments: List[Segment]) -> List[Dict[str, Any]]:
    """Plain-JSON form of segments and their words (with confidences)."""
    out = []
    for seg in segments:
        item: Dict[str, Any] = {"start_ms": seg.start_ms, "end_ms": seg.end_ms, "text": seg.text}
        if seg.words:
            item["words"] = [
                {"start_ms": w.start_ms, "end_ms": w.end_ms, "text": w.text, "conf": w.conf}
                for w in seg.words
            ]
        out.append(item)
    return out


def _opt_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def segments_from_data(items: Any) -> List[Segment]:
    """Inverse of :func:`segments_to_data`; also reads ``ytt -f json`` output."""
    if not isinstance(items, list):
        raise ValueError("segments must be a list")
    segments = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("each segment needs a text field")
        words = [
            Word(
                int(w.get("start_ms") or 0),
                int(w.get("end_ms") or 0),
                str(w.get("text") or ""),
                _opt_float(w.get("conf")),
            )
            for w in item.get("words") or []
            if isinstance(w, dict)
        ]
        segments.append(
            Segment(
                int(item.get("start_ms") or 0), int(item.get("end_ms") or 0), item["text"], words
            )
        )
    return segments


@dataclass
class Transcript:
    video_id: str
    title: str
    url: str
    segments: List[Segment]
    duration_ms: int = 0
    channel: str = ""
    lang: str = ""
    track_name: str = ""
    kind: str = "manual"  # manual | auto | auto-translated | asr
    engine: str = "captions"  # captions | asr
    fetched_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    warnings: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return word_count(self.segments)

    @property
    def chars(self) -> int:
        return sum(len(s.text) for s in self.segments)

    def plain_text(self) -> str:
        return "\n".join(s.text for s in self.segments)

    def label(self) -> str:
        bits = [self.engine]
        if self.engine == "captions":
            bits.append(self.kind)
        if self.lang:
            bits.append(self.lang)
        return " · ".join(bits)


def transcript_from_json(data: Any) -> Transcript:
    """Rebuild a :class:`Transcript` from ``ytt -f json`` output."""
    if not isinstance(data, dict):
        raise ValueError("not a ytt transcript JSON file")
    source = data.get("source") or {}
    return Transcript(
        video_id=str(data.get("video_id") or ""),
        title=str(data.get("title") or ""),
        url=str(data.get("url") or ""),
        segments=segments_from_data(data.get("segments")),
        duration_ms=int(data.get("duration_ms") or 0),
        channel=str(data.get("channel") or ""),
        lang=str(data.get("language") or ""),
        track_name=str(source.get("track") or ""),
        kind=str(source.get("kind") or "manual"),
        engine=str(source.get("engine") or "captions"),
        fetched_at=str(data.get("fetched_at") or ""),
        warnings=[str(w) for w in data.get("warnings") or []],
    )
