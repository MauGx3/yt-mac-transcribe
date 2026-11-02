# yt-transcribe (`ytt`)

Fast, local YouTube transcripts. **Uses YouTube's own caption tracks by default** — no audio
download, no ffmpeg, no Whisper models. Local ASR is a fallback for the rare video that has no
usable captions.

```bash
ytt https://youtu.be/aircAruvnKk                      # transcript to ./<title>.txt
ytt https://youtu.be/aircAruvnKk -f srt vtt json md    # all formats at once
ytt https://youtu.be/aircAruvnKk --timestamps -o ~/Documents
ytt --batch urls.txt -o transcripts/                   # many videos
```

An 18-minute video transcribes in **~2 seconds**.

## Why captions instead of Whisper

The original plan (download audio → ffmpeg → whisper.cpp + Core ML) is the right tool for audio
that has no transcript. For YouTube it is mostly wasted work, because YouTube already publishes a
transcript for essentially every video, produced by Google's own ASR on far more compute than a
laptop has.

| | YouTube captions | Local Whisper |
|---|---|---|
| Wall time, 18-min video | **~2.4 s** (measured) | 1–4 min (model-dependent) |
| Wall time, repeat run | **~0.1 s** (cached) | still minutes |
| Dependencies | `yt-dlp` only | `yt-dlp` + `ffmpeg` + `whisper.cpp` + 0.5–3 GB model |
| Download size | **~45 KB** | 15–60 MB audio |
| Punctuation / casing | yes (auto captions) | model-dependent |
| Word-level timings | yes (`json3`) | yes |
| Accuracy on proper nouns | Google's ASR, usually stronger | depends on model |
| Works offline | no (needs the caption URL) | yes |
| CPU / battery | negligible | heavy (minutes of sustained load) |
| Videos with no captions | ✗ | ✓ |

Measured on the reference video (3Blue1Brown, 18:40): metadata 2.14 s + caption fetch 0.20 s +
parse 0.006 s = **2.35 s**, versus an estimated 99 s for `small.en` and 230 s for `medium.en` —
about **42x faster**, before counting the one-off model download. Metadata extraction, not
transcription, is now the dominant cost; `tests/benchmark.py` reproduces these numbers.

The trade-off is real but narrow: local ASR wins only for videos with no captions, captions
disabled by the uploader, or audio in a language YouTube doesn't auto-caption. So this tool treats
Whisper as a **fallback tier**, not the main path — and it verifies caption quality before trusting
it.

## How it works

```
yt-dlp -J  ──►  metadata + caption-track URLs   (one call, ~2 s)
                     │
                     ├─ prefer human-authored ("manual") captions
                     ├─ then YouTube ASR ("auto"), matching --langs
                     └─ then machine translations ("auto-translated")
                     │
             direct HTTP GET of the json3 track   (~50 KB, ~0.2 s)
                     │
             parse → dedupe → repair timings → format
                     │
             quality check ──► bad? escalate to local ASR
```

Two details make this reliable:

**Rolling-window dedupe.** Modern YouTube auto captions are not one line per cue. They re-emit a
sliding window of text, so a naive parser produces a transcript where every sentence appears two or
three times. The parser drops `aAppend` newline markers, removes adjacent duplicates, and keeps the
*longer* line when a window grows. A real example: 4,285 raw events → 709 clean segments.

**Timing repair.** Auto captions set each cue's duration to the whole window lifetime, so cues
overlap heavily. Overlapping cues are invalid in SRT and make players misbehave, so each cue is
clamped to end when the next begins.

**Quality gate.** Before trusting a caption track, the tool checks speech density (words/min), the
share of `[Music]`-style tags, and local vocabulary diversity. If the track is empty, tag-only, or
looks like a degenerate ASR loop, it escalates to Whisper automatically (`--asr auto`, the default).

**Caching.** Caption payloads and metadata are cached on disk (`~/.cache/yt-transcribe`, 7-day TTL).
Repeat runs take ~0.1 s instead of ~2.4 s, and re-running a batch costs no network calls — which
also sidesteps YouTube's throttling. `--no-cache`, `--cache-ttl`, and `--clear-cache` control it.

## Install

```bash
# required
brew install yt-dlp

# optional: only needed for the ASR fallback
brew install ffmpeg whisper-cpp
whisper-cpp-download-ggml-model small.en
```

Then:

```bash
cd yt-transcribe
pip install -e .          # installs the `ytt` command
# or run without installing:
PYTHONPATH=src python3 -m ytt <url>
```

