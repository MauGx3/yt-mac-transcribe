"""HTML report of a review document, for people who use the CLI.

The report is one self-contained page (no network, no external files) built
from the same ``<name>.review.json`` the macOS app reads. It shows every
change with its "AI unsure" and "Unclear audio" labels, and lists unclear
words the rewrite left alone. With JavaScript on, each change can be kept or
rejected and the Reviewed text downloaded; without it the page is still a
readable diff.
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List

from .review import AI_UNSURE, UNCLEAR_AUDIO

LABELS = {AI_UNSURE: "AI unsure", UNCLEAR_AUDIO: "Unclear audio"}

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa; --fg: #1d1d1f; --muted: #6e6e73; --line: #e3e3e0; --card: #ffffff;
  --del-bg: #fde8e7; --del-fg: #a1261b; --ins-bg: #e4f5e8; --ins-fg: #186a2e;
  --ai: #b25000; --ai-bg: #fff1e0; --audio: #0b5cad; --audio-bg: #e5f0fc;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161618; --fg: #ececee; --muted: #a1a1a6; --line: #2f2f33; --card: #1f1f22;
    --del-bg: #3d1b19; --del-fg: #ff9d92; --ins-bg: #173322; --ins-fg: #86e0a0;
    --ai: #ffb15c; --ai-bg: #3a2a14; --audio: #8cc4ff; --audio-bg: #14283f;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 32px 16px 120px; }
h1 { font-size: 1.6rem; line-height: 1.25; margin: 0 0 6px; overflow-wrap: anywhere; }
.summary, .note { color: var(--muted); margin: 0 0 16px; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0 0 20px; }
.badge { display: inline-block; font-size: .75rem; font-weight: 600; padding: 1px 7px;
  border-radius: 999px; white-space: nowrap; vertical-align: 1px; }
.badge.ai { color: var(--ai); background: var(--ai-bg); }
.badge.audio { color: var(--audio); background: var(--audio-bg); }
.controls { display: none; flex-wrap: wrap; gap: 8px; margin: 0 0 20px; }
.js .controls { display: flex; }
button { font: inherit; font-size: .9rem; padding: 6px 12px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--card); color: var(--fg); cursor: pointer; }
button[aria-pressed="true"] { border-color: var(--fg); }
button.primary { background: var(--fg); color: var(--bg); border-color: var(--fg); }
.seg { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 12px 16px; margin: 0 0 12px; }
.only-unsure .seg:not(.needs-look) { display: none; }
.time { font-size: .8rem; color: var(--muted); font-variant-numeric: tabular-nums;
  text-decoration: none; }
.text { margin: 4px 0 0; overflow-wrap: anywhere; }
del { background: var(--del-bg); color: var(--del-fg); text-decoration: line-through; }
ins { background: var(--ins-bg); color: var(--ins-fg); text-decoration: none; }
del, ins { border-radius: 3px; padding: 0 2px; }
.hunk.flag-ai ins { text-decoration: underline wavy var(--ai); text-underline-offset: 3px; }
.hunk label { display: none; font-size: .75rem; color: var(--muted); margin-left: 4px;
  white-space: nowrap; }
.js .hunk label { display: inline; }
.hunk.rejected ins { opacity: .45; text-decoration: line-through; }
.hunk.rejected del { background: none; color: inherit; text-decoration: none; }
mark.audio { background: var(--audio-bg); color: var(--audio); border-radius: 3px; padding: 0 2px; }
.kept { margin: 6px 0 0; font-size: .9rem; color: var(--muted); }
.bar { position: fixed; left: 0; right: 0; bottom: 0; display: none; justify-content: center;
  gap: 12px; align-items: center; padding: 12px 16px; background: var(--card);
  border-top: 1px solid var(--line); }
.js .bar { display: flex; }
.bar span { color: var(--muted); font-size: .9rem; }
"""

