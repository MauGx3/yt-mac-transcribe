# yt-transcribe (`ytt`)

Fast YouTube transcripts for macOS, especially Apple silicon. `ytt` uses YouTube's own caption tracks by default and uses local `whisper.cpp` only when captions are missing or fail a quality check.

- Fast caption path: no audio download, `ffmpeg`, or model required
- Local ASR fallback for videos without usable captions
- Outputs `txt`, `srt`, `vtt`, `json`, and `md`
- Batch and playlist support
- Metadata and caption caching to reduce repeat requests
- No third-party Python runtime dependencies

## Quick start

### Install runtime dependencies

```bash
brew install yt-dlp
```

The local ASR fallback is optional:

```bash
brew install ffmpeg whisper-cpp
whisper-cpp-download-ggml-model small.en
```

### Install `ytt`

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### Generate a transcript

```bash
ytt https://youtu.be/aircAruvnKk
ytt https://youtu.be/aircAruvnKk -f srt vtt json md
ytt https://youtu.be/aircAruvnKk --timestamps -o ~/Documents
ytt --batch urls.txt -o transcripts/
```

See [`docs/development.md`](docs/development.md) for the contributor setup, architecture, test strategy, debugging workflow, and release checklist.

## How it works

```text
yt-dlp -J
    │
    ├── metadata
    └── caption-track URLs
          │
          ├── manual captions
          ├── YouTube ASR captions
          └── machine translations
                    │
             fetch json3/VTT/SRT
                    │
             parse → dedupe → repair timings
                    │
             quality check → local ASR fallback when needed
                    │
             render txt/SRT/VTT/JSON/Markdown
```

The caption path is intentionally the default. YouTube caption tracks are usually much faster and lighter than downloading audio and running a local model. The fallback remains available for videos with no usable track, disabled captions, or unsupported language coverage.

## Usage

```text
ytt [URL ...] [options]

  -f, --format FMT ...     txt srt vtt json md            (default: txt)
  -o, --out PATH           output directory or explicit file path
  -l, --langs LIST         language preference, e.g. pt,en (default: en)
  -m, --model NAME         whisper.cpp fallback model (default: small.en)
      --asr {never,auto,always}
                           auto uses captions then escalates when needed
      --timestamps         add [mm:ss] to txt/md output
      --raw                keep one line per cue
      --drop-sound-tags    remove [Music], (applause), and similar tags
      --list-tracks        list available tracks and exit
      --batch FILE         read URLs from a file
      --playlist           expand playlist URLs
      --delay SECS         pause between videos (default: 1.0)
      --retries N          retry failed videos (default: 1)
      --no-cache            bypass the on-disk cache
      --cache-ttl SECS     cache lifetime in seconds (default: 604800)
      --clear-cache        delete cached payloads and exit
      --cookies-from-browser BROWSER
                           use browser cookies through yt-dlp
  -q, --quiet / -v, --verbose / --stats / --version
```

`--out` is treated as a directory unless it ends in a known output extension. For example, `-o transcripts` creates a directory target even when it does not exist yet.

## Output formats

- **`txt`**: readable paragraphs without timestamps by default.
- **`srt` / `vtt`**: standard subtitle files with repaired, non-overlapping cues.
- **`json`**: segment timings, optional word timings, metadata, warnings, and provenance.
- **`md`**: metadata followed by timestamped transcript paragraphs.

Each transcript records whether it came from manual captions, YouTube ASR, a machine translation, or local Whisper.

## Performance model

On the reference 18-minute video, the caption path took about 2.4 seconds in the original benchmark, while a local Whisper pass took roughly 1–4 minutes depending on the model. Repeated runs use the cache and are much faster.

Run the benchmark locally when changing network, parsing, or cache behavior:

```bash
python3 tests/benchmark.py
```

These numbers depend on the video, network, `yt-dlp`, model, and machine. Treat them as a comparison guide rather than a fixed guarantee.

## Tests

The project uses Python's standard library `unittest` module and has no test dependency to install.

```bash
python3 tests/test_parsing.py
python3 tests/test_tracks.py
python3 tests/test_cache.py
```

The first three commands are network-free unit tests. These scripts exercise parsing, rolling-window deduplication, timing repair, quality checks, formatters, track selection, output paths, and cache behavior.

Optional live checks:

```bash
python3 tests/sweep.py 16
python3 tests/benchmark.py
```

Live checks access YouTube and may be affected by rate limits. Read the development guide before running them in automation.

## Known limits

- YouTube may throttle bursts of caption requests. Use `--delay`, caching, and browser cookies when appropriate.
- Auto captions inherit speech-recognition errors, especially for names and accents. Use `--asr always` when local transcription is preferred.
- Videos without usable captions require the optional ASR toolchain.
- YouTube translations are machine-generated; prefer the original language when it is available.
- `live_chat` is excluded because its payload is not a subtitle track.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution checklist and [`docs/development.md`](docs/development.md) for the technical details.

## License

MIT
