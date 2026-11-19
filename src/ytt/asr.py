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

from .captions import parse_mlx_json, parse_whisper_json
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


ENGINES = ("auto", "whisper-cpp", "mlx")

# Short model names -> mlx-community Hugging Face repos (names checked against
# the mlx-community "whisper" collection; medium.en only ships quantized).
MLX_MODELS = {
    "tiny.en": "mlx-community/whisper-tiny.en-mlx",
    "base.en": "mlx-community/whisper-base.en-mlx",
    "small.en": "mlx-community/whisper-small.en-mlx",
    "medium.en": "mlx-community/whisper-medium.en-mlx-8bit",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class ASRUnavailable(RuntimeError):
    pass


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def model_search_dirs() -> List[str]:
    """Folders searched for ggml model files, most specific first."""
    dirs = []
    env = os.environ.get("YTT_MODEL_DIR")
    if env:
        dirs.append(env)
    home = os.path.expanduser("~")
    dirs += [
        os.getcwd(),
        os.path.join(os.getcwd(), "models"),
        os.path.join(home, ".cache", "whisper"),
        os.path.join(home, ".cache", "whisper.cpp"),
        "/opt/homebrew/share/whisper-cpp",
        "/opt/homebrew/share/whisper-cpp/models",
        "/usr/local/share/whisper-cpp",
        "/usr/local/share/whisper-cpp/models",
    ]
    return dirs


WHISPER_CPP_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-%s.bin"


def whisper_cpp_download_command(model: str) -> str:
    """Shell command that fetches a ggml model into ~/.cache/whisper.

    Homebrew's whisper-cpp formula ships no download script, so this is a
    plain curl that works anywhere.
    """
    return "mkdir -p ~/.cache/whisper && curl -L -o ~/.cache/whisper/ggml-%s.bin %s" % (
        model,
        WHISPER_CPP_MODEL_URL % model,
    )


def resolve_model(model: str, search_dirs: Optional[List[str]] = None) -> str:
    """Turn a model name like ``small.en`` into a ggml model file path.

    whisper-cli's ``-m`` needs a file, not a name. An existing path is
    returned as-is; otherwise ``<name>`` and ``ggml-<name>.bin`` are looked up
    in :func:`model_search_dirs`.
    """
    expanded = os.path.expanduser(model)
    if os.path.isfile(expanded):
        return expanded
    names = [model, "ggml-%s.bin" % model]
    dirs = search_dirs if search_dirs is not None else model_search_dirs()
    for d in dirs:
        for name in names:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
    raise ASRUnavailable(
        "whisper.cpp model %r not found. Download it with:\n"
        "  %s\n"
        "then pass its path with --model, or put it in one of:\n  %s"
        % (model, whisper_cpp_download_command(model), "\n  ".join(dirs))
    )


def resolve_mlx_model(model: str) -> str:
    """Map a short name to an mlx-community repo; repo ids and paths pass through."""
    if model in MLX_MODELS:
        return MLX_MODELS[model]
    if "/" in model or os.path.isdir(os.path.expanduser(model)):
        return os.path.expanduser(model) if os.path.isdir(os.path.expanduser(model)) else model
    raise ASRUnavailable(
        "unknown MLX model %r. Use one of: %s, a Hugging Face repo id "
        "(org/name), or a local model directory." % (model, ", ".join(MLX_MODELS))
    )


def hf_cache_dir() -> str:
    hub = os.environ.get("HF_HUB_CACHE")
    if hub:
        return hub
    home = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface"
    )
    return os.path.join(home, "hub")


def mlx_model_cached(repo: str) -> bool:
    """True when a Hugging Face snapshot of ``repo`` is already on disk."""
    if os.path.isdir(repo):
        return True
    snaps = os.path.join(hf_cache_dir(), "models--" + repo.replace("/", "--"), "snapshots")
    return os.path.isdir(snaps) and bool(os.listdir(snaps))


