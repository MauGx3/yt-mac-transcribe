"""Local ASR fallback — used ONLY when a video has no usable captions.

This is the pipeline from the original plan (yt-dlp audio -> ffmpeg 16 kHz mono
-> whisper.cpp + Core ML), demoted to a fallback tier because for the vast
majority of YouTube videos the caption path is ~50x faster and needs no models,
no ffmpeg, and no build step.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

from .captions import parse_whisper_json
from .model import Transcript
from .segments import Segment
from .util import Log

DEFAULT_MODEL = "small.en"
MODEL_HINTS = {
    "tiny.en": "~75 MB, fastest, roughest",
    "base.en": "~150 MB, good for clean English speech",
    "small.en": "~500 MB, best speed/accuracy default",
    "medium.en": "~1.5 GB, slow but strong",
    "large-v3": "~3 GB, best quality, multilingual",
}


class ASRUnavailable(RuntimeError):
    pass


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def detect_backends() -> dict:
    """Report what the ASR tier needs and what is present."""
    return {
        "yt-dlp": _which("yt-dlp"),
        "ffmpeg": _which("ffmpeg"),
        "whisper.cpp": _which("whisper-cli") or _which("whisper"),
        "whisper (openai)": _which("whisper"),
        "mlx_whisper": _which("mlx_whisper"),
    }


def asr_ready() -> bool:
    b = detect_backends()
    return bool(b["yt-dlp"] and b["ffmpeg"] and b["whisper.cpp"])


def transcribe_audio(
    url: str,
    model: str,
    log: Log,
    lang: str = "auto",
    keep_audio: Optional[str] = None,
) -> List[Segment]:
    """Download audio, normalise it, and run whisper.cpp locally."""
    backends = detect_backends()
    missing = [k for k in ("yt-dlp", "ffmpeg", "whisper.cpp") if not backends[k]]
    if missing:
        raise ASRUnavailable(
            "ASR fallback needs %s. Install with:\n"
            "  brew install yt-dlp ffmpeg whisper-cpp\n"
            "then download a model:\n"
            "  whisper-cpp-download-ggml-model %s" % (", ".join(missing), model)
        )

    whisper_bin = backends["whisper.cpp"]
    tmpdir = tempfile.mkdtemp(prefix="ytt-asr-")
    wav = os.path.join(tmpdir, "audio.wav")
    out_prefix = os.path.join(tmpdir, "out")
    try:
        log.info("  [asr] downloading audio…")
        dl = subprocess.run(
            [
                backends["yt-dlp"],
                "-x", "--audio-format", "wav",
                "--postprocessor-args", "-ar 16000 -ac 1",
                "-o", os.path.join(tmpdir, "audio.%(ext)s"),
                "--no-warnings", url,
            ],
            capture_output=True, text=True,
        )
        if dl.returncode != 0:
            raise ASRUnavailable("audio download failed: %s" % dl.stderr.strip()[-300:])

        candidates = [
            os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
            if f.startswith("audio.") and f.endswith(".wav")
        ]
        if not candidates:
            raise ASRUnavailable("yt-dlp produced no wav file")
        if candidates[0] != wav:
            os.rename(candidates[0], wav)

        log.info("  [asr] transcribing with whisper.cpp (%s)…" % model)
        cmd = [whisper_bin, "-m", model, "-f", wav, "-oj", "-of", out_prefix, "-pp"]
        if lang and lang != "auto":
            cmd += ["-l", lang]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ASRUnavailable("whisper.cpp failed: %s" % proc.stderr.strip()[-300:])

        json_path = out_prefix + ".json"
        if not os.path.exists(json_path):
            raise ASRUnavailable("whisper.cpp wrote no JSON output")
        with open(json_path, "r", encoding="utf-8") as fh:
            return parse_whisper_json(json.load(fh))
    finally:
        if keep_audio and os.path.exists(wav):
            shutil.copy(wav, keep_audio)
        shutil.rmtree(tmpdir, ignore_errors=True)


def transcript_from_asr(
    meta: dict, segments: List[Segment], model: str, lang: str = "auto"
) -> Transcript:
    return Transcript(
        video_id=meta.get("id") or "",
        title=meta.get("title") or "",
        url=meta.get("webpage_url") or "",
        segments=segments,
        duration_ms=int((meta.get("duration") or 0) * 1000),
        channel=meta.get("uploader") or "",
        lang=lang if lang != "auto" else (meta.get("language") or ""),
        track_name=model,
        kind="asr",
        engine="asr",
    )
