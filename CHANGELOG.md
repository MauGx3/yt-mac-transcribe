# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

<!-- [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review. -->

## [Unreleased]

### Added

- macOS app: **Library** tab with transcript history, search by title, URL or
  transcript text, and open / show in Finder / remove actions.
- macOS app: **Playlist** and **Batch** input modes backed by `ytt --playlist`
  and multiple URLs.
- macOS app: output format choice (txt, srt, vtt, json, md; several at once).

### Known limits

- Reviewed copies (local rewrite) are only offered for single videos.

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