def download_mlx_model(model: str, log: Log) -> str:
    """Pre-fetch an MLX model with the Hugging Face CLI. Returns the repo id."""
    repo = resolve_mlx_model(model)
    if mlx_model_cached(repo):
        log.info("  [mlx] %s already downloaded" % repo)
        return repo
    cli = _which("hf") or _which("huggingface-cli")
    if not cli:
        raise ASRUnavailable(
            "no Hugging Face CLI found to download %s. Install it with:\n"
            "  brew install huggingface-cli   (or: pipx install huggingface_hub)\n"
            "or skip this step: mlx_whisper downloads the model on first use." % repo
        )
    log.info("  [mlx] downloading %s…" % repo)
    proc = subprocess.run([cli, "download", repo], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ASRUnavailable("model download failed: %s" % proc.stderr.strip()[-300:])
    return repo


def detect_backends() -> dict:
    """Report what the ASR tier needs and what is present."""
    return {
        "yt-dlp": _which("yt-dlp"),
        "ffmpeg": _which("ffmpeg"),
        # Only whisper.cpp binaries: OpenAI's Python `whisper` CLI takes
        # different flags (-oj/-of/-pp would fail).
        "whisper.cpp": _which("whisper-cli") or _which("whisper-cpp"),
        "whisper (openai)": _which("whisper"),
        "mlx_whisper": _which("mlx_whisper"),
    }


def pick_engine(engine: str = "auto", backends: Optional[dict] = None) -> Optional[str]:
    """Resolve ``auto`` to an installed engine (whisper.cpp first, then MLX).

    Returns None when nothing usable is installed. An explicit engine is
    returned unchanged so the caller can report what is missing.
    """
    if engine not in ENGINES:
        raise ValueError("unknown ASR engine %r" % engine)
    if engine != "auto":
        return engine
    b = backends if backends is not None else detect_backends()
    if b["whisper.cpp"]:
        return "whisper-cpp"
    if b["mlx_whisper"]:
        return "mlx"
    return None


def asr_ready(engine: str = "auto") -> bool:
    b = detect_backends()
    if not (b["yt-dlp"] and b["ffmpeg"]):
        return False
    chosen = pick_engine(engine, b)
    if chosen == "mlx":
        return bool(b["mlx_whisper"])
    return chosen == "whisper-cpp" and bool(b["whisper.cpp"])


def mlx_command(binary: str, repo: str, wav: str, outdir: str, lang: str) -> List[str]:
    cmd = [
        binary,
        wav,
        "--model",
        repo,
        "-f",
        "json",
        "-o",
        outdir,
        "--output-name",
        "out",
        "--verbose",
        "False",
        "--word-timestamps",
        "True",
    ]  # per-word probability for the review screen
    if lang and lang != "auto":
        cmd += ["--language", lang]
    return cmd


def _missing_hint(chosen: str, model: str) -> str:
    if chosen == "mlx":
        return "  brew install yt-dlp ffmpeg\n  pipx install mlx-whisper"
    return (
        "  brew install yt-dlp ffmpeg whisper-cpp\n"
        "then download a model:\n  %s" % whisper_cpp_download_command(model)
    )


def prepare_engine(model: str, engine: str = "auto", backends: Optional[dict] = None):
    """Check the engine binary and resolve the model before any slow work.

    Returns ``(chosen, binary, model_ref)`` where ``model_ref`` is a ggml file
    path for whisper.cpp or a repo id / directory for MLX.
    """
    b = backends if backends is not None else detect_backends()
    chosen = pick_engine(engine, b) or "whisper-cpp"
    binary_key = "mlx_whisper" if chosen == "mlx" else "whisper.cpp"
    if not b.get(binary_key):
        raise ASRUnavailable(
            "%s is not installed. Install with:\n%s" % (binary_key, _missing_hint(chosen, model))
        )
    ref = resolve_mlx_model(model) if chosen == "mlx" else resolve_model(model)
    return chosen, b[binary_key], ref


def transcribe_wav(
    wav: str,
    chosen: str,
    binary: str,
    model_ref: str,
    log: Log,
    lang: str = "auto",
) -> List[Segment]:
    """Run a prepared engine (see :func:`prepare_engine`) on a 16 kHz mono wav."""
    tmpdir = tempfile.mkdtemp(prefix="ytt-asr-run-")
    try:
        if chosen == "mlx":
            if not mlx_model_cached(model_ref):
                log.info("  [asr] first use: mlx_whisper will download %s" % model_ref)
            log.info("  [asr] transcribing with mlx-whisper (%s)…" % model_ref)
            cmd = mlx_command(binary, model_ref, wav, tmpdir, lang)
            label, json_path = "mlx_whisper", os.path.join(tmpdir, "out.json")
            parse = parse_mlx_json
        else:
            out_prefix = os.path.join(tmpdir, "out")
            log.info("  [asr] transcribing with whisper.cpp (%s)…" % os.path.basename(model_ref))
            cmd = [binary, "-m", model_ref, "-f", wav, "-ojf", "-of", out_prefix, "-pp"]
            if lang and lang != "auto":
                cmd += ["-l", lang]
            label, json_path = "whisper.cpp", out_prefix + ".json"
            parse = parse_whisper_json
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ASRUnavailable("%s failed: %s" % (label, proc.stderr.strip()[-300:]))
        if not os.path.exists(json_path):
            raise ASRUnavailable("%s wrote no JSON output" % label)
        with open(json_path, encoding="utf-8") as fh:
            return parse(json.load(fh))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def transcribe_audio(
    url: str,
    model: str,
    log: Log,
    lang: str = "auto",
    keep_audio: Optional[str] = None,
    engine: str = "auto",
) -> List[Segment]:
    """Download audio, normalise it, and run a local Whisper engine."""
    backends = detect_backends()
    chosen = pick_engine(engine, backends) or "whisper-cpp"
    binary_key = "mlx_whisper" if chosen == "mlx" else "whisper.cpp"
    missing = [k for k in ("yt-dlp", "ffmpeg", binary_key) if not backends[k]]
    if missing:
        raise ASRUnavailable(
            "ASR fallback needs %s. Install with:\n%s"
            % (", ".join(missing), _missing_hint(chosen, model))
        )

    # Resolve before downloading audio so a bad model fails fast.
    chosen, binary, model_ref = prepare_engine(model, chosen, backends)
    tmpdir = tempfile.mkdtemp(prefix="ytt-asr-")
    wav = os.path.join(tmpdir, "audio.wav")
    try:
        log.info("  [asr] downloading audio…")
        dl = subprocess.run(
            [
                backends["yt-dlp"],
                "-x",
                "--audio-format",
                "wav",
                "--postprocessor-args",
                "-ar 16000 -ac 1",
                "-o",
                os.path.join(tmpdir, "audio.%(ext)s"),
                "--no-warnings",
                "--",  # a URL must never be parsed as a yt-dlp option
                url,
            ],
            capture_output=True,
            text=True,
        )
        if dl.returncode != 0:
            raise ASRUnavailable("audio download failed: %s" % dl.stderr.strip()[-300:])

        candidates = [
            os.path.join(tmpdir, f)
            for f in os.listdir(tmpdir)
            if f.startswith("audio.") and f.endswith(".wav")
        ]
        if not candidates:
            raise ASRUnavailable("yt-dlp produced no wav file")
        if candidates[0] != wav:
            os.rename(candidates[0], wav)

        return transcribe_wav(wav, chosen, binary, model_ref, log, lang)
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
