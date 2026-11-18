"""Segment model plus the cleanup passes shared by both engines.

Both YouTube's caption tracks and whisper.cpp emit loosely timed, loosely
punctuated lines. Everything downstream (formatters) expects a tidy, ordered,
non-overlapping list of Segments, so all normalisation lives here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

SOUND_TAG_RE = re.compile(r"\[(?:[A-Za-z][A-Za-z '\-]{0,40})\]|\((?:[A-Za-z][A-Za-z '\-]{0,40})\)")
MULTISPACE_RE = re.compile(r"[ \t\u00a0]+")


@dataclass
class Word:
    start_ms: int
    end_ms: int
    text: str
    # Speech recognition confidence, 0..1, when the engine reports one.
    conf: Optional[float] = None


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    text: str
    words: List[Word] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def normalize_text(text: str) -> str:
    """Collapse newlines/hard wraps that YouTube injects mid-sentence."""
    if not text:
        return ""
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\n", " ").replace("\r", " ")
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def clean_segments(segments: List[Segment], drop_sound_tags: bool = False) -> List[Segment]:
    """Normalise text, drop empties, repair timings, remove rolling duplicates."""
    out: List[Segment] = []
    for seg in segments:
        text = normalize_text(seg.text)
        if drop_sound_tags:
            text = normalize_text(SOUND_TAG_RE.sub(" ", text))
        if not text:
            continue
        if not text.strip(" -–—."):
            continue
        out.append(Segment(int(seg.start_ms), int(seg.end_ms), text, list(seg.words)))

    out = _dedupe(out)
    out = _repair_timings(out)
    return out


def _dedupe(segments: List[Segment]) -> List[Segment]:
    """Remove repeated lines.

    YouTube's rolling-window auto captions sometimes re-emit the previous
    window's text. Two shapes occur:
      1. exact duplicate of the previous line -> drop it
      2. current line is the previous line plus new words -> keep the longer one
    """
    out: List[Segment] = []
    for seg in segments:
        key = _norm_key(seg.text)
        if not key:
            continue
        if out:
            prev = out[-1]
            pkey = _norm_key(prev.text)
            if key == pkey:
                # Keep whichever carries more timing information.
                if seg.duration_ms > prev.duration_ms:
                    out[-1] = seg
                continue
            if len(key) > len(pkey) and key.startswith(pkey):
                out[-1] = seg  # grown window: replace with the fuller line
                continue
            if len(pkey) > len(key) and pkey.startswith(key):
                continue  # stale shorter repeat
        out.append(seg)
    return out


def _repair_timings(segments: List[Segment]) -> List[Segment]:
    """Clamp overlapping/zero-length cues so SRT/VTT stay valid.

    YouTube's rolling captions set dDurationMs to the full window lifetime, so
    consecutive cues overlap heavily. A cue must end when the next one starts.
    """
    out: List[Segment] = []
    for i, seg in enumerate(segments):
        start = seg.start_ms
        end = seg.end_ms
        nxt = segments[i + 1].start_ms if i + 1 < len(segments) else None

        if nxt is not None and nxt > start:
            end = min(end, nxt) if end > start else nxt
        if end <= start:
            # Synthesise a plausible duration from the text length.
            est = max(800, min(6000, len(seg.text) * 55))
            end = start + est
            if nxt is not None and nxt > start:
                end = min(end, nxt)
            if end <= start:
                end = start + 400
        out.append(Segment(start, end, seg.text, list(seg.words)))
    return out


def merge_paragraphs(
    segments: List[Segment],
    max_gap_ms: int = 2200,
    max_chars: int = 900,
) -> List[Tuple[Optional[Segment], str]]:
    """Group segments into readable paragraphs.

    Returns (first_segment, text) pairs so the caller can still render a
    leading timestamp for each paragraph. Breaks are biased towards sentence
    ends so paragraphs do not start mid-clause.
    """
    paras: List[Tuple[Optional[Segment], str]] = []
    buf: List[str] = []
    first: Optional[Segment] = None
    prev_end: Optional[int] = None
    chars = 0
    last_was_sentence_end = False

    def flush() -> None:
        nonlocal buf, first, chars, last_was_sentence_end
        if buf:
            paras.append((first, _join_sentences(buf)))
        buf, first, chars, last_was_sentence_end = [], None, 0, False

    for seg in segments:
        gap = (seg.start_ms - prev_end) if prev_end is not None else 0
        if buf:
            long_gap = gap > max_gap_ms
            too_long = chars + len(seg.text) > max_chars
            # Only split on length at a sentence boundary; otherwise keep going
            # a little (up to 1.5x) so we don't cut mid-sentence.
            if long_gap or (too_long and last_was_sentence_end) or (
                too_long and chars > max_chars * 1.5
            ):
                flush()
        if not buf:
            first = seg
        buf.append(seg.text)
        chars += len(seg.text) + 1
        prev_end = seg.end_ms
        last_was_sentence_end = seg.text.rstrip().endswith((".", "!", "?", "…", ":", "♪"))
    flush()
    return paras


def _join_sentences(parts: List[str]) -> str:
    out = ""
    for part in parts:
        if not out:
            out = part
            continue
        if out.endswith(("-", "–")):
            out = out[:-1] + part  # rejoin hyphenated line breaks
        else:
            out = out + " " + part
    return MULTISPACE_RE.sub(" ", out).strip()


def word_count(segments: List[Segment]) -> int:
    return sum(len(s.text.split()) for s in segments)


def strip_sound_tags(segments: List[Segment]) -> List[Segment]:
    """Remove [Music]/(applause) annotations, dropping cues left empty."""
    out: List[Segment] = []
    for seg in segments:
        text = normalize_text(SOUND_TAG_RE.sub(" ", seg.text))
        if text and text.strip(" -–—."):
            out.append(Segment(seg.start_ms, seg.end_ms, text, list(seg.words)))
    return _repair_timings(out)


def quality_report(segments: List[Segment], duration_ms: int) -> List[str]:
    """Cheap sanity check on a caption track.

    Returns a list of problems. An empty list means "looks usable". This is what
    lets the tool auto-escalate to local ASR when YouTube's captions are junk
    (music-only videos, failed ASR, looping output).
    """
    problems: List[str] = []
    if not segments:
        return ["caption track is empty"]

    words = word_count(segments)
    text = " ".join(s.text for s in segments)
    if duration_ms > 0:
        wpm = words / (duration_ms / 60000.0)
        if wpm < 10:
            problems.append("very sparse speech (%.0f words/min)" % wpm)

    tag_chars = sum(len(m.group(0)) for m in SOUND_TAG_RE.finditer(text))
    if text and tag_chars / float(len(text)) > 0.5:
        problems.append("mostly non-speech tags")

    # Length-independent repetition check. A raw type/token ratio falls below
    # 0.1 for any long English text (Zipf), so measure the *mean* ratio over
    # fixed-size windows instead. Normal speech sits around 0.45-0.7; a
    # degenerate ASR loop collapses towards 0.
    toks = [t for t in re.split(r"\s+", text.lower()) if t]
    if len(toks) >= 400:
        window = 400
        ratios = []
        for i in range(0, len(toks) - window + 1, window):
            chunk = toks[i:i + window]
            ratios.append(len(set(chunk)) / float(window))
        if ratios:
            mean_ratio = sum(ratios) / len(ratios)
            if mean_ratio < 0.18:
                problems.append("highly repetitive text (possible ASR loop)")

    return problems
