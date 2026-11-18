"""``ytt demo``: benchmark transcription on this Mac and pick models.

The demo needs no YouTube video and no third-party audio. It uses a short
script written for this project (public domain, see ``SAMPLE_SEGMENTS``) and
voices it on the Mac with the built-in ``say`` command, so the clip is made
locally and nothing copyrighted is downloaded or shipped. Because the text is
known exactly, every engine's output can be scored.

Two benchmarks run, each on whatever is installed:

1. Speech to text: every installed engine (whisper.cpp, mlx-whisper) with
   every model that is already downloaded. Reports time, speed as a multiple
   of real time, and word error rate (WER) against the script.
2. LLM cleanup: every MLX-LM model in ``LLM_CATALOG`` that is downloaded is
   given a deliberately garbled copy of the script (homophones, missing
   punctuation and capitals) through the normal ``--rewrite-command`` runner.
   Reports time and how many errors remain.

It then recommends a model for each job, lets you pick, and can save the
choice to ``~/.config/ytt/config.json`` so later ``ytt`` runs use it.

Synthetic speech is cleaner than a real recording, so treat the WER numbers as
a best case. Pass ``--audio FILE --reference TEXT_FILE`` to score your own
recording instead.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from typing import Any, Dict, List, Optional, Sequence

from . import asr as asr_mod
from . import config as config_mod
from .model import Transcript
from .rewriter import rewrite_transcript
from .segments import Segment
from .util import Log

REPORT_VERSION = 1

# Written for yt-transcribe and dedicated to the public domain (CC0). Digits
# and brand names are avoided so that scoring does not depend on how an
# engine writes numbers.
SAMPLE_SEGMENTS = [
    "Welcome to the transcription demo.",
    "This short recording was written for this project and is free to use for any purpose.",
    "It checks how well your Mac turns speech into text, and how quickly it does the work.",
    "Every morning, the baker on Willow Street opens her shop before sunrise and lights the old brick oven.",
    "An hour later, there is a line of neighbors waiting outside, and the smell of fresh bread reaches the corner.",
    "She says the secret is patience: the dough rests overnight, so the flavor has time to grow.",
    "Their favorite loaf is a dark rye with caraway seeds, but the cinnamon rolls sell out first.",
    "On rainy days, fewer people come, so she bakes less and gives the extra to the shelter nearby.",
    "Whether it is sunny or cold, the routine stays the same, and the shop has not missed a morning in years.",
    "Its windows fog up in winter, and children draw small faces in the glass while they wait.",
    "If you can read this sentence clearly in your transcript, the speech engine is doing its job.",
    "Thank you for testing. You can now compare models and choose the one that fits your Mac.",
]

# The same script as a weak transcript might return it: no capitals or
# punctuation, plus twelve homophone and spacing mistakes for the LLM to fix.
NOISY_SEGMENTS = [
    "welcome to the transcription demo",
    "this short recording was written for this project and is free to use for any purpose",
    "it checks how well you're mac turns speech into text and how quickly it does the work",
    "every morning the baker on willow street opens her shop before sunrise and lights the old brick oven",
    "an hour later their is a line of neighbors waiting outside and the smell of fresh bred reaches the corner",
    "she says the secret is patients the dough rests overnight so the flavor has time to grow",
    "there favorite loaf is a dark rye with caraway seeds but the cinnamon rolls sell out first",
    "on rainy days fewer people come so she bakes less and gives the extra to the shelter near by",
    "weather it is sunny or cold the routine stays the same and the shop has not missed a morning in years",
    "it's windows fog up in winter and children draw small faces in the glass while they weight",
    "if you can read this sentence clearly in your transcript the speech engine is doing it's job",
    "thank you for testing you can now compare models and choose the one that fits you're mac",
]

SAMPLE_LICENSE = "Script written for yt-transcribe, public domain (CC0); voiced on this Mac."

# MLX-LM models offered for transcript cleanup. Names were checked against the
# mlx-community organisation on Hugging Face. Sizes are approximate download
# sizes; min_ram_gb is the smallest unified memory where the model runs
# comfortably next to the app.
LLM_CATALOG = [
    {"repo": "mlx-community/Qwen2.5-0.5B-Instruct-4bit", "size_gb": 0.3, "min_ram_gb": 8},
    {"repo": "mlx-community/Llama-3.2-1B-Instruct-4bit", "size_gb": 0.7, "min_ram_gb": 8},
    {"repo": "mlx-community/Qwen2.5-1.5B-Instruct-4bit", "size_gb": 0.9, "min_ram_gb": 8},
    {"repo": "mlx-community/Llama-3.2-3B-Instruct-4bit", "size_gb": 1.8, "min_ram_gb": 8},
    {"repo": "mlx-community/Qwen2.5-3B-Instruct-4bit", "size_gb": 1.7, "min_ram_gb": 8},
    {"repo": "mlx-community/Qwen3-4B-Instruct-2507-4bit", "size_gb": 2.3, "min_ram_gb": 16},
    {"repo": "mlx-community/Qwen2.5-7B-Instruct-4bit", "size_gb": 4.3, "min_ram_gb": 16},
    {"repo": "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit", "size_gb": 4.5, "min_ram_gb": 16},
]
DEFAULT_LLM = "mlx-community/Qwen2.5-3B-Instruct-4bit"

# Models within this WER of the best count as "as accurate"; the fastest of
# those is recommended.
WER_TOLERANCE = 0.02


# --------------------------------------------------------------------------
# Scoring


_WORD_RE = re.compile(r"[a-z0-9']+")


def normalize_words(text: str) -> List[str]:
    """Lowercase words without punctuation. Apostrophes inside words stay,
    so ``it's`` and ``its`` remain different words."""
    text = text.lower().replace("-", " ").replace("’", "'")
    return [w.strip("'") for w in _WORD_RE.findall(text) if w.strip("'")]


