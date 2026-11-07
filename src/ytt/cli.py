"""Command-line interface for yt-transcribe."""
from __future__ import annotations

import argparse
import time
import os
import sys
from typing import List, Optional, Tuple

from . import __version__
from . import asr as asr_mod
from .cache import DEFAULT_TTL, Cache
from .captions import parse_any
from .formatter import FORMATS, render
from .model import Transcript
from .rewriter import rewrite_transcript
from .segments import quality_report
from .util import Log, Timer, fmt_duration, fmt_elapsed, fmt_int, sanitize_filename
from .youtube import RateLimited, VideoError, YtDlpMissing, YouTube

DEFAULT_LANGS = ["en"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytt",
        description="YouTube transcripts in seconds — uses YouTube's own caption "
                    "tracks by default, with local whisper.cpp as a fallback.",
        epilog="Examples:\n"
               "  ytt https://youtu.be/aircAruvnKk\n"
               "  ytt <url> -f srt vtt json -o ~/Downloads\n"
               "  ytt <url> --langs pt,en --asr auto\n"
               "  ytt --batch urls.txt -o transcripts/\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", help="YouTube video or playlist URLs")
    p.add_argument("-f", "--format", nargs="+", default=["txt"], choices=list(FORMATS),
                   metavar="FMT", help="output formats: %s (default: txt)" % ", ".join(FORMATS))
    p.add_argument("-o", "--out", default=".", help="output directory or file path")
    p.add_argument("-l", "--langs", default=",".join(DEFAULT_LANGS),
                   help="comma-separated language preference, e.g. 'pt,en' (default: en)")
    p.add_argument("-m", "--model", default=asr_mod.DEFAULT_MODEL,
                   help="whisper.cpp model for the ASR fallback (default: %(default)s)")
    p.add_argument("--asr", choices=["never", "auto", "always"], default="auto",
                   help="local ASR usage: auto escalates only when captions are "
                        "missing/unusable (default), never, or always")
    p.add_argument("--timestamps", action="store_true",
                   help="include [mm:ss] stamps in txt/md output")
    p.add_argument("--raw", action="store_true",
                   help="skip paragraph reflow; one line per caption cue")
    p.add_argument("--drop-sound-tags", action="store_true",
                   help="remove [Music], (applause) style annotations")
    p.add_argument("--list-tracks", action="store_true",
                   help="list available caption tracks and exit")
    p.add_argument("--batch", metavar="FILE",
                   help="read URLs from a file (one per line, # comments allowed)")
    p.add_argument("--playlist", action="store_true",
                   help="expand playlist URLs into individual videos")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    p.add_argument("-v", "--verbose", action="store_true", help="show debug detail")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="pass through to yt-dlp for age/region-restricted videos")
    p.add_argument("--delay", type=float, default=1.0, metavar="SECS",
                   help="pause between videos in batch/playlist runs to avoid "
                        "HTTP 429 throttling (default: %(default)s)")
    p.add_argument("--retries", type=int, default=1,
                   help="retry a failed video this many times (default: %(default)s)")
    p.add_argument("--stats", action="store_true", help="print a timing summary")
    p.add_argument("--no-cache", action="store_true",
                   help="bypass the on-disk caption/metadata cache")
    p.add_argument("--clear-cache", action="store_true",
                   help="delete cached caption and metadata payloads, then exit")
    p.add_argument("--cache-ttl", type=int, default=DEFAULT_TTL, metavar="SECS",
                   help="cache lifetime in seconds (default: %(default)s)")
    p.add_argument("--rewrite-timeout", type=int, default=300, metavar="SECS",
                   help="local rewrite command timeout (default: %(default)s)")
    # [AI-GENERATED] REMAINDER keeps runner flags such as `--model` out of
    # ytt's own parser, so this option must be the last one on the line.
    p.add_argument("--rewrite-command", nargs=argparse.REMAINDER, metavar="CMD",
                   help="run a local context-aware rewriter after transcription; "
                        "must be the LAST option, everything after it is passed "
                        "to the command, which reads JSON on stdin and writes "
                        "JSON on stdout")
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
        with open(args.batch, "r", encoding="utf-8") as fh:
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
    # Explicit file path: honour it verbatim when it matches the format.
    if out.lower().endswith(ext):
        return out
    root, _ = os.path.splitext(out)
    return root + ext


def rewritten_output_path(path: str) -> str:
    root, ext = os.path.splitext(path)
    return root + ".rewritten" + ext


def _write_formats(t: Transcript, args, title: str, vid: str, multi: bool,
                   log: Log, companion: bool) -> List[str]:
    written: List[str] = []
    for fmt in args.format:
        path = output_path(args.out, title, vid, fmt, multi)
        if companion:
            path = rewritten_output_path(path)
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


