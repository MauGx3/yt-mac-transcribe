"""YouTube interaction: metadata, caption-track selection, payload fetching.

One `yt-dlp -J` call gives us metadata *and* the caption-track URLs, so we never
need to download audio or run ffmpeg on the caption path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .cache import META_TTL, Cache
from .tls import ssl_context
from .util import Log

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
PREFERRED_FORMATS = ("json3", "srv3", "vtt", "srv1", "ttml", "srt")

# Pseudo-tracks YouTube advertises that are not subtitles at all (e.g. the
# live-chat replay, whose "json" payload is an HTML page).
EXCLUDED_LANGS = {"live_chat"}
# Caption payload formats we can actually parse.
CAPTION_FORMATS = {"json3", "srv3", "srv2", "srv1", "vtt", "ttml", "srt"}


class YtDlpMissing(RuntimeError):
    pass


class VideoError(RuntimeError):
    pass


class RateLimited(VideoError):
    """YouTube returned HTTP 429.

    The throttle is per-IP, so retrying other caption formats is pointless —
    the caller should back off and retry the whole video instead.
    """


@dataclass
class Track:
    lang: str
    name: str
    kind: str  # "manual" | "auto" | "auto-translated"
    formats: List[str] = field(default_factory=list)
    urls: Dict[str, str] = field(default_factory=dict)

    @property
    def best_format(self) -> Optional[str]:
        for fmt in PREFERRED_FORMATS:
            if fmt in self.urls:
                return fmt
        return next(iter(self.urls), None)

    @property
    def is_translation(self) -> bool:
        return self.kind == "auto-translated"


def _base_lang(lang: str) -> str:
    return lang.split("-")[0].lower()


def _lang_score(track: Track, langs: List[str]) -> int:
    """Higher is better; 0 means the track does not match any preference."""
    tl = track.lang.lower()
    for i, pref in enumerate(langs):
        p = pref.lower()
        rank = len(langs) - i  # earlier preference wins
        if tl == p:
            return 100 + rank
        if tl.split("-")[0] == p.split("-")[0] and "-" not in p:
            return 70 + rank
        if tl.startswith(p + "-") or p.startswith(tl + "-"):
            return 50 + rank
    return 0


class YouTube:
    def __init__(
        self,
        log: Log,
        ytdlp: str = "yt-dlp",
        cookies: Optional[str] = None,
        cache: Optional[Cache] = None,
    ) -> None:
        self.log = log
        self.cookies = cookies
        self.cache = cache or Cache(enabled=False)
        if shutil.which(ytdlp) is None:
            raise YtDlpMissing(
                "yt-dlp not found. Install it with `brew install yt-dlp` "
                "(or `pipx install yt-dlp`)."
            )
        self.ytdlp = ytdlp

    # ---------------------------------------------------------------- metadata
    def _run(self, args: List[str], timeout: int = 180) -> subprocess.CompletedProcess:
        cmd = [self.ytdlp, *args]
        if self.cookies:
            cmd += ["--cookies-from-browser", self.cookies]
        self.log.debug("$ " + " ".join(cmd))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def metadata(self, url: str) -> Dict[str, Any]:
        cached = self.cache.get_json("meta", url, ttl=META_TTL)
        if cached is not None:
            self.log.debug("metadata cache hit")
            return cached
        proc = self._run(["-J", "--skip-download", "--no-warnings", url])
        if proc.returncode != 0:
            raise VideoError(_clean_error(proc.stderr) or "yt-dlp failed to read %s" % url)
        try:
            meta = json.loads(proc.stdout)
        except ValueError as exc:
            raise VideoError("could not parse yt-dlp metadata for %s" % url) from exc
        self.cache.set_json(meta, "meta", url)
        return meta

    def playlist_ids(self, url: str) -> List[str]:
        proc = self._run(
            ["--flat-playlist", "--skip-download", "--print", "%(id)s", "--no-warnings", url]
        )
        if proc.returncode != 0:
            raise VideoError(_clean_error(proc.stderr) or "yt-dlp failed to read playlist")
        return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]

    # ------------------------------------------------------------------ tracks
    def tracks(self, meta: Dict[str, Any]) -> List[Track]:
        out: List[Track] = []
        for kind, key in (("manual", "subtitles"), ("auto", "automatic_captions")):
            for lang, entries in (meta.get(key) or {}).items():
                if lang.lower() in EXCLUDED_LANGS:
                    continue  # live_chat and friends are not subtitles
                urls: Dict[str, str] = {}
                name = lang
                for entry in entries:
                    fmt = (entry.get("ext") or "").lower()
                    if fmt in CAPTION_FORMATS and entry.get("url"):
                        urls[fmt] = entry["url"]
                    if entry.get("name") and name == lang:
                        name = entry["name"]
                if not urls:
                    continue
                tkind = kind
                if kind == "auto" and "-" in lang and not lang.endswith("-orig"):
                    # e.g. "en-pt" == English audio machine-translated to Portuguese
                    tkind = "auto-translated"
                out.append(Track(lang=lang, name=name, kind=tkind, formats=list(urls), urls=urls))
        return out

    def pick_track(self, tracks: List[Track], langs: List[str]) -> Optional[Track]:
        """Prefer human-authored captions, then YouTube's ASR, then translations."""
        if not tracks:
            return None
        tiers = (
            lambda t: t.kind == "manual",
            lambda t: t.kind == "auto" and not t.is_translation,
            lambda t: t.is_translation,
        )
        for tier in tiers:
            candidates = [t for t in tracks if tier(t)]
            scored = [(_lang_score(t, langs), t) for t in candidates]
            matched = [(s, t) for s, t in scored if s > 0]
            if matched:
                matched.sort(key=lambda st: -st[0])
                return matched[0][1]
            if candidates:
                # No language match: take the video's own original track first.
                originals = [t for t in candidates if t.lang.endswith("-orig")]
                return (originals or candidates)[0]
        return None

    # ----------------------------------------------------------------- payload
    def fetch_text(self, url: str, retries: int = 2, timeout: int = 30) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
                )
                with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # Per-IP throttle: one short retry, then surface it so the
                    # caller can fall back or wait instead of hammering.
                    last = exc
                    if attempt + 1 < retries:
                        time.sleep(4.0)
                        continue
                    raise RateLimited("HTTP 429 Too Many Requests") from exc
                last = exc
                if exc.code in (500, 502, 503, 504):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise
            except Exception as exc:  # network hiccup
                last = exc
                time.sleep(0.8 * (attempt + 1))
        raise VideoError("could not fetch caption payload: %s" % last)

    def fetch_track(self, track: Track, video_url: str) -> Tuple[str, Optional[str]]:
        """Fetch a caption payload, preferring direct HTTP over yt-dlp.

        Tries each available format until one yields a payload we can actually
        parse, since YouTube occasionally serves an HTML error page for a track.
        Returns (payload, format). The format is ``None`` when it is not known
        (cache hits and the yt-dlp fallback), so callers should let
        :func:`parse_any` detect it from the payload.
        """
        from .captions import parse_any

        cached = self.cache.get_text("cap", video_url, track.lang, track.kind)
        if cached is not None:
            self.log.debug("caption cache hit (%s)" % track.lang)
            return cached, None

        order = [f for f in PREFERRED_FORMATS if f in track.urls]
        order += [f for f in track.urls if f not in order]
        last_exc: Optional[Exception] = None

        for fmt in order:
            try:
                payload = self.fetch_text(track.urls[fmt])
                parse_any(payload, fmt)  # validate before committing
                self.cache.set_text(payload, "cap", video_url, track.lang, track.kind)
                return payload, fmt
            except RateLimited:
                # Throttled at the IP level — other formats will fail the same
                # way, so go straight to the yt-dlp fallback.
                self.log.debug("rate limited; trying yt-dlp fallback")
                try:
                    return self._fetch_via_ytdlp(track, video_url), None
                except VideoError as exc:
                    raise RateLimited(str(exc)) from exc
            except Exception as exc:
                last_exc = exc
                self.log.debug("format %s unusable for %s: %s" % (fmt, track.lang, exc))

        self.log.debug("all direct formats failed (%s); falling back to yt-dlp" % last_exc)
        return self._fetch_via_ytdlp(track, video_url), None

    def _fetch_via_ytdlp(self, track: Track, video_url: str) -> str:
        """Last-resort path: let yt-dlp write one subtitle file, then read it."""
        import glob
        import os
        import shutil as _shutil
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="ytt-sub-")
        try:
            auto = track.kind != "manual"
            args = [
                "--skip-download",
                "--sub-format",
                "json3/vtt/srt",
                "--sub-langs",
                track.lang,
                "-o",
                os.path.join(tmpdir, "sub"),
                "--no-warnings",
                "--write-auto-subs" if auto else "--write-subs",
                video_url,
            ]
            proc = self._run(args)
            files = sorted(glob.glob(os.path.join(tmpdir, "sub*")))
            if not files:
                err = _clean_error(proc.stderr) or "unknown reason"
                if "429" in (proc.stderr or "") or "Too Many Requests" in (proc.stderr or ""):
                    raise RateLimited(
                        "YouTube rate-limited this request (HTTP 429). Wait a minute "
                        "and retry, or pass --cookies-from-browser to use a session."
                    )
                raise VideoError("no caption file produced: %s" % err)
            with open(files[0], encoding="utf-8", errors="replace") as fh:
                return fh.read()
        finally:
            _shutil.rmtree(tmpdir, ignore_errors=True)


def _clean_error(stderr: str) -> str:
    """Pull the useful line out of yt-dlp's stderr noise."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("ERROR:"):
            return ln[len("ERROR:") :].strip()
    return lines[-1] if lines else ""
