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
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

These are the same network-free tests CI runs on Python 3.8 and 3.12. If you
changed the macOS app, also run its XCTest suite (see the
[app README](macos/YTTranscribeApp/README.md#development)).

## Linting and formatting

The repository uses [pre-commit](https://pre-commit.com) to run ruff (Python lint and format), codespell, shellcheck, actionlint, swift-format, and a few file hygiene checks. Install it once and enable the git hook:

```bash
uv tool install pre-commit   # or: pipx install pre-commit
pre-commit install
pre-commit run --all-files   # optional: check the whole tree
```

The same hooks run on every pull request in the `Lint` CI job and on pre-commit.ci. The swift-format hook needs Xcode 16 or later and only runs on macOS. Ruff settings live in `pyproject.toml`, Swift settings in `.swift-format`.

For changes that touch the network or performance path, run the relevant live command manually and document the video type used. Live tests are not a substitute for deterministic unit tests.

## Adding or changing behavior

- Add or update a focused test near the code it covers.
- Prefer standard library code unless a dependency provides a clear benefit.
- Keep YouTube-specific behavior in `youtube.py` and parsing behavior in `captions.py` / `segments.py`.
- Preserve provenance and warnings in the `Transcript` model when adding a new source or fallback.
- Keep CLI output stable and update the README when flags or defaults change.
- Write user-facing docs for someone who has never used a terminal tool like this: say what a step does, show how to check it worked, and add new error messages to [`docs/troubleshooting.md`](docs/troubleshooting.md).
- Treat caption payloads as untrusted input: handle malformed JSON, VTT, SRT, empty events, and unexpected fields.

## Pull requests

A pull request should include:

- What changed and why
- How it was tested
- Any change to CLI output, file naming, cache behavior, or dependencies
- A note about network testing when applicable

Keep the pull request small enough to review. Add a regression test when fixing a parser, track-selection, timing, cache, or formatter bug.

## AI-generated code markers

Some files carry a `[AI-GENERATED]` comment. It marks code an AI assistant
wrote that has not yet had a line-by-line human review. When you review such a
block, remove its marker in the same pull request.

## Commit messages

Use a short imperative subject, for example:

```text
Fix rolling caption deduplication
Add cache expiry coverage
Document ASR fallback setup
```

## License

By contributing, you agree that your contributions are provided under the MIT license.