_JS = """
(function () {
  document.documentElement.classList.add("js");
  var doc = JSON.parse(document.getElementById("review-data").textContent);
  var rejected = {};
  var count = document.getElementById("rejected-count");
  function key(s, h) { return s + ":" + h; }
  function refresh() {
    var n = Object.keys(rejected).length;
    count.textContent = n + (n === 1 ? " change rejected" : " changes rejected");
  }
  document.querySelectorAll(".hunk input").forEach(function (box) {
    box.addEventListener("change", function () {
      var hunk = box.closest(".hunk");
      var k = key(hunk.dataset.seg, hunk.dataset.hunk);
      if (box.checked) { delete rejected[k]; } else { rejected[k] = true; }
      hunk.classList.toggle("rejected", !box.checked);
      refresh();
    });
  });
  function segmentText(seg) {
    var a = seg.original.split(/\\s+/).filter(Boolean);
    var b = seg.enhanced.split(/\\s+/).filter(Boolean);
    var words = [], pos = 0;
    seg.hunks.forEach(function (h, i) {
      words = words.concat(b.slice(pos, h["new"][0]));
      words = words.concat(rejected[key(seg.index, i)]
        ? a.slice(h.orig[0], h.orig[1]) : b.slice(h["new"][0], h["new"][1]));
      pos = h["new"][1];
    });
    return words.concat(b.slice(pos)).join(" ");
  }
  document.getElementById("download").addEventListener("click", function () {
    var text = doc.segments.map(segmentText).join("\\n") + "\\n";
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    link.download = document.body.dataset.reviewed;
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
  document.getElementById("accept-unflagged").addEventListener("click", function () {
    document.querySelectorAll(".hunk:not(.flagged) input").forEach(function (box) {
      if (!box.checked) { box.checked = true; box.dispatchEvent(new Event("change")); }
    });
  });
  var main = document.querySelector("main");
  document.querySelectorAll("[data-filter]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var only = btn.dataset.filter === "unsure";
      main.classList.toggle("only-unsure", only);
      document.querySelectorAll("[data-filter]").forEach(function (b) {
        b.setAttribute("aria-pressed", String(b === btn));
      });
    });
  });
  refresh();
})();
"""


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _badges(flags: List[str]) -> str:
    out = []
    if AI_UNSURE in flags:
        out.append('<span class="badge ai">%s</span>' % LABELS[AI_UNSURE])
    if UNCLEAR_AUDIO in flags:
        out.append('<span class="badge audio">%s</span>' % LABELS[UNCLEAR_AUDIO])
    return " ".join(out)


