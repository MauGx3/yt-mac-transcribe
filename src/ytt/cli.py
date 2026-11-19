"""Command-line interface for yt-transcribe."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import time
from typing import List, Optional, Tuple

from . import __version__
from . import asr as asr_mod
from . import config as config_mod
from .cache import DEFAULT_TTL, Cache
from .formatter import FORMATS, render
from .model import Transcript, segments_from_data, segments_to_data, transcript_from_json
from .report import render_report
from .review import build_review, render_review
from .rewriter import rewrite_transcript
from .segments import quality_report
from .util import Log, Timer, fmt_duration, fmt_elapsed, fmt_int, sanitize_filename
from .youtube import InvalidURL, RateLimited, VideoError, YouTube, YtDlpMissing, validate_url

DEFAULT_LANGS = ["en"]
# Exit code when a batch or playlist run wrote some transcripts but not all.
EXIT_PARTIAL = 3


def build_parser() -> argparse.ArgumentParser:
    saved = config_mod.load()
    saved_engine = saved.get("asr_engine")
    if saved_engine not in asr_mod.ENGINES:
        saved_engine = "auto"
    p = argparse.ArgumentParser(
        prog="ytt",
        description="YouTube transcripts in seconds — uses YouTube's own caption "
        "tracks by default, with local whisper.cpp as a fallback.",
        epilog="Examples:\n"
        "  ytt https://youtu.be/aircAruvnKk\n"
        "  ytt <url> -f srt vtt json -o ~/Downloads\n"
        "  ytt <url> --langs pt,en --asr auto\n"
        "  ytt --batch urls.txt -o transcripts/\n"
        "  ytt demo        benchmark models on this Mac and pick defaults\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", help="YouTube video or playlist URLs")
    p.add_argument(
        "-f",
        "--format",
        nargs="+",
        default=["txt"],
        choices=list(FORMATS),
        metavar="FMT",
        help="output formats: %s (default: txt)" % ", ".join(FORMATS),
    )
    p.add_argument("-o", "--out", default=".", help="output directory or file path")
    p.add_argument(
        "-l",
        "--langs",
        default=",".join(DEFAULT_LANGS),
        help="comma-separated language preference, e.g. 'pt,en' (default: en)",
    )
    p.add_argument(
        "-m",
        "--model",
        default=saved.get("asr_model") or asr_mod.DEFAULT_MODEL,
        help="ASR model: a short name (%s), a whisper.cpp .bin path, "
        "or an MLX repo id (default: %%(default)s)" % ", ".join(asr_mod.MLX_MODELS),
    )
    p.add_argument(
        "--engine",
        choices=list(asr_mod.ENGINES),
        default=saved_engine,
        help="ASR engine: whisper-cpp, mlx (mlx-whisper, Apple Silicon), "
        "or auto = whichever is installed, whisper.cpp first (default)",
    )
    p.add_argument(
        "--download-model",
        action="store_true",
        help="download the --model for --engine mlx now, then exit",
    )
    p.add_argument(
        "--list-models",
        action="store_true",
        help="list known models and whether each MLX model is downloaded, then exit",
    )
    p.add_argument(
        "--asr",
        choices=["never", "auto", "always"],
        default="auto",
        help="local ASR usage: auto escalates only when captions are "
        "missing/unusable (default), never, or always",
    )
    p.add_argument(
        "--timestamps", action="store_true", help="include [mm:ss] stamps in txt/md output"
    )
    p.add_argument(
        "--raw", action="store_true", help="skip paragraph reflow; one line per caption cue"
    )
    p.add_argument(
        "--drop-sound-tags",
        action="store_true",
        help="remove [Music], (applause) style annotations",
    )
    p.add_argument(
        "--list-tracks", action="store_true", help="list available caption tracks and exit"
    )
    p.add_argument(
        "--batch", metavar="FILE", help="read URLs from a file (one per line, # comments allowed)"
    )
    p.add_argument(
        "--playlist", action="store_true", help="expand playlist URLs into individual videos"
    )
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    p.add_argument("-v", "--verbose", action="store_true", help="show debug detail")
    p.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="pass through to yt-dlp for age/region-restricted videos",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECS",
        help="pause between videos in batch/playlist runs to avoid "
        "HTTP 429 throttling (default: %(default)s)",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=1,
        help="retry a failed video this many times (default: %(default)s)",
    )
    p.add_argument("--stats", action="store_true", help="print a timing summary")
    p.add_argument(
        "--no-cache", action="store_true", help="bypass the on-disk caption/metadata cache"
    )
    p.add_argument(
        "--clear-cache",
        action="store_true",
        help="delete cached caption and metadata payloads, then exit",
    )
    p.add_argument(
        "--cache-ttl",
        type=int,
        default=DEFAULT_TTL,
        metavar="SECS",
        help="cache lifetime in seconds (default: %(default)s)",
    )
    p.add_argument(
        "--rewrite-timeout",
        type=int,
        default=None,
        metavar="SECS",
        help="local rewrite command timeout (default: 2 minutes plus 2 s per segment)",
    )
    p.add_argument(
        "--rewrite-from",
        metavar="TRANSCRIPT_JSON",
        help="rewrite an existing `ytt -f json` transcript instead of fetching the video "
        "again; needs --rewrite-command",
    )
    # [AI-GENERATED] REMAINDER keeps runner flags such as `--model` out of
    # ytt's own parser, so this option must be the last one on the line.
    p.add_argument(
        "--rewrite-command",
        nargs=argparse.REMAINDER,
        metavar="CMD",
        help="run a local context-aware rewriter after transcription; "
        "must be the LAST option, everything after it is passed "
        "to the command, which reads JSON on stdin and writes "
        "JSON on stdout",
    )
    p.add_argument(
        "--review-report",
        metavar="REVIEW_JSON",
        help="rebuild the HTML review report from an existing <name>.review.json and exit",
    )
    p.add_argument("--version", action="version", version="ytt " + __version__)
    return p


class RewriteFailed(RuntimeError):
    """[AI-GENERATED] The rewrite companion failed after originals were written.

    ``written`` lists the original output paths that were saved successfully.
    """

    def __init__(self, message: str, written: List[str]):
        super().__init__(message)
        self.written = list(written)


def collect_urls(args) -> List[str]:
    urls = list(args.urls)
    if args.batch:
        with open(args.batch, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    urls.append(line)
    return urls


def _looks_like_file(out: str) -> bool:
    """True only when --out clearly names a file rather than a directory."""
    if os.path.isdir(out):
        return False
    ext = os.path.splitext(out)[1].lstrip(".").lower()
    return ext in FORMATS


def output_path(out: str, title: str, video_id: str, fmt: str, multi: bool) -> str:
    """Resolve the destination file for one video/format.

    `--out` is treated as a directory unless it ends in a known output
    extension, so `-o transcripts` works even before the directory exists.
    With several videos, an explicit file name gets the video ID inserted
    (``notes [id].txt``) so each video keeps its own file.
    """
    ext = "." + fmt
    out = out or "."
    if not _looks_like_file(out):
        if multi:
            # Reserve room so the video ID suffix is never truncated away.
            suffix = " [%s]" % video_id
            base = sanitize_filename(title or video_id, max_len=80 - len(suffix))
            return os.path.join(out, base + suffix + ext)
        return os.path.join(out, sanitize_filename(title or video_id) + ext)
    root, given = os.path.splitext(out)
    if multi:
        return "%s [%s]%s" % (root, video_id, ext)
    # Explicit file path: honour it verbatim when it matches the format.
    if given.lower() == ext:
        return out
    return root + ext


def rewritten_output_path(path: str) -> str:
    root, ext = os.path.splitext(path)
    return root + ".rewritten" + ext


def review_output_path(path: str) -> str:
    """Review sidecar next to an original output, e.g. ``video.review.json``."""
    root, _ = os.path.splitext(path)
    return root + ".review.json"


def report_output_path(review_path: str) -> str:
    """HTML report next to a review file: ``video.review.json`` → ``video.review.html``."""
    root = review_path[: -len(".json")] if review_path.endswith(".json") else review_path
    return root + ".html"


def reviewed_name(review_path: str) -> str:
    """Download name for the Reviewed copy, matching the macOS app."""
    name = os.path.basename(review_path)
    base = (
        name[: -len(".review.json")] if name.endswith(".review.json") else os.path.splitext(name)[0]
    )
    return base + ".reviewed.txt"


def write_report(review: dict, review_path: str) -> str:
    path = report_output_path(review_path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_report(review, reviewed_name(review_path)))
    return path


def _write_formats(
    t: Transcript,
    args,
    title: str,
    vid: str,
    multi: bool,
    log: Log,
    companion: bool,
    keep_existing: bool = False,
) -> List[str]:
    written: List[str] = []
    for fmt in args.format:
        path = output_path(args.out, title, vid, fmt, multi)
        if companion:
            path = rewritten_output_path(path)
        if keep_existing and os.path.exists(path):
            written.append(path)
            continue
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        body = render(t, fmt, timestamps=args.timestamps)
        if args.raw and fmt in ("txt", "md"):
            body = _render_raw(t, fmt, args.timestamps)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        written.append(path)
        log.debug("wrote %s (%s)" % (path, fmt))
    return written


def rewrite_timeout(args, transcript: Transcript) -> int:
    """``--rewrite-timeout``, or a limit that grows with the transcript.

    A fixed 5 minutes cut off local models on hour-long videos after most of
    the work was done; 2 s per segment covers a 7B model on Apple silicon.
    """
    if args.rewrite_timeout:
        return args.rewrite_timeout
    return 120 + 2 * len(transcript.segments)


def write_outputs(
    transcript: Transcript,
    args,
    title: str,
    vid: str,
    multi: bool,
    log: Log,
    keep_originals: bool = False,
) -> List[str]:
    """[AI-GENERATED] Write originals first, then optional rewrite companions.

    Originals are always persisted before the rewriter runs, so a failing or
    slow model never loses the transcript. Rewrite errors raise
    :class:`RewriteFailed` carrying the original paths. With
    ``keep_originals`` (``--rewrite-from``) originals that already exist are
    left untouched, but their paths are still reported first.
    """
    written = _write_formats(
        transcript, args, title, vid, multi, log, False, keep_existing=keep_originals
    )
    if not args.rewrite_command:
        return written
    t0 = Timer()
    try:
        rewritten = rewrite_transcript(
            transcript, args.rewrite_command, timeout=rewrite_timeout(args, transcript)
        )
    except Exception as exc:
        raise RewriteFailed("local rewrite failed: %s" % exc, written) from exc
    log.info("  ✓ local rewrite · %s" % fmt_elapsed(t0.ms))
    companions = _write_formats(rewritten, args, title, vid, multi, log, True)
    review_path = review_output_path(written[0])
    try:
        review = build_review(transcript, rewritten)
        with open(review_path, "w", encoding="utf-8") as fh:
            fh.write(render_review(review))
    except (OSError, ValueError) as exc:
        # The review sidecar is advisory; never lose the rewritten files over it.
        log.warn("could not write review file: %s" % exc)
        return written + companions
    log.debug("wrote %s (review)" % review_path)
    try:
        report_path = write_report(review, review_path)
    except OSError as exc:
        log.warn("could not write review report: %s" % exc)
        return written + companions + [review_path]
    log.debug("wrote %s (review report)" % report_path)
    return written + companions + [review_path, report_path]


def process_one(
    url: str,
    args,
    log: Log,
    multi: bool,
    cache: Optional[Cache] = None,
    yt: Optional[YouTube] = None,
) -> Tuple[Optional[Transcript], List[str]]:
    """Transcribe a single video. Returns (transcript, written_paths)."""
    if yt is None:
        yt = YouTube(log, cookies=args.cookies_from_browser, cache=cache)
    timer = Timer()

    meta = yt.metadata(url)
    vid = meta.get("id") or "video"
    title = meta.get("title") or vid
    log.info("▸ %s" % title)
    if meta.get("duration"):
        log.info(
            "  %s · %s"
            % (
                meta.get("uploader") or "unknown channel",
                fmt_duration(int(meta["duration"]) * 1000),
            )
        )

    tracks = yt.tracks(meta)
    if args.list_tracks:
        for t in tracks:
            log.info("  %-16s %-14s %s" % (t.lang, t.kind, ",".join(t.formats)))
        return None, []

    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    warnings: List[str] = []
    transcript: Optional[Transcript] = None

    want_captions = args.asr != "always"
    if want_captions:
        track = yt.pick_track(tracks, langs)
        if track is None:
            warnings.append("no caption tracks available")
            log.debug("no caption tracks found")
        else:
            t0 = Timer()
            try:
                segments = yt.fetch_segments(track, url)
                problems = quality_report(segments, int((meta.get("duration") or 0) * 1000))
                log.debug(
                    "captions fetched in %s · %d segments · track %s (%s)"
                    % (fmt_elapsed(t0.ms), len(segments), track.lang, track.kind)
                )
                if problems:
                    warnings.extend(problems)
                    log.debug("caption quality issues: " + "; ".join(problems))
                    if args.asr == "never":
                        pass
                    else:
                        log.info(
                            "  captions look unusable (%s) → escalating to local ASR"
                            % "; ".join(problems)
                        )
                        segments = []
                if segments:
                    transcript = Transcript(
                        video_id=vid,
                        title=title,
                        url=meta.get("webpage_url") or url,
                        segments=segments,
                        duration_ms=int((meta.get("duration") or 0) * 1000),
                        channel=meta.get("uploader") or "",
                        lang=track.lang,
                        track_name=track.name,
                        kind=track.kind,
                        engine="captions",
                    )
                    log.info(
                        "  ✓ %s captions · %s words · %s"
                        % (track.kind, fmt_int(transcript.words), fmt_elapsed(t0.ms))
                    )
            except RateLimited:
                # A per-IP throttle is not "no captions" — let main() back off.
                raise
            except Exception as exc:
                warnings.append("caption fetch failed: %s" % exc)
                log.debug("caption fetch failed: %s" % exc)

    if transcript is None and args.asr != "never":
        if not asr_mod.asr_ready(args.engine):
            log.warn("no usable captions and the local ASR fallback is not installed")
            for k, v in asr_mod.detect_backends().items():
                log.info("    %-16s %s" % (k, v or "not found"))
            log.info(
                "  install with: brew install yt-dlp ffmpeg whisper-cpp"
                "  (or: pipx install mlx-whisper, then --engine mlx)"
            )
            return None, []
        t0 = Timer()
        lang = langs[0] if langs else "auto"
        asr_key = ("asr", vid, args.engine, args.model, lang)
        try:
            cached = cache.get_json(*asr_key) if cache is not None else None
            if cached is not None:
                segments = segments_from_data(cached)
                log.debug("ASR cache hit")
            else:
                segments = asr_mod.transcribe_audio(
                    url,
                    args.model,
                    log,
                    lang=lang,
                    engine=args.engine,
                    cookies=args.cookies_from_browser,
                    info=meta,
                )
                if cache is not None:
                    # Local ASR takes minutes; never redo it for the same video.
                    cache.set_json(segments_to_data(segments), *asr_key)
            transcript = asr_mod.transcript_from_asr(meta, segments, args.model, lang=lang)
            log.info(
                "  ✓ local ASR · %s words · %s" % (fmt_int(transcript.words), fmt_elapsed(t0.ms))
            )
        except Exception as exc:
            log.error("ASR fallback failed: %s" % exc)
            return None, []

    if transcript is None:
        log.error("no transcript produced for %s" % url)
        return None, []

    transcript.warnings = warnings
    if args.drop_sound_tags:
        from .segments import strip_sound_tags

        transcript.segments = strip_sound_tags(transcript.segments)
        if not transcript.segments:
            log.error("nothing left after removing sound tags")
            return None, []

    written = write_outputs(transcript, args, title, vid, multi, log)

    if args.stats:
        log.info(
            "  total %s · %s segments · %s words · %s chars"
            % (
                fmt_elapsed(timer.ms),
                fmt_int(len(transcript.segments)),
                fmt_int(transcript.words),
                fmt_int(transcript.chars),
            )
        )
    return transcript, written


def _render_raw(t: Transcript, fmt: str, timestamps: bool) -> str:
    if fmt == "md":
        head = "# %s\n\n" % (t.title or t.video_id)
        body = "\n".join(s.text for s in t.segments)
        return head + body + "\n"
    if timestamps:
        from .util import fmt_duration

        return "\n".join("[%s] %s" % (fmt_duration(s.start_ms), s.text) for s in t.segments) + "\n"
    return t.plain_text() + "\n"


def rewrite_from_file(args, log: Log) -> int:
    """``--rewrite-from``: rewrite a saved JSON transcript, no network at all.

    Prints the same paths, in the same order, as a full run with
    ``--rewrite-command`` would, so the macOS app parses both the same way.
    """
    if not args.rewrite_command:
        log.error("--rewrite-from needs --rewrite-command")
        return 2
    try:
        with open(args.rewrite_from, encoding="utf-8") as fh:
            transcript = transcript_from_json(json.load(fh))
    except (OSError, ValueError, TypeError) as exc:
        log.error("could not read transcript %s: %s" % (args.rewrite_from, exc))
        return 1
    if not transcript.segments:
        log.error("transcript %s has no segments" % args.rewrite_from)
        return 1
    title = transcript.title or transcript.video_id
    try:
        paths = write_outputs(
            transcript, args, title, transcript.video_id, False, log, keep_originals=True
        )
    except RewriteFailed as exc:
        log.error(str(exc))
        for p in exc.written:
            print(p)
        return 1
    for p in paths:
        print(p)
    return 0


def _on_sigterm(signum, frame):  # pragma: no cover - exercised by the app
    # Unwind normally so `finally` blocks delete temp audio, and subprocess
    # calls kill the child they are waiting on.
    raise SystemExit(128 + signum)


def install_signal_handling(environ=os.environ) -> None:
    """Make ``ytt`` safe to cancel.

    SIGTERM unwinds like Ctrl-C instead of exiting at once. When the macOS
    app sets ``YTT_PROCESS_GROUP=1``, ytt also leads its own process group,
    so cancelling signals yt-dlp, ffmpeg and Whisper along with it. (Only
    then: in a terminal, a new group would stop Ctrl-C reaching ytt.)
    """
    signal.signal(signal.SIGTERM, _on_sigterm)
    if environ.get("YTT_PROCESS_GROUP") == "1":
        with contextlib.suppress(OSError):
            os.setpgid(0, 0)


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        install_signal_handling()
    raw = sys.argv[1:] if argv is None else list(argv)
    if raw and raw[0] == "demo":
        from . import demo

        return demo.main(raw[1:])
    parser = build_parser()
    args = parser.parse_args(raw)
    if args.rewrite_command is not None and not args.rewrite_command:
        parser.error("--rewrite-command requires a command")
    log = Log(quiet=args.quiet, verbose=args.verbose)

    if args.review_report:
        try:
            with open(args.review_report, encoding="utf-8") as fh:
                review = json.load(fh)
            if not isinstance(review, dict) or not isinstance(review.get("segments"), list):
                raise ValueError("not a ytt review file")
            print(write_report(review, args.review_report))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.error("could not build review report: %s" % exc)
            return 1
        return 0

    if args.list_models:
        for name, repo in asr_mod.MLX_MODELS.items():
            state = "downloaded" if asr_mod.mlx_model_cached(repo) else "not downloaded"
            log.info("%-15s %-45s %s" % (name, repo, state))
        return 0
    if args.download_model:
        if args.engine == "whisper-cpp":
            log.error(
                "--download-model is for the mlx engine; fetch a whisper.cpp model with:\n  %s"
                % asr_mod.whisper_cpp_download_command(args.model)
            )
            return 2
        try:
            repo = asr_mod.download_mlx_model(args.model, log)
        except asr_mod.ASRUnavailable as exc:
            log.error(str(exc))
            return 1
        print(repo)
        return 0

    if args.rewrite_from:
        return rewrite_from_file(args, log)

    cache = Cache(enabled=not args.no_cache, ttl=args.cache_ttl)
    if args.clear_cache:
        n = cache.clear()
        log.info("cleared %d cached file(s) from %s" % (n, cache.root))
        return 0

    urls = collect_urls(args)
    if not urls:
        build_parser().print_help(sys.stderr)
        return 2

    try:
        yt_probe = YouTube(log, cookies=args.cookies_from_browser, cache=cache)
    except YtDlpMissing as exc:
        log.error(str(exc))
        return 2

    failed: List[str] = []
    valid: List[str] = []
    for url in urls:
        try:
            valid.append(validate_url(url))
        except InvalidURL as exc:
            log.error("skipping %s" % exc)
            failed.append(url)

    expanded: List[str] = []
    for url in valid:
        if args.playlist or ("list=" in url and "watch?v=" not in url):
            try:
                ids = yt_probe.playlist_ids(url)
                log.info("playlist: %d videos" % len(ids))
                expanded.extend("https://www.youtube.com/watch?v=%s" % i for i in ids)
                continue
            except Exception as exc:
                log.warn("could not expand playlist (%s); treating as a single video" % exc)
        expanded.append(url)

    multi = len(expanded) > 1
    if multi:
        n = yt_probe.prefetch_metadata(expanded)
        if n:
            log.debug("prefetched metadata for %d video(s)" % n)
    ok = 0
    requests_before = yt_probe.requests
    for i, url in enumerate(expanded, 1):
        if multi:
            log.info("\n[%d/%d] %s" % (i, len(expanded), url))
        if multi and i > 1 and args.delay > 0 and yt_probe.requests > requests_before:
            # Be polite; YouTube 429s on bursts. Skipped when the previous
            # video came entirely from the cache.
            time.sleep(args.delay)
        requests_before = yt_probe.requests

        attempts = max(1, args.retries + 1)
        transcript = None
        paths: List[str] = []
        succeeded = False
        for attempt in range(attempts):
            try:
                transcript, paths = process_one(url, args, log, multi, cache, yt_probe)
                # --list-tracks returns no transcript but is still a success.
                succeeded = transcript is not None or args.list_tracks
                break
            except (VideoError, YtDlpMissing) as exc:
                log.error(str(exc))
                limited = isinstance(exc, RateLimited)
                if attempt + 1 < attempts and limited:
                    # Throttles usually clear within a minute or two.
                    wait = min(120, 15 * (3**attempt))
                    log.info(
                        "  rate-limited; retrying in %ds (attempt %d/%d)…"
                        % (wait, attempt + 1, attempts)
                    )
                    time.sleep(wait)
                    continue
                if limited:
                    log.info(
                        "  YouTube is throttling this IP. Wait a few minutes, "
                        "or retry with --cookies-from-browser chrome"
                    )
                failed.append(url)
                break
            except RewriteFailed as exc:
                # [AI-GENERATED] Originals were saved; surface them, but count
                # the URL as failed so batch summaries and exit codes are honest.
                log.error(str(exc))
                for p in exc.written:
                    print(p)
                failed.append(url)
                break
            except KeyboardInterrupt:
                log.error("interrupted")
                return 130
            except Exception as exc:
                log.error("%s: %s" % (type(exc).__name__, exc))
                failed.append(url)
                break
        if succeeded:
            ok += 1
            for p in paths:
                print(p)

    total = len(expanded) + len(urls) - len(valid)
    if multi or failed:
        log.info("\n%d/%d succeeded" % (ok, total))
        if failed:
            log.info("failed: %s" % ", ".join(failed))
    if not ok:
        return 1
    # Some videos worked and some did not: a distinct code lets scripts and
    # the macOS app keep the files that were written.
    return EXIT_PARTIAL if ok < total else 0


if __name__ == "__main__":
    sys.exit(main())
