"""Measure the caption path and compare it with local ASR.

Caption timings are MEASURED. ASR timings are ESTIMATES from published
whisper.cpp throughput on Apple silicon, clearly labelled as such, because the
ASR tier needs ffmpeg + a downloaded model that may not be installed.

Usage: python3 tests/benchmark.py
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.captions import parse_any
from ytt.util import Log
from ytt.youtube import YouTube

# Rough whisper.cpp speed on M-series with Core ML, as multiples of realtime.
# small.en ≈ 10-15x realtime; medium.en ≈ 4-6x; large-v3 ≈ 1.5-2.5x.
ASR_RTF = {"tiny.en": 25.0, "base.en": 18.0, "small.en": 12.0, "medium.en": 5.0, "large-v3": 2.0}
# Audio download + ffmpeg transcode overhead, seconds.
ASR_FIXED_OVERHEAD = 6.0

VIDEOS = [
    ("aircAruvnKk", "3Blue1Brown, manual captions"),
    ("jNQXAC9IVRw", "first YouTube video, manual captions"),
]


def bench(vid):
    yt = YouTube(Log(quiet=True))
    url = "https://www.youtube.com/watch?v=%s" % vid

    t0 = time.perf_counter()
    meta = yt.metadata(url)
    t_meta = time.perf_counter() - t0

    dur = int(meta.get("duration") or 0)
    track = yt.pick_track(yt.tracks(meta), ["en"])
    if track is None:
        return None

    t0 = time.perf_counter()
    payload, fmt = yt.fetch_track(track, url)
    t_fetch = time.perf_counter() - t0

    t0 = time.perf_counter()
    segs = parse_any(payload, fmt)
    t_parse = time.perf_counter() - t0

    return {
        "vid": vid,
        "title": (meta.get("title") or "")[:38],
        "duration": dur,
        "kind": track.kind,
        "bytes": len(payload.encode("utf-8")),
        "segments": len(segs),
        "words": sum(len(s.text.split()) for s in segs),
        "t_meta": t_meta,
        "t_fetch": t_fetch,
        "t_parse": t_parse,
        "t_total": t_meta + t_fetch + t_parse,
    }


def main():
    print("Caption path (measured)\n" + "=" * 78)
    rows = []
    for vid, note in VIDEOS:
        try:
            r = bench(vid)
        except Exception as exc:
            print("  %-12s FAILED: %s" % (vid, exc))
            continue
        if not r:
            print("  %-12s no captions" % vid)
            continue
        rows.append(r)
        print("  %-12s %5s  %6.1fs video  %5.1f KB  %4d segs  "
              "meta %.2fs + fetch %.2fs + parse %.3fs = %.2fs"
              % (vid, r["kind"], r["duration"], r["bytes"] / 1024.0, r["segments"],
                 r["t_meta"], r["t_fetch"], r["t_parse"], r["t_total"]))
        print("               %s" % r["title"])

    if not rows:
        print("\nNo measurements collected (likely rate-limited). Try again later.")
        return 1

    print("\nComparison (caption path measured, ASR estimated)\n" + "=" * 78)
    print("  %-22s %10s %10s %10s %8s" % ("video", "captions", "small.en", "medium.en", "speedup"))
    for r in rows:
        d = r["duration"]
        est_small = d / ASR_RTF["small.en"] + ASR_FIXED_OVERHEAD
        est_med = d / ASR_RTF["medium.en"] + ASR_FIXED_OVERHEAD
        print("  %-22s %9.2fs %9.1fs %9.1fs %7.0fx"
              % (r["vid"], r["t_total"], est_small, est_med, est_small / r["t_total"]))

    totals = [r["t_total"] for r in rows]
    print("\n  caption path: mean %.2fs, median %.2fs over %d videos"
          % (statistics.mean(totals), statistics.median(totals), len(totals)))
    print("  ASR estimates assume whisper.cpp + Core ML on Apple silicon and are")
    print("  not measured; they exclude model download (0.5-3 GB, one time).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
