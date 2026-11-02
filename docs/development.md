# Development guide

This guide explains how to work on `yt-transcribe` without needing to reconstruct the project from the user README.

## Project goals

`yt-transcribe` optimizes for fast, low-resource YouTube transcripts on macOS, including Apple silicon:

1. Reuse YouTube's caption tracks whenever they are usable.
2. Keep the common path free of audio downloads, `ffmpeg`, model downloads, and Python packages.
3. Fall back to local `whisper.cpp` for videos that need actual audio transcription.
4. Produce deterministic, useful transcript formats with provenance and repaired timings.

Changes should preserve these goals unless the change explicitly revises the product direction.

## Supported environment

- Python 3.8 or newer
- macOS is the primary development platform
- Apple silicon is the target performance platform
- `yt-dlp` is required at runtime
- `ffmpeg` and `whisper.cpp` are required only for local ASR
- Runtime Python dependencies are intentionally empty

The package is installed from a `src/` layout. The console command is declared in `pyproject.toml`:

```text
ytt = ytt.cli:main
```

## Local setup

```bash
git clone https://github.com/MauGx3/yt-transcribe.git
cd yt-transcribe

brew install yt-dlp

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Verify the installation:

```bash
ytt --version
ytt --help
```

Install the optional ASR toolchain only when you need it:

```bash
brew install ffmpeg whisper-cpp
whisper-cpp-download-ggml-model small.en
```

The package itself does not download models. The model name passed to `--model` must be available to the installed `whisper-cpp` command.

## Repository layout

```text
.
├── README.md
├── CONTRIBUTING.md
├── pyproject.toml
├── src/ytt/
│   ├── __main__.py     # python -m ytt entry point
│   ├── __init__.py     # package version
│   ├── cli.py          # argument parsing and end-to-end orchestration
│   ├── youtube.py      # yt-dlp, track discovery, selection, and fetching
│   ├── captions.py     # json3, VTT, SRT, and Whisper JSON parsers
│   ├── segments.py     # shared model cleanup, deduplication, timing repair
│   ├── model.py        # Transcript model and provenance fields
│   ├── formatter.py    # txt, SRT, VTT, JSON, and Markdown output
│   ├── cache.py        # filesystem metadata and caption cache
│   ├── asr.py          # optional whisper.cpp integration
│   └── util.py         # logging, timing, filenames, and small helpers
└── tests/
    ├── test_parsing.py # parser, cleanup, quality, formatter, and utility tests
    ├── test_tracks.py  # track selection and output-path tests
    ├── test_cache.py   # cache tests
    ├── sweep.py        # optional live robustness sweep
    └── benchmark.py    # optional live performance comparison