def write_outputs(transcript: Transcript, args, title: str, vid: str,
                  multi: bool, log: Log) -> List[str]:
    """[AI-GENERATED] Write originals first, then optional rewrite companions.

    Originals are always persisted before the rewriter runs, so a failing or
    slow model never loses the transcript. Rewrite errors raise
    :class:`RewriteFailed` carrying the original paths.
    """
    written = _write_formats(transcript, args, title, vid, multi, log, False)
    if not args.rewrite_command:
        return written
    t0 = Timer()
    try:
        rewritten = rewrite_transcript(
            transcript, args.rewrite_command, timeout=args.rewrite_timeout
        )
    except Exception as exc:
        raise RewriteFailed("local rewrite failed: %s" % exc, written) from exc
    log.info("  ✓ local rewrite · %s" % fmt_elapsed(t0.ms))
    return written + _write_formats(rewritten, args, title, vid, multi, log, True)


def process_one(
    url: str,
    args,
    log: Log,
    multi: bool,
    cache: Optional[Cache] = None,
) -> Tuple[Optional[Transcript], List[str]]:
    """Transcribe a single video. Returns (transcript, written_paths)."""
    yt = YouTube(log, cookies=args.cookies_from_browser, cache=cache)
    timer = Timer()

    meta = yt.metadata(url)
    vid = meta.get("id") or "video"
    title = meta.get("title") or vid
    log.info("▸ %s" % title)
    if meta.get("duration"):
        log.info("  %s · %s" % (meta.get("uploader") or "unknown channel",
                                fmt_duration(int(meta["duration"]) * 1000)))

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
                payload, fmt = yt.fetch_track(track, url)
                segments = parse_any(payload, fmt or track.best_format)
                problems = quality_report(segments, int((meta.get("duration") or 0) * 1000))
                log.debug("captions fetched in %s · %d segments · track %s (%s)" % (
                    fmt_elapsed(t0.ms), len(segments), track.lang, track.kind))
                if problems:
                    warnings.extend(problems)
                    log.debug("caption quality issues: " + "; ".join(problems))
                    if args.asr == "never":
                        pass
                    else:
                        log.info("  captions look unusable (%s) → escalating to local ASR"
                                 % "; ".join(problems))
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
                    log.info("  ✓ %s captions · %s words · %s" % (
                        track.kind, fmt_int(transcript.words), fmt_elapsed(t0.ms)))
            except RateLimited:
                # A per-IP throttle is not "no captions" — let main() back off.
                raise
            except Exception as exc:
                warnings.append("caption fetch failed: %s" % exc)
                log.debug("caption fetch failed: %s" % exc)

    if transcript is None and args.asr != "never":
        if not asr_mod.asr_ready():
            log.warn("no usable captions and the local ASR fallback is not installed")
            for k, v in asr_mod.detect_backends().items():
                log.info("    %-16s %s" % (k, v or "not found"))
            log.info("  install with: brew install yt-dlp ffmpeg whisper-cpp")
            return None, []
        t0 = Timer()
        try:
            segments = asr_mod.transcribe_audio(url, args.model, log, lang=langs[0] if langs else "auto")
            transcript = asr_mod.transcript_from_asr(meta, segments, args.model,
                                                     lang=langs[0] if langs else "auto")
            log.info("  ✓ local ASR · %s words · %s" % (
                fmt_int(transcript.words), fmt_elapsed(t0.ms)))
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
        log.info("  total %s · %s segments · %s words · %s chars" % (
            fmt_elapsed(timer.ms), fmt_int(len(transcript.segments)),
            fmt_int(transcript.words), fmt_int(transcript.chars)))
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rewrite_command is not None and not args.rewrite_command:
        parser.error("--rewrite-command requires a command")
    log = Log(quiet=args.quiet, verbose=args.verbose)

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

    expanded: List[str] = []
    for url in urls:
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
    ok = 0
    failed: List[str] = []
    for i, url in enumerate(expanded, 1):
        if multi:
            log.info("\n[%d/%d] %s" % (i, len(expanded), url))
        if multi and i > 1 and args.delay > 0:
            time.sleep(args.delay)  # be polite; YouTube 429s on bursts

        attempts = max(1, args.retries + 1)
        transcript = None
        paths: List[str] = []
        succeeded = False
        for attempt in range(attempts):
            try:
                transcript, paths = process_one(url, args, log, multi, cache)
                # --list-tracks returns no transcript but is still a success.
                succeeded = transcript is not None or args.list_tracks
                break
            except (VideoError, YtDlpMissing) as exc:
                log.error(str(exc))
                if attempt + 1 < attempts and "429" in str(exc):
                    # Throttles usually clear within a minute or two.
                    wait = min(120, 15 * (3 ** attempt))
                    log.info("  rate-limited; retrying in %ds (attempt %d/%d)…"
                             % (wait, attempt + 1, attempts))
                    time.sleep(wait)
                    continue
                if "429" in str(exc):
                    log.info("  YouTube is throttling this IP. Wait a few minutes, "
                             "or retry with --cookies-from-browser chrome")
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

    if multi:
        log.info("\n%d/%d succeeded" % (ok, len(expanded)))
        if failed:
            log.info("failed: %s" % ", ".join(failed))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
