"""Output writers: txt, srt, vtt, json, md."""
from __future__ import annotations

import json
import textwrap
from typing import Dict, List

from .model import Transcript
from .segments import Segment, merge_paragraphs
from .util import fmt_duration

FORMATS = ("txt", "srt", "vtt", "json", "md")


def _ts_srt(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, milli)


def _ts_vtt(ms: int) -> str:
    return _ts_srt(ms).replace(",", ".")


def _wrap(text: str, width: int = 42, max_lines: int = 2) -> str:
    lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) > max_lines:
        head = lines[: max_lines - 1]
        tail = " ".join(lines[max_lines - 1:])
        lines = head + [textwrap.shorten(tail, width=width, placeholder="…")]
    return "\n".join(lines)


def render_txt(t: Transcript, timestamps: bool = False, paragraphs: bool = True) -> str:
    if paragraphs:
        blocks = merge_paragraphs(t.segments)
        if not timestamps:
            return "\n\n".join(text for _, text in blocks).strip() + "\n"
        out = []
        for seg, text in blocks:
            stamp = fmt_duration(seg.start_ms) if seg else "0:00"
            out.append("[%s] %s" % (stamp, text))
        return "\n\n".join(out).strip() + "\n"

    if not timestamps:
        return t.plain_text().strip() + "\n"
    return "\n".join("[%s] %s" % (fmt_duration(s.start_ms), s.text) for s in t.segments).strip() + "\n"


def render_srt(t: Transcript) -> str:
    out: List[str] = []
    for i, seg in enumerate(t.segments, 1):
        out.append(str(i))
        out.append("%s --> %s" % (_ts_srt(seg.start_ms), _ts_srt(seg.end_ms)))
        out.append(_wrap(seg.text))
        out.append("")
    return "\n".join(out).strip() + "\n"


def render_vtt(t: Transcript) -> str:
    out: List[str] = ["WEBVTT", ""]
    for seg in t.segments:
        out.append("%s --> %s" % (_ts_vtt(seg.start_ms), _ts_vtt(seg.end_ms)))
        out.append(_wrap(seg.text))
        out.append("")
    return "\n".join(out).strip() + "\n"


def render_json(t: Transcript, include_words: bool = True) -> str:
    payload = {
        "video_id": t.video_id,
        "title": t.title,
        "url": t.url,
        "channel": t.channel,
        "duration_ms": t.duration_ms,
        "language": t.lang,
        "source": {
            "engine": t.engine,
            "kind": t.kind,
            "track": t.track_name,
        },
        "fetched_at": t.fetched_at,
        "warnings": t.warnings,
        "stats": {"segments": len(t.segments), "words": t.words, "chars": t.chars},
        "segments": [
            _seg_json(s, include_words) for s in t.segments
        ],
    }
    # [AI-GENERATED] Rewrite companions record which engine produced the input.
    if t.extra.get("rewritten_from"):
        payload["source"]["rewritten_from"] = t.extra["rewritten_from"]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _seg_json(seg: Segment, include_words: bool) -> Dict:
    data = {
        "start_ms": seg.start_ms,
        "end_ms": seg.end_ms,
        "text": seg.text,
    }
    if include_words and seg.words:
        data["words"] = [
            {"start_ms": w.start_ms, "end_ms": w.end_ms, "text": w.text} for w in seg.words
        ]
    return data


def render_md(t: Transcript, timestamps: bool = True) -> str:
    lines: List[str] = ["# %s" % (t.title or t.video_id), ""]
    meta = [
        ("Source", t.url),
        ("Channel", t.channel or "—"),
        ("Duration", fmt_duration(t.duration_ms) if t.duration_ms else "—"),
        ("Transcript", t.label()),
        ("Segments", f"{len(t.segments):,}"),
    ]
    if t.extra.get("rewritten_from"):  # [AI-GENERATED] rewrite provenance
        meta.insert(4, ("Rewritten from", t.extra["rewritten_from"]))
    for key, val in meta:
        lines.append("- **%s:** %s" % (key, val))
    lines.append("")
    if t.warnings:
        lines.append("> " + "  \n> ".join(t.warnings))
        lines.append("")
    lines.append("---")
    lines.append("")
    for seg, text in merge_paragraphs(t.segments):
        if timestamps and seg is not None:
            lines.append("**%s**  %s" % (fmt_duration(seg.start_ms), text))
        else:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render(t: Transcript, fmt: str, timestamps: bool = False) -> str:
    if fmt == "srt":
        return render_srt(t)
    if fmt == "vtt":
        return render_vtt(t)
    if fmt == "json":
        return render_json(t)
    if fmt == "md":
        return render_md(t, timestamps=timestamps)
    return render_txt(t, timestamps=timestamps)