Requires Python 3.8+. No third-party Python packages.

## Usage

```
ytt [URL ...] [options]

  -f, --format FMT ...     txt srt vtt json md            (default: txt)
  -o, --out PATH           output directory, or an explicit file path
  -l, --langs LIST         language preference, e.g. pt,en  (default: en)
  -m, --model NAME         whisper.cpp model for the fallback (default: small.en)
      --asr {never,auto,always}
                           auto = use captions, escalate only if unusable (default)
      --timestamps         prefix [mm:ss] in txt/md
      --raw                no paragraph reflow; one line per cue
      --drop-sound-tags    remove [Music], (applause), ...
      --list-tracks        show available caption tracks and exit
      --batch FILE         read URLs from a file (# comments allowed)
      --playlist           expand playlist URLs into individual videos
      --delay SECS         pause between videos (default: 1.0)
      --retries N          retry a failed video N times (default: 1)
      --no-cache           bypass the on-disk caption/metadata cache
      --cache-ttl SECS     cache lifetime (default: 604800)
      --clear-cache        delete cached payloads and exit
      --cookies-from-browser BROWSER
                           for age- or region-restricted videos
      --rewrite-command CMD ...
                           run a local context-aware model after transcription
      --rewrite-timeout SECS
                           local rewrite timeout (default: 300)
  -q, --quiet / -v, --verbose / --stats / --version
```

`--out` is treated as a directory unless it ends in a known output extension, so
`-o transcripts` works before the directory exists.

## Output

`txt` — paragraphs, no timestamps by default. Meant for reading, feeding to an LLM, or grepping.

```
This is a 3. It's sloppily written and rendered at an extremely low resolution of 28x28 pixels,
but your brain has no trouble recognizing it as a 3. That's because of how you and I see the world.
```

`srt` / `vtt` — standard subtitle files, word-wrapped to two lines per cue, no overlaps.

`json` — full fidelity: per-segment timings, optional per-word timings from `json3`, plus metadata
and a `source` block recording whether the text came from human captions, YouTube ASR, a
translation, or local Whisper.

`md` — a front-matter-ish header (source, channel, duration, provenance) plus timestamped
paragraphs.

Every transcript records its provenance, so you always know whether you are reading
human-authored captions, machine-generated ones, or a local Whisper pass.

## Local context-aware rewriting

Use `--rewrite-command` to run a local language model after transcription. The model receives the
full transcript with neighboring segment context and returns corrected text while `ytt` preserves
the original timings. The original and rewritten files are saved together:

```bash
ytt https://youtu.be/aircAruvnKk -f txt srt json \\
  --rewrite-command python3 tools/rewrite_with_local_model.py
```

For `video.srt`, the companion file is `video.rewritten.srt`. The original is never replaced. The
runner must read JSON from stdin and write exactly `{"segments": [{"text": "..."}, ...]}` to stdout.
It can call any local Apple silicon runtime, such as an MLX, llama.cpp, or Ollama based runner.
See [`docs/local-rewriting.md`](docs/local-rewriting.md) for the complete protocol and failure
behavior.

## Tests

```bash
python3 tests/test_parsing.py     # parsers, cleanup, formatters
python3 tests/test_tracks.py      # caption-track selection and output paths
python3 tests/test_cache.py       # cache behaviour
python3 tests/test_rewriter.py    # local context-aware rewriting
python3 tests/sweep.py 16         # live robustness sweep over varied videos
python3 tests/benchmark.py        # measured caption-path timings vs ASR estimates
```

68 unit tests cover both caption styles (static and rolling-window), VTT/SRT fallbacks, dedupe,
timing repair, the quality gate, every formatter, track selection, and the cache. The sweep checks real videos for parser
crashes, cue overlaps, adjacent duplicates, and false-positive quality flags.

## Known limits

- **Rate limiting.** YouTube throttles bursts of `timedtext` requests. The tool detects 429s,
  backs off, retries, and tells you to wait or pass `--cookies-from-browser`. Batch runs space
  requests out via `--delay`.
- **Auto captions inherit Google's errors**, especially on proper nouns and heavy accents. For
  critical accuracy on a specific video, `--asr always` re-transcribes with Whisper.
- **No captions at all** (music-only uploads, some livestreams, uploader-disabled captions)
  requires the ASR tier.
- **Translations are machine-made.** `-l pt` on an English video gives YouTube's translated track,
  which is lower quality than the original — prefer `-l pt,en` so the original wins when available.
- The `live_chat` pseudo-track is excluded; its payload is HTML, not subtitles.
