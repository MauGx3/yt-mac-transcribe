"""Robustness sweep: run the caption path over many varied videos.

Checks that parsing never raises, timings are ordered, and no duplicate or
overlapping cues survive. Usage: python3 tests/sweep.py [n]
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt.captions import parse_any
from ytt.segments import quality_report
from ytt.util import Log
from ytt.youtube import YouTube

QUERIES = [
    "ytsearch6:TED talk",
    "ytsearch4:music video official",
    "ytsearch4:japanese interview",
    "ytsearch4:python tutorial",
    "ytsearch3:live stream news",
    "ytsearch3:shorts",
]


def collect(limit):
    yt = YouTube(Log(quiet=True))
    ids, seen = [], set()
    for q in QUERIES:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", q],
            capture_output=True,
            text=True,
            timeout=180,
        )
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            continue
        for entry in data.get("entries") or []:
            vid = entry.get("id")
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
    return ids[:limit]


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    ids = collect(limit)
    print("probing %d videos\n" % len(ids))

    yt = YouTube(Log(quiet=True))
    stats = {"manual": 0, "auto": 0, "auto-translated": 0, "none": 0, "throttled": 0, "error": 0}
    delay = float(os.environ.get("SWEEP_DELAY", "2"))
    failures, warnings = [], []

    for i, vid in enumerate(ids, 1):
        url = "https://www.youtube.com/watch?v=%s" % vid
        try:
            meta = yt.metadata(url)
        except Exception as exc:
            print("%2d. %-12s META-FAIL %s" % (i, vid, str(exc)[:60]))
            stats["error"] += 1
            continue

        title = (meta.get("title") or "")[:40]
        dur = int((meta.get("duration") or 0) * 1000)
        tracks = yt.tracks(meta)
        track = yt.pick_track(tracks, ["en"])
        if track is None:
            print("%2d. %-12s NO-CAPTIONS  %s" % (i, vid, title))
            stats["none"] += 1
            continue

        try:
            payload, fmt = yt.fetch_track(track, url)
            segs = parse_any(payload, fmt)
        except Exception as exc:
            if "429" in str(exc):
                print("%2d. %-12s THROTTLED    %s" % (i, vid, title))
                stats["throttled"] += 1
                time.sleep(delay * 3)
                continue
            print("%2d. %-12s PARSE-FAIL   %s :: %s" % (i, vid, title, str(exc)[:70]))
            failures.append((vid, str(exc)))
            stats["error"] += 1
            continue

        stats[track.kind] = stats.get(track.kind, 0) + 1

        # invariants
        problems = []
        for a, b in zip(segs, segs[1:]):
            if a.end_ms > b.start_ms + 1:
                problems.append("overlap")
                break
        for s in segs:
            if s.end_ms <= s.start_ms:
                problems.append("zero-duration")
                break
        keys = [s.text.lower().strip() for s in segs]
        dupes = sum(1 for a, b in zip(keys, keys[1:]) if a == b)
        if dupes:
            problems.append("%d adjacent dupes" % dupes)
        q = quality_report(segs, dur)
        if q:
            warnings.append((vid, q))

        flag = "OK  " if not problems else "FAIL"
        if problems:
            failures.append((vid, problems))
        time.sleep(delay)
        print(
            "%2d. %-12s %s %-15s %5d segs  %s  %s"
            % (i, vid, flag, track.kind, len(segs), title, "" if not problems else str(problems))
        )

    print("\n--- summary ---")
    for k, v in stats.items():
        print("  %-16s %d" % (k, v))
    print("  parse failures:  %d" % len(failures))
    for vid, why in failures:
        print("     %s: %s" % (vid, why))
    print("  quality flags:   %d" % len(warnings))
    for vid, q in warnings[:10]:
        print("     %s: %s" % (vid, "; ".join(q)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