```

## Runtime pipeline

The main flow starts in `ytt.cli.main()`:

1. Parse CLI arguments and create the cache and logger.
2. Collect direct URLs and optional batch-file URLs.
3. Expand playlists when requested.
4. For each video, call `process_one()`.
5. `YouTube.metadata()` runs `yt-dlp -J --skip-download` to obtain metadata and caption URLs in one call.
6. `YouTube.tracks()` converts the metadata dictionaries into `Track` objects and removes unsupported pseudo-tracks such as `live_chat`.
7. `YouTube.pick_track()` selects a source by tier: manual captions, original YouTube ASR, then machine translation.
8. `YouTube.fetch_track()` fetches the preferred caption format directly and validates it through `parse_any()`.
9. The parser creates `Segment` and optional `Word` objects.
10. `clean_segments()` normalizes text, removes rolling-window duplicates, and repairs cue timings.
11. `quality_report()` decides whether the result is usable. Problems trigger local ASR when `--asr auto` is active.
12. `formatter.render()` writes the requested output formats.

The important boundary is that formatters consume cleaned `Segment` objects. Parser and cleanup changes should not need to know how SRT, VTT, JSON, or Markdown are rendered.

## Caption data model

### `Track`

`youtube.Track` describes one candidate source:

- `lang`: YouTube language identifier
- `name`: display name
- `kind`: `manual`, `auto`, or `auto-translated`
- `formats`: supported payload formats
- `urls`: format-to-URL mapping

Track selection is deliberately tiered. A matching manual track wins over an automatic track, and an original automatic track wins over a translation. Language matching honors exact language, base language, and region variants.

### `Segment`

`segments.Segment` is the common unit passed through the rest of the application:

- `start_ms`
- `end_ms`
- `text`
- optional word timings in `words`

Every parser should return segments that can safely pass through `clean_segments()`. Downstream code expects ordered, non-empty, non-overlapping output.

### `Transcript`

`model.Transcript` combines the cleaned segments with video metadata and provenance. When adding another transcription source, preserve the engine/source fields and append meaningful warnings instead of hiding fallback behavior.

## Parser and cleanup rules

YouTube's modern `json3` captions can be rolling windows: a later event may repeat the previous event or extend it with more words. The parser skips newline marker events (`aAppend`), then shared cleanup:

- normalizes whitespace and invisible characters
- removes empty and punctuation-only cues
- drops adjacent exact duplicates
- replaces a shorter prefix with a longer grown window
- clamps overlaps before subtitle output
- synthesizes a short duration for zero-length cues

Do not solve these rules separately in each formatter. If a new caption shape fails, add a fixture and fix the shared parser/cleanup layer.

When a payload format is added:

1. Add it to `CAPTION_FORMATS` and the preferred order only if it is actually supported.
2. Implement parsing in `captions.py`.
3. Keep `parse_any()` format detection explicit.
4. Add malformed, empty, and representative real-shape fixtures.
5. Verify word timings and overlap repair where the format carries timing data.

## Cache behavior

The default cache root is `~/.cache/yt-transcribe`. Metadata and caption payloads are stored separately with a seven-day TTL by default.

Use these commands while debugging cache behavior:

```bash
ytt https://youtu.be/aircAruvnKk --verbose
ytt https://youtu.be/aircAruvnKk --no-cache --verbose
ytt --clear-cache
```

The cache is keyed by request inputs so that different videos, languages, and track kinds do not collide. Do not commit cache contents or make tests depend on a developer's home directory.

## Test strategy

The test suite uses `unittest` directly, so the tests run without installing a test framework:

```bash
python3 tests/test_parsing.py
python3 tests/test_tracks.py
python3 tests/test_cache.py
```

Run all network-free tests together:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Test categories:

| Area | File | What it protects |
|---|---|---|
| Parsing and cleanup | `tests/test_parsing.py` | json3/VTT/SRT/Whisper shapes, dedupe, timing repair, quality checks |
| Formatting | `tests/test_parsing.py` | text, SRT, VTT, JSON, and Markdown output |
| Track selection | `tests/test_tracks.py` | language preference, source tiers, translations, pseudo-track filtering |
| Output paths | `tests/test_tracks.py` | directory targets, explicit files, multi-video IDs |
| Cache | `tests/test_cache.py` | reads, writes, TTL, disabled mode, clearing |
| Live robustness | `tests/sweep.py` | parser crashes, overlaps, duplicates, quality false positives |
| Performance | `tests/benchmark.py` | caption path timing and ASR comparison |

For a bug fix, first reproduce it with a deterministic fixture. Add a live test only when the behavior cannot be represented without YouTube.

## Live debugging

Use verbose logging to inspect subprocesses, cache hits, selected tracks, payload formats, timing, and fallback decisions:

```bash
ytt URL --verbose --stats
```

Useful diagnostic commands:

```bash
ytt URL --list-tracks --verbose
ytt URL --asr never --no-cache --verbose
ytt URL --asr always --model small.en --verbose
```

Interpret failures in this order:

1. Confirm `yt-dlp` is installed and can read the URL.
2. Run `--list-tracks` to distinguish missing captions from parser failures.
3. Use `--asr never` to isolate the caption path.
4. Use `--no-cache` to eliminate stale metadata or payloads.
5. Use `--asr always` to isolate the local ASR toolchain.
6. Check for YouTube HTTP 429 throttling before changing parser logic.

Do not paste cookies, signed caption URLs, or private video metadata into issues.

## Making changes safely

### CLI changes

Update `build_parser()`, add a focused test for parsing or behavior, and update the usage section in `README.md`.

### Track-selection changes

Keep source priority and language behavior in `YouTube.pick_track()`. Add tests for exact language, region variants, unmatched languages, and translation fallback.

### Parser changes

Keep parsing format-specific code in `captions.py` and shared normalization in `segments.py`. Add fixtures for both the normal and malformed form of the input.

### Formatter changes

Formatters should consume `Transcript` and never make network requests. Preserve valid subtitle timing and provenance in JSON/Markdown output.

### ASR changes

Keep the optional path importable when `whisper.cpp` is absent. The caption-only path must continue to work with only `yt-dlp` installed.

### Cache changes

Test cache hits, misses, expiration, disabled mode, and clearing. Avoid tests that write to the real user cache; use a temporary directory or the cache's injected root if available.

## Performance work

The dominant caption-path cost is usually metadata extraction through `yt-dlp`; parsing is expected to be small. When measuring a change:

1. Clear or isolate the cache.
2. Run the same video and language settings.
3. Record whether the run used manual, automatic, translated, or local ASR output.
4. Repeat enough times to separate network variance from code changes.
5. Include machine, Python, `yt-dlp`, and model versions in the report.

Use `tests/benchmark.py` as a starting point, but avoid relying on one network measurement as a regression threshold.

## Release checklist

1. Run all network-free tests.
2. Run `ytt --version` from an editable install.
3. Review `README.md`, `CONTRIBUTING.md`, and this guide for changed defaults or flags.
4. Run one manual caption example and one output-format example.
5. If ASR code changed, run one local fallback example with a known model.
6. Check `git diff` for cache files, generated transcripts, credentials, and unrelated changes.
7. Update `version` in `pyproject.toml` and `src/ytt/__init__.py` together.
8. Record user-visible changes in the release notes or pull request.

## Design constraints to preserve

- Keep the common path fast and lightweight.
- Keep Python runtime dependencies at zero unless the project direction changes.
- Keep network access in the YouTube layer.
- Keep cleanup rules shared by all input sources.
- Keep output formatters independent of network and ASR tools.
- Keep the local ASR fallback optional.
- Keep provenance visible in generated output.
