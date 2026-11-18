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

`ytt --model small.en` looks for `small.en` or `ggml-small.en.bin` in these
folders, in order:

1. `$YTT_MODEL_DIR`, if set
2. the current folder, then `./models`
3. `~/.cache/whisper`, then `~/.cache/whisper.cpp`
4. `/opt/homebrew/share/whisper-cpp` and its `models` subfolder
5. `/usr/local/share/whisper-cpp` and its `models` subfolder

You can also pass the file path directly with `--model`.

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
      --no-cache           bypass the on-disk cache
      --cache-ttl SECS     cache lifetime in seconds (default: 604800)
      --clear-cache        delete cached payloads and exit
      --cookies-from-browser BROWSER
                           use browser cookies through yt-dlp
      --rewrite-command CMD ...
                           run a local context-aware model after transcription
      --rewrite-timeout SECS
                           local rewrite timeout (default: 300)
  -q, --quiet / -v, --verbose / --stats / --version
```

`--out` is treated as a directory unless it ends in a known output extension. For example, `-o transcripts` creates a directory target even when it does not exist yet.

## Output formats

- **`txt`**: readable paragraphs without timestamps by default.
- **`srt` / `vtt`**: standard subtitle files with repaired, non-overlapping cues.
- **`json`**: segment timings, optional word timings, metadata, warnings, and provenance.
- **`md`**: metadata followed by timestamped transcript paragraphs.

Each transcript records whether it came from manual captions, YouTube ASR, a machine translation, or local Whisper.

## Local context-aware rewriting

Use `--rewrite-command` to run a local language model after transcription. The model receives the full transcript with neighboring segment context and returns corrected text while `ytt` preserves the original timings. The original and rewritten files are saved together:

```bash
ytt https://youtu.be/aircAruvnKk -f txt srt json \
  --rewrite-command python3 tools/rewrite_with_local_model.py
```

For `video.srt`, the companion file is `video.rewritten.srt`. The original is never replaced, and it is written before the rewriter runs. `--rewrite-command` must be the last option; every argument after it goes to the runner. The runner must read JSON from stdin and write exactly `{"segments": [{"text": "..."}, ...]}` to stdout. `tools/rewrite_with_local_model.py` is a bundled MLX-LM runner (`python3 -m pip install mlx-lm` first; pick a model with `--model`). Any other local runtime, such as llama.cpp or Ollama, can be wrapped the same way. See [`docs/local-rewriting.md`](docs/local-rewriting.md) for the complete protocol and failure behavior.

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
python3 tests/test_rewriter.py
```

The first four commands are network-free unit tests. Optional live checks:

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

## Native macOS app

A small SwiftUI wrapper is available in [`macos/YTTranscribeApp`](macos/YTTranscribeApp/README.md). It accepts one YouTube URL, creates the original text transcript, then asks whether to create a locally reviewed copy. The original and reviewed files are saved together; the app can open either file or reveal them in Finder.

Open `macos/YTTranscribeApp/YTTranscribeApp.xcodeproj` in Xcode and build the `YTTranscribeApp` scheme. The `ytt` CLI is bundled into the app at build time, so only `yt-dlp` needs to be installed separately. Optionally set a local rewrite command in the app’s Settings. The app targets macOS 13 or newer on Apple silicon and bundles no model.

Version 0.1.0 is described in [`CHANGELOG.md`](CHANGELOG.md).