def _edit_distance(ref: Sequence[str], hyp: Sequence[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str, strict: bool = False) -> float:
    """Word error rate. ``strict`` also counts case and punctuation."""
    if strict:
        ref, hyp = reference.split(), hypothesis.split()
    else:
        ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / float(len(ref))


# --------------------------------------------------------------------------
# System


def _sysctl(name: str) -> str:
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def system_info() -> Dict[str, Any]:
    ram = _sysctl("hw.memsize")
    try:
        ram_gb = round(int(ram) / (1024**3)) if ram else 0
    except ValueError:
        ram_gb = 0
    if not ram_gb and hasattr(os, "sysconf"):
        try:
            ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3))
        except (ValueError, OSError):
            ram_gb = 0
    return {
        "os": platform.system(),
        "os_version": platform.mac_ver()[0] or platform.release(),
        "machine": platform.machine(),
        "chip": _sysctl("machdep.cpu.brand_string") or platform.processor(),
        "ram_gb": ram_gb,
        "apple_silicon": platform.system() == "Darwin" and platform.machine() == "arm64",
        "python": platform.python_version(),
    }


# --------------------------------------------------------------------------
# Sample audio


def sample_text() -> str:
    return " ".join(SAMPLE_SEGMENTS)


def wav_duration(path: str) -> float:
    with wave.open(path, "rb") as fh:
        return fh.getnframes() / float(fh.getframerate() or 1)


