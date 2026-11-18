"""Optional local context-aware transcript rewriting."""
from __future__ import annotations

import json
import subprocess
from typing import List, Sequence

from .model import Transcript
from .review import clean_uncertain
from .segments import Segment


def _request_payload(transcript: Transcript) -> dict:
    segments = []
    for i, segment in enumerate(transcript.segments):
        segments.append({
            "index": i,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "text": segment.text,
            "previous_text": transcript.segments[i - 1].text if i else "",
            "next_text": transcript.segments[i + 1].text
            if i + 1 < len(transcript.segments) else "",
        })
    return {
        "protocol": 2,
        "title": transcript.title,
        "url": transcript.url,
        "language": transcript.lang,
        "segments": segments,
        "instructions": (
            "Rewrite only wording that improves meaning, grammar, punctuation, "
            "or speaker intent. Preserve the segment count and return JSON with "
            "a segments array containing one text field per segment."
        ),
    }


def rewrite_transcript(
    transcript: Transcript,
    command: Sequence[str],
    timeout: int = 300,
) -> Transcript:
    """Rewrite transcript text with a local model command.

    The command receives a JSON request on stdin and must write JSON to stdout:
    {"segments": [{"text": "..."}, ...]}. A segment may also carry an optional
    ``uncertain`` list of character spans the model was unsure about (protocol
    v2, see docs/local-rewriting.md). Segment timings remain local and
    are copied from the original transcript so subtitle alignment is unchanged.
    """
    if not command:
        raise ValueError("rewrite command is empty")
    proc = subprocess.run(
        list(command),
        input=json.dumps(_request_payload(transcript), ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or "local rewrite command failed"
        raise RuntimeError(detail)
    try:
        response = json.loads(proc.stdout)
        rewritten = response["segments"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("local rewrite command returned invalid JSON") from exc
    if len(rewritten) != len(transcript.segments):
        raise ValueError(
            "local rewrite returned %d segments; expected %d"
            % (len(rewritten), len(transcript.segments))
        )

    segments: List[Segment] = []
    uncertain: List[list] = []
    for original, item in zip(transcript.segments, rewritten):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("each rewritten segment must contain string text")
        text = item["text"].strip()
        segments.append(Segment(
            original.start_ms,
            original.end_ms,
            text,
            list(original.words),
        ))
        # Optional protocol v2 field; old runners simply omit it.
        uncertain.append(clean_uncertain(item.get("uncertain"), text))

    extra = dict(transcript.extra)
    extra["rewritten_from"] = transcript.engine
    extra["uncertain"] = uncertain
    return Transcript(
        video_id=transcript.video_id,
        title=transcript.title,
        url=transcript.url,
        segments=segments,
        duration_ms=transcript.duration_ms,
        channel=transcript.channel,
        lang=transcript.lang,
        track_name=transcript.track_name,
        kind=transcript.kind,
        engine="rewrite",
        fetched_at=transcript.fetched_at,
        warnings=list(transcript.warnings),
        extra=extra,
    )