def _timestamp(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    hours, rest = divmod(seconds, 3600)
    if hours:
        return "%d:%02d:%02d" % (hours, rest // 60, rest % 60)
    return "%02d:%02d" % (rest // 60, rest % 60)


def _time_link(url: str, ms: int) -> str:
    label = _timestamp(ms)
    if not url.startswith("https://"):
        return '<span class="time">%s</span>' % label
    sep = "&" if "?" in url else "?"
    href = "%s%st=%ds" % (url, sep, max(0, int(ms)) // 1000)
    return '<a class="time" href="%s">%s</a>' % (_e(href), label)


def _kept_unclear(seg: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {
        f["word"]: f
        for f in seg.get("flags") or []
        if f.get("kind") == UNCLEAR_AUDIO
        and not f.get("changed")
        and isinstance(f.get("word"), int)
    }


def _plain(words: List[str], first_orig: int, kept: Dict[int, Dict[str, Any]]) -> List[str]:
    """Unchanged words; ``first_orig`` is the original index of ``words[0]``."""
    out = []
    for k, word in enumerate(words):
        flag = kept.get(first_orig + k)
        if flag is None:
            out.append(_e(word))
        else:
            score = flag.get("score")
            tip = "Unclear audio, left unchanged"
            if isinstance(score, (int, float)):
                tip += " (score %.2f)" % score
            out.append('<mark class="audio" title="%s">%s</mark>' % (_e(tip), _e(word)))
    return out


def _segment_html(seg: Dict[str, Any], url: str) -> str:
    b = seg["enhanced"].split()
    kept = _kept_unclear(seg)
    parts: List[str] = []
    a_pos = b_pos = 0
    for h, hunk in enumerate(seg["hunks"]):
        i2 = hunk["orig"][1]
        j1, j2 = hunk["new"]
        parts += _plain(b[b_pos:j1], a_pos, kept)
        flags = list(hunk.get("flags") or [])
        cls = ["hunk"]
        if AI_UNSURE in flags:
            cls.append("flag-ai")
        if UNCLEAR_AUDIO in flags:
            cls.append("flag-audio")
        if flags:
            cls.append("flagged")
        inner = ""
        if hunk["orig_text"]:
            inner += "<del>%s</del>" % _e(hunk["orig_text"])
        if hunk["orig_text"] and hunk["new_text"]:
            inner += " "
        if hunk["new_text"]:
            inner += "<ins>%s</ins>" % _e(hunk["new_text"])
        badges = _badges(flags)
        parts.append(
            '<span class="%s" data-seg="%d" data-hunk="%d">%s%s'
            '<label><input type="checkbox" checked> keep</label></span>'
            % (" ".join(cls), seg["index"], h, inner, (" " + badges) if badges else "")
        )
        a_pos, b_pos = i2, j2
    parts += _plain(b[b_pos:], a_pos, kept)
    needs_look = any(hk.get("flags") for hk in seg["hunks"]) or bool(kept)
    kept_line = ""
    if kept:
        words = ", ".join(_e(f.get("text", "")) for _, f in sorted(kept.items()))
        kept_line = (
            '<p class="kept"><span class="badge audio">Unclear audio</span> '
            "Unchanged, check against the audio: %s</p>" % words
        )
    return '<section class="seg%s" id="s%d">%s<p class="text">%s</p>%s</section>' % (
        " needs-look" if needs_look else "",
        seg["index"],
        _time_link(url, seg.get("start_ms", 0)),
        " ".join(parts),
        kept_line,
    )


def render_report(review: Dict[str, Any], reviewed_name: str = "transcript.reviewed.txt") -> str:
    """The HTML report for a review document."""
    stats = review.get("stats") or {}
    title = review.get("title") or "Transcript"
    url = review.get("url") or ""
    shown = [s for s in review.get("segments") or [] if s.get("hunks") or _kept_unclear(s)]
    summary = "%d of %d segments changed, %d with unsure spots." % (
        stats.get("changed", 0),
        stats.get("segments", 0),
        stats.get("flagged", 0),
    )
    notes = []
    if not stats.get("has_ai_confidence", stats.get("has_confidence")):
        notes.append(
            "The rewrite gave no confidence information, so no change is marked AI unsure."
        )
    if not stats.get("has_audio_confidence"):
        notes.append(
            "No speech recognition scores (for example, YouTube captions), so nothing is marked Unclear audio."
        )
    body = (
        "\n".join(_segment_html(s, url) for s in shown)
        or '<p class="note">The rewrite changed nothing.</p>'
    )
    data = json.dumps(review, ensure_ascii=False).replace("</", "<\\/")
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review: %(title)s</title>
<style>%(css)s</style>
</head>
<body data-reviewed="%(reviewed)s">
<main>
<h1>Review: %(title)s</h1>
<p class="summary">%(summary)s Enhanced → Reviewed</p>
%(notes)s<div class="legend"><span><span class="badge ai">AI unsure</span> the rewrite model doubted its own edit</span>
<span><span class="badge audio">Unclear audio</span> the speech recognition was unsure what was said</span></div>
<div class="controls">
<button type="button" data-filter="all" aria-pressed="true">All changes</button>
<button type="button" data-filter="unsure" aria-pressed="false">Only unsure</button>
<button type="button" id="accept-unflagged">Accept all without unsure marks</button>
</div>
%(body)s
</main>
<div class="bar"><span id="rejected-count"></span>
<button type="button" class="primary" id="download">Download Reviewed</button></div>
<script type="application/json" id="review-data">%(data)s</script>
<script>%(js)s</script>
</body>
</html>
""" % {
        "title": _e(title),
        "css": _CSS,
        "reviewed": _e(reviewed_name),
        "summary": _e(summary),
        "notes": "".join('<p class="note">%s</p>\n' % _e(n) for n in notes),
        "body": body,
        "data": data,
        "js": _JS,
    }