def synthesize_sample(path: str, voice: Optional[str] = None, rate: Optional[int] = None) -> None:
    """Voice the sample script with macOS ``say`` as a 16 kHz mono 16-bit wav."""
    say = shutil.which("say")
    if not say:
        raise asr_mod.ASRUnavailable(
            "the demo voices its sample with macOS 'say', which is not available here. "
            "Pass your own recording with --audio FILE --reference TEXT_FILE."
        )
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(sample_text())
        script = fh.name
    try:
        cmd = [say, "-o", path, "--file-format=WAVE", "--data-format=LEI16@16000", "-f", script]
        if voice:
            cmd += ["-v", voice]
        if rate:
            cmd += ["-r", str(rate)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(path):
            raise asr_mod.ASRUnavailable("say failed: %s" % (proc.stderr.strip()[-300:] or "?"))
    finally:
        os.unlink(script)


def to_wav16k(src: str, dst: str) -> None:
    """Convert any audio file to a 16 kHz mono wav with ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise asr_mod.ASRUnavailable("--audio needs ffmpeg: brew install ffmpeg")
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", src, "-ar", "16000", "-ac", "1", dst],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise asr_mod.ASRUnavailable("ffmpeg failed: %s" % proc.stderr.strip()[-300:])


# --------------------------------------------------------------------------
# Speech-to-text benchmark


def asr_candidates(
    engines: Sequence[str], models: Sequence[str], backends: dict
) -> List[Dict[str, Any]]:
    """Plan one row per (engine, model); rows that cannot run carry a reason."""
    rows = []
    for engine in engines:
        installed = backends.get("mlx_whisper" if engine == "mlx" else "whisper.cpp")
        for model in models:
            row: Dict[str, Any] = {"engine": engine, "model": model, "status": "pending"}
            if not installed:
                row.update(status="skipped", reason="%s is not installed" % engine)
            elif engine == "mlx":
                try:
                    repo = asr_mod.resolve_mlx_model(model)
                except asr_mod.ASRUnavailable as exc:
                    row.update(status="skipped", reason=str(exc))
                else:
                    row["model_ref"] = repo
                    if not asr_mod.mlx_model_cached(repo):
                        row.update(
                            status="not_downloaded",
                            reason="not downloaded: ytt --engine mlx --download-model -m %s" % model,
                        )
            else:
                try:
                    row["model_ref"] = asr_mod.resolve_model(model)
                except asr_mod.ASRUnavailable:
                    row.update(
                        status="not_downloaded",
                        reason="not downloaded: %s" % asr_mod.whisper_cpp_download_command(model),
                    )
            rows.append(row)
    return rows


def run_asr_benchmark(
    wav: str,
    reference: str,
    rows: List[Dict[str, Any]],
    backends: dict,
    log: Log,
    allow_download: bool = False,
) -> List[Dict[str, Any]]:
    duration = wav_duration(wav)
    for row in rows:
        if row["status"] == "not_downloaded" and allow_download and row["engine"] == "mlx":
            row["status"] = "pending"  # mlx_whisper downloads on first use
        if row["status"] != "pending":
            continue
        binary = backends["mlx_whisper" if row["engine"] == "mlx" else "whisper.cpp"]
        log.info("  %s / %s…" % (row["engine"], row["model"]))
        t0 = time.perf_counter()
        try:
            segs = asr_mod.transcribe_wav(
                wav, row["engine"], binary, row["model_ref"], Log(quiet=True), "en"
            )
        except asr_mod.ASRUnavailable as exc:
            row.update(status="failed", reason=str(exc))
            continue
        elapsed = time.perf_counter() - t0
        text = " ".join(s.text for s in segs)
        row.update(
            status="ok",
            seconds=round(elapsed, 2),
            realtime_x=round(duration / elapsed, 1) if elapsed > 0 else None,
            wer=round(wer(reference, text), 4),
            text=text,
        )
    return rows


# --------------------------------------------------------------------------
# LLM cleanup benchmark


def default_runner() -> Optional[List[str]]:
    """Command that runs tools/rewrite_with_local_model.py, if it can be found."""
    env = os.environ.get("YTT_REWRITE_RUNNER")
    candidates = [env] if env else []
    here = os.path.dirname(os.path.abspath(__file__))
    candidates += [
        os.path.join(here, "..", "..", "tools", "rewrite_with_local_model.py"),
        os.path.join(os.getcwd(), "tools", "rewrite_with_local_model.py"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return [sys.executable, os.path.normpath(path)]
    return None


def mlx_lm_available(python: str = sys.executable) -> bool:
    try:
        proc = subprocess.run(
            [python, "-c", "import mlx_lm"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def noisy_transcript() -> Transcript:
    segs = [Segment(i * 4000, i * 4000 + 3800, text) for i, text in enumerate(NOISY_SEGMENTS)]
    return Transcript(
        video_id="demo",
        title="Transcription demo sample",
        url="",
        segments=segs,
        duration_ms=len(segs) * 4000,
        lang="en",
        kind="asr",
        engine="asr",
    )


def llm_candidates(models: Sequence[str], ram_gb: int) -> List[Dict[str, Any]]:
    info = {m["repo"]: m for m in LLM_CATALOG}
    rows = []
    for repo in models:
        meta = info.get(repo, {})
        row: Dict[str, Any] = {
            "model": repo,
            "size_gb": meta.get("size_gb"),
            "min_ram_gb": meta.get("min_ram_gb"),
            "status": "pending",
        }
        if ram_gb and meta.get("min_ram_gb") and ram_gb < meta["min_ram_gb"]:
            row["note"] = "needs about %d GB of memory" % meta["min_ram_gb"]
        if not os.path.isdir(os.path.expanduser(repo)) and not asr_mod.mlx_model_cached(repo):
            row.update(status="not_downloaded", reason="not downloaded (pass --download)")
        rows.append(row)
    return rows


def run_llm_benchmark(
    runner: List[str],
    rows: List[Dict[str, Any]],
    log: Log,
    allow_download: bool = False,
    timeout: int = 900,
) -> List[Dict[str, Any]]:
    reference = sample_text()
    noisy = noisy_transcript()
    before = noisy.plain_text().replace("\n", " ")
    for row in rows:
        if row["status"] == "not_downloaded" and allow_download:
            row["status"] = "pending"
        if row["status"] != "pending":
            continue
        log.info("  %s…" % row["model"])
        t0 = time.perf_counter()
        try:
            out = rewrite_transcript(noisy, list(runner) + ["--model", row["model"]], timeout)
        except subprocess.TimeoutExpired:
            row.update(status="failed", reason="timed out after %d s" % timeout)
            continue
        except (RuntimeError, ValueError, OSError) as exc:
            detail = str(exc).strip().splitlines()
            row.update(status="failed", reason=(detail[-1] if detail else "rewrite failed")[:300])
            continue
        elapsed = time.perf_counter() - t0
        after = " ".join(s.text for s in out.segments)
        row.update(
            status="ok",
            seconds=round(elapsed, 2),
            wer_before=round(wer(reference, before), 4),
            wer=round(wer(reference, after), 4),
            strict_before=round(wer(reference, before, strict=True), 4),
            strict=round(wer(reference, after, strict=True), 4),
            text=after,
        )
    return rows


# --------------------------------------------------------------------------
# Recommendation


def _best(rows: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    ok = [r for r in rows if r.get("status") == "ok" and r.get(key) is not None]
    if not ok:
        return None
    floor = min(r[key] for r in ok)
    close = [r for r in ok if r[key] <= floor + WER_TOLERANCE]
    return min(close, key=lambda r: r["seconds"])


def fallback_asr(ram_gb: int, backends: dict) -> Dict[str, str]:
    engine = asr_mod.pick_engine("auto", backends) or "mlx"
    if ram_gb and ram_gb < 16:
        model = "small.en"
    else:
        model = "large-v3-turbo" if engine == "mlx" else "small.en"
    return {"engine": engine, "model": model}


def fallback_llm(ram_gb: int) -> str:
    if ram_gb and ram_gb < 16:
        return "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
    if ram_gb >= 24:
        return "mlx-community/Qwen2.5-7B-Instruct-4bit"
    return DEFAULT_LLM


def recommend(report: Dict[str, Any], backends: dict) -> Dict[str, Any]:
    ram = report["system"].get("ram_gb") or 0
    rec: Dict[str, Any] = {}
    best_asr = _best(report.get("asr") or [], "wer")
    if best_asr:
        rec["asr"] = {
            "engine": best_asr["engine"],
            "model": best_asr["model"],
            "measured": True,
            "reason": "most accurate on the sample (WER %.1f%%), fastest among ties, %.1fx real time"
            % (best_asr["wer"] * 100, best_asr["realtime_x"] or 0),
        }
    else:
        rec["asr"] = dict(
            fallback_asr(ram, backends),
            measured=False,
            reason="nothing was measured; suggested for %s GB of memory" % (ram or "unknown"),
        )
    llm_rows = [
        r
        for r in report.get("llm") or []
        if r.get("status") != "ok" or r.get("wer", 1) < r.get("wer_before", 0)
    ]
    best_llm = _best(llm_rows, "strict")
    if best_llm:
        rec["llm"] = {
            "model": best_llm["model"],
            "measured": True,
            "reason": "fewest remaining errors (%.1f%% strict, %.1f%% words) in %.1f s"
            % (best_llm["strict"] * 100, best_llm["wer"] * 100, best_llm["seconds"]),
        }
    else:
        rec["llm"] = {
            "model": fallback_llm(ram),
            "measured": False,
            "reason": "nothing was measured; suggested for %s GB of memory" % (ram or "unknown"),
        }
    return rec


# --------------------------------------------------------------------------
# Output


def _pct(value: Optional[float]) -> str:
    return "-" if value is None else "%.1f%%" % (value * 100)


def render_text(report: Dict[str, Any]) -> str:
    s = report["system"]
    lines = [
        "This Mac: %s, %s GB memory, macOS %s"
        % (s.get("chip") or s.get("machine"), s.get("ram_gb") or "?", s.get("os_version")),
        "Sample: %.1f s of speech, %d words (%s)"
        % (report["sample"]["duration_s"], report["sample"]["words"], report["sample"]["source"]),
        "",
        "Speech to text",
        "  %-12s %-16s %9s %10s %7s" % ("engine", "model", "time", "speed", "WER"),
    ]
    for r in report.get("asr") or []:
        if r["status"] == "ok":
            lines.append(
                "  %-12s %-16s %8.1fs %9.1fx %7s"
                % (r["engine"], r["model"], r["seconds"], r["realtime_x"] or 0, _pct(r["wer"]))
            )
        else:
            lines.append("  %-12s %-16s %s" % (r["engine"], r["model"], r.get("reason", r["status"])))
    if not report.get("asr"):
        lines.append("  (skipped)")
    lines += [
        "",
        "LLM cleanup (errors left: words / words+punctuation; garbled input starts at %s / %s)"
        % (_pct(wer(sample_text(), " ".join(NOISY_SEGMENTS))), _pct(wer(sample_text(), " ".join(NOISY_SEGMENTS), True))),
        "  %-46s %8s %7s %7s" % ("model", "time", "words", "strict"),
    ]
    for r in report.get("llm") or []:
        name = r["model"].replace("mlx-community/", "")
        if r["status"] == "ok":
            lines.append(
                "  %-46s %7.1fs %7s %7s" % (name, r["seconds"], _pct(r["wer"]), _pct(r["strict"]))
            )
        else:
            lines.append("  %-46s %s" % (name, r.get("reason", r["status"])))
    if report.get("llm_note"):
        lines.append("  " + report["llm_note"])
    rec = report["recommendation"]
    lines += [
        "",
        "Recommended",
        "  speech to text: --engine %s --model %s" % (rec["asr"]["engine"], rec["asr"]["model"]),
        "    %s" % rec["asr"]["reason"],
        "  LLM cleanup:    %s" % rec["llm"]["model"],
        "    %s" % rec["llm"]["reason"],
    ]
    return "\n".join(lines)


def _ask(prompt: str, options: List[str], default: str) -> str:
    print(prompt, file=sys.stderr)
    for i, opt in enumerate(options, 1):
        mark = "  (recommended)" if opt == default else ""
        print("  %d) %s%s" % (i, opt, mark), file=sys.stderr)
    while True:
        print("Choose 1-%d, Enter for recommended, s to skip: " % len(options), end="", file=sys.stderr)
        sys.stderr.flush()
        answer = sys.stdin.readline().strip().lower()
        if not answer:
            return default
        if answer == "s":
            return ""
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]


def pick_interactively(report: Dict[str, Any]) -> Dict[str, str]:
    rec = report["recommendation"]
    asr_opts = ["%s %s" % (r["engine"], r["model"]) for r in report.get("asr") or [] if r["status"] == "ok"]
    asr_default = "%s %s" % (rec["asr"]["engine"], rec["asr"]["model"])
    if asr_default not in asr_opts:
        asr_opts.insert(0, asr_default)
    llm_opts = [r["model"] for r in report.get("llm") or [] if r["status"] == "ok"]
    llm_opts += [m["repo"] for m in LLM_CATALOG if m["repo"] not in llm_opts]
    chosen: Dict[str, str] = {}
    a = _ask("\nSpeech-to-text model for ytt:", asr_opts, asr_default)
    if a:
        chosen["asr_engine"], chosen["asr_model"] = a.split(" ", 1)
    m = _ask("\nLLM for transcript cleanup:", llm_opts, rec["llm"]["model"])
    if m:
        chosen["llm_model"] = m
    return chosen


# --------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytt demo",
        description="Benchmark speech-to-text and LLM cleanup models on this Mac with a "
        "copyright-free sample, then pick the models ytt should use.",
        epilog="Examples:\n"
        "  ytt demo                      run everything already installed, then pick\n"
        "  ytt demo --download           also download missing MLX models first\n"
        "  ytt demo --asr-only --json    machine-readable report (used by the Mac app)\n"
        "  ytt demo --audio me.m4a --reference me.txt\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    part = p.add_mutually_exclusive_group()
    part.add_argument("--asr-only", action="store_true", help="skip the LLM cleanup benchmark")
    part.add_argument("--llm-only", action="store_true", help="skip the speech-to-text benchmark")
    p.add_argument(
        "--engines",
        nargs="+",
        choices=["whisper-cpp", "mlx"],
        default=["whisper-cpp", "mlx"],
        help="speech engines to try (default: both; missing ones are skipped)",
    )
    p.add_argument(
        "--asr-models",
        nargs="+",
        default=list(asr_mod.MLX_MODELS),
        metavar="MODEL",
        help="speech models to try (default: %(default)s)",
    )
    p.add_argument(
        "--llm-models",
        nargs="+",
        default=[m["repo"] for m in LLM_CATALOG],
        metavar="REPO",
        help="MLX-LM models to try (default: the built-in catalog)",
    )
    p.add_argument(
        "--download",
        action="store_true",
        help="download missing MLX models instead of skipping them (can be several GB)",
    )
    p.add_argument("--audio", metavar="FILE", help="score your own recording instead of the sample")
    p.add_argument("--reference", metavar="FILE", help="exact text of --audio, for scoring")
    p.add_argument("--voice", help="macOS voice for the sample (see: say -v '?')")
    p.add_argument("--timeout", type=int, default=900, help="seconds per LLM model (default: 900)")
    p.add_argument("--json", action="store_true", help="print the report as JSON on stdout")
    p.add_argument("--report", metavar="FILE", help="also write the JSON report to FILE")
    p.add_argument(
        "--save", action="store_true", help="save the recommended models without asking"
    )
    p.add_argument("--no-pick", action="store_true", help="do not ask which models to use")
    p.add_argument("--keep-audio", metavar="FILE", help="copy the sample wav to FILE")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    # REMAINDER so the runner's own flags (such as --model) pass through; this
    # must therefore be the last option on the line.
    p.add_argument(
        "--runner",
        nargs=argparse.REMAINDER,
        metavar="CMD",
        help="rewrite runner command, as for ytt --rewrite-command; must be the LAST "
        "option (default: python tools/rewrite_with_local_model.py)",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.runner is not None and not args.runner:
        parser.error("--runner requires a command")
    if bool(args.audio) != bool(args.reference):
        parser.error("--audio and --reference go together")
    log = Log(quiet=args.quiet)
    backends = asr_mod.detect_backends()
    info = system_info()
    report: Dict[str, Any] = {
        "version": REPORT_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "system": info,
        "engines": {k: bool(v) for k, v in backends.items()},
        "asr": [],
        "llm": [],
    }
    if not info["apple_silicon"]:
        log.warn("this is not an Apple silicon Mac; MLX models will not run here")

    tmpdir = tempfile.mkdtemp(prefix="ytt-demo-")
    try:
        if args.audio:
            with open(args.reference, encoding="utf-8") as fh:
                reference = " ".join(fh.read().split())
            source = os.path.basename(args.audio)
        else:
            reference = sample_text()
            source = SAMPLE_LICENSE
        report["sample"] = {
            "source": source,
            "words": len(normalize_words(reference)),
            "duration_s": 0.0,
        }

        if not args.llm_only:
            wav = os.path.join(tmpdir, "sample.wav")
            try:
                if args.audio:
                    log.info("Converting %s…" % args.audio)
                    to_wav16k(args.audio, wav)
                else:
                    log.info("Voicing the demo script with macOS say…")
                    synthesize_sample(wav, voice=args.voice)
                report["sample"]["duration_s"] = round(wav_duration(wav), 2)
                if args.keep_audio:
                    shutil.copy(wav, args.keep_audio)
                log.info("Speech to text:")
                rows = asr_candidates(args.engines, args.asr_models, backends)
                report["asr"] = run_asr_benchmark(
                    wav, reference, rows, backends, log, allow_download=args.download
                )
            except asr_mod.ASRUnavailable as exc:
                log.error(str(exc))
                report["asr_error"] = str(exc)

        if not args.asr_only:
            runner = args.runner or default_runner()
            rows = llm_candidates(args.llm_models, info["ram_gb"])
            if not runner:
                report["llm_note"] = (
                    "rewrite runner not found; pass --runner python3 path/to/rewrite_with_local_model.py"
                )
                rows = [dict(r, status="skipped", reason="no runner") for r in rows]
            elif not args.runner and not mlx_lm_available(runner[0]):
                report["llm_note"] = "mlx-lm is not installed: %s -m pip install mlx-lm" % runner[0]
                rows = [dict(r, status="skipped", reason="mlx-lm not installed") for r in rows]
            else:
                log.info("LLM cleanup:")
                rows = run_llm_benchmark(
                    runner, rows, log, allow_download=args.download, timeout=args.timeout
                )
            report["llm"] = rows
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    report["recommendation"] = recommend(report, backends)

    chosen: Dict[str, str] = {}
    if args.save:
        rec = report["recommendation"]
        chosen = {"llm_model": rec["llm"]["model"]}
        if not args.llm_only:
            chosen.update(asr_engine=rec["asr"]["engine"], asr_model=rec["asr"]["model"])
    elif not args.json and not args.no_pick and sys.stdin.isatty():
        if not args.quiet:
            print(render_text(report), file=sys.stderr)
        chosen = pick_interactively(report)
        report["_printed"] = True
    if chosen:
        report["saved"] = chosen
        report["saved_to"] = config_mod.save(chosen)

    printed = report.pop("_printed", False)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
    if args.json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    elif not printed:
        print(render_text(report))
    if chosen and not args.json:
        log.info("\nSaved to %s: %s" % (report["saved_to"], ", ".join("%s=%s" % kv for kv in chosen.items())))
    return 0
