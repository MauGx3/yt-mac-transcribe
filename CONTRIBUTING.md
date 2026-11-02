# Contributing

Thanks for improving `yt-transcribe`. The project is intentionally small and dependency-free so that contributors can run it easily on macOS and other Python 3.8+ systems.

## Before opening a change

1. Read [`docs/development.md`](docs/development.md).
2. Open an issue for behavior changes or larger design changes.
3. Keep changes focused and explain user-visible behavior in the pull request.
4. Do not commit downloaded audio, Whisper models, cache files, generated transcripts, or credentials.

## Development checklist

From a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python3 tests/test_parsing.py
python3 tests/test_tracks.py
python3 tests/test_cache.py
```

For changes that touch the network or performance path, run the relevant live command manually and document the video type used. Live tests are not a substitute for deterministic unit tests.

## Adding or changing behavior

- Add or update a focused test near the code it covers.
- Prefer standard library code unless a dependency provides a clear benefit.
- Keep YouTube-specific behavior in `youtube.py` and parsing behavior in `captions.py` / `segments.py`.
- Preserve provenance and warnings in the `Transcript` model when adding a new source or fallback.
- Keep CLI output stable and update the README when flags or defaults change.
- Treat caption payloads as untrusted input: handle malformed JSON, VTT, SRT, empty events, and unexpected fields.

## Pull requests

A pull request should include:

- What changed and why
- How it was tested
- Any change to CLI output, file naming, cache behavior, or dependencies
- A note about network testing when applicable

Keep the pull request small enough to review. Add a regression test when fixing a parser, track-selection, timing, cache, or formatter bug.

## Commit messages

Use a short imperative subject, for example:

```text
Fix rolling caption deduplication
Add cache expiry coverage
Document ASR fallback setup
```

## License

By contributing, you agree that your contributions are provided under the MIT license.
