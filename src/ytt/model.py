"""Result model shared by the caption and ASR engines."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .segments import Segment, word_count


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
    kind: str = "manual"        # manual | auto | auto-translated | asr
    engine: str = "captions"    # captions | asr
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
