# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

<!-- [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review. -->

## [Unreleased]

### Added

- `ytt demo`: benchmarks speech-to-text engines and models and MLX-LM cleanup
  models on a copyright-free sample voiced on the Mac, recommends a model for
  each, and saves the choice to `~/.config/ytt/config.json` as the new
  default. See `docs/demo.md`.
- macOS app: Benchmark tab that runs `ytt demo` and applies the chosen models.
- `tools/rewrite_with_local_model.py`: MLX-LM runner for `--rewrite-command`,
  referenced by the README but previously missing.
- Review file: a rewrite now also writes `<name>.review.json` with a word-level
  diff of original vs enhanced text, and rewrite protocol v2 lets a runner report
  uncertain spans per segment. Groundwork for the app's diff review screen.
- `tools/rewrite_with_local_model.py` reports changed words the model was unsure
  about (`--unsure-below`, default 0.5) from MLX-LM token probabilities.
- macOS app: after an AI enhancement, a review screen shows each change with
  Accept/Reject, labels "AI unsure" and "Unclear audio" spots, and saves the
  final `<name>.reviewed.txt`. The AI output is now called "Enhanced".
- macOS Library: enhanced transcripts show "Needs review" or "Reviewed", with
  buttons to reopen the review screen and the Reviewed copy.
- "Unclear audio" labels from real data: whisper.cpp (`-ojf`) and mlx-whisper
  (`--word-timestamps True`) word confidence is kept as `conf` in JSON output,
  and the review file marks words under 0.5, both those the AI changed and those
  it left alone.
- HTML review report: every rewrite also writes `<name>.review.html`, a
  self-contained page with both labels, keep/reject per change, and a
  "Download Reviewed" button. `ytt --review-report FILE` rebuilds it.

### Changed

- A batch or playlist run where some videos fail now exits `3` instead of `0`.
  The macOS app accepts `3` for batch and playlist runs and keeps the
  transcripts that were written.

## [0.1.0] - 2026-11-03

First packaged release: the `ytt` command-line transcriber and a native macOS app.

### Added

- `ytt` CLI: YouTube transcripts from caption tracks, with optional local
  whisper.cpp fallback. Outputs txt, srt, vtt, json, and md.
- Local context-aware rewriting via `--rewrite-command`, preserving original outputs.
- SwiftUI macOS app (`macos/YTTranscribeApp`) for one-URL transcription, with an
  optional reviewed copy.
- The app bundles `ytt` as a self-contained `ytt.pyz` zipapp
  (`macos/YTTranscribeApp/scripts/bundle-ytt.sh`). Users only need `yt-dlp`
  installed.
- GitHub Actions CI: Python 3.8 and 3.12 unit tests and an XCTest build on macOS.

### Changed

- The app launches `ytt` with Homebrew directories on `PATH`, so `yt-dlp`
  resolves when the app is opened from Finder.

### Known limits

- Requires `yt-dlp` on the system (`brew install yt-dlp`).
- Requires `python3` at build time to package `ytt`.
- The app is unsigned and not notarized. Gatekeeper requires right-click → Open on first launch.
- YouTube may rate-limit bursts of caption requests.
