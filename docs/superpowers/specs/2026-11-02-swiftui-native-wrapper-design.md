# SwiftUI native wrapper design

## Intent

Provide a small native macOS front end for `yt-transcribe` so a user can enter one YouTube URL, generate the normal transcript, and choose whether to generate and use a reviewed version from a local model.

## Goals

- Native SwiftUI macOS app for macOS 13 and newer, targeting Apple silicon.
- Accept and process one URL per run.
- Invoke the existing `ytt` executable; keep transcription and rewriting logic in Python.
- Save the original transcript and, if requested, the `.rewritten` companion beside it.
- Ask after the original transcript is generated: “Would you like to create a reviewed version using your local model?”
- Show progress, command errors, and output paths in the app.
- Let the user open either transcript in the default editor or reveal it in Finder.
- Add no external Swift package dependencies and bundle no model.

## Non-goals

- Batch URLs, playlist processing, transcript editing, model downloads, and model selection UI.
- Reimplementing transcription, caption parsing, or rewriting in Swift.
- Supporting Intel macOS in this first version.

## Approaches considered

1. **SwiftUI app launching `ytt`** — selected. It reuses the tested CLI and existing local rewrite protocol, keeps the native layer small, and provides a platform-native interaction.
2. AppKit menu bar utility — small footprint, but a less natural home for a URL-to-transcript workflow and review prompt.
3. Shell or AppleScript wrapper — quick to prototype, but weaker native interaction and packaging.

## User flow

1. User enters one YouTube URL and selects **Transcribe**.
2. App validates that the field is non-empty and starts one `ytt URL -f txt -o <output directory>` process.
3. App displays progress and retains stdout/stderr for status and errors.
4. After success, app asks whether to create a reviewed version.
5. If declined, the original is available to open or reveal in Finder.
6. If accepted, app runs `ytt URL -f txt -o <output directory> --rewrite-command <configured command...>`; the CLI produces original and `.rewritten.txt` outputs.
7. App shows both paths and offers **Open Original**, **Open Reviewed**, and **Show in Finder** actions.

The app will not run transcription and rewriting concurrently: rewriting itself invokes the CLI transcription path, and repeated calls normally reuse the CLI cache. The initial transcription is retained so the user can decline review without triggering a model call.

## Local command configuration

- Resolve the `ytt` executable from a user-configured path in app settings, falling back to `ytt` on `PATH`.
- Resolve the rewrite command from `YTT_REWRITE_COMMAND` first, then an editable app setting.
- Parse command settings into executable plus argument array; never pass a shell command string to `/bin/sh`.
- Persist output directory and executable settings using `UserDefaults`.
- The output directory defaults to `~/Documents/yt-transcribe`.

## Architecture

- `YTTranscribeApp.swift`: app entry point and app model lifecycle.
- `ContentView.swift`: URL form, progress, review confirmation, and output actions.
- `TranscriptionRunner.swift`: `Process` lifecycle, argument construction, stdout/stderr capture, cancellation, and exit status.
- `AppSettings.swift`: persisted executable paths, rewrite command, and output directory.
- `TranscriptionViewModel.swift`: state machine connecting the view and runner.

The Python CLI remains responsible for producing both files and preserving transcript provenance and timing. The Swift wrapper chooses the user-facing workflow and opens generated files.

## State and errors

States: idle, transcribing, awaiting-review-choice, rewriting, completed, and failed. Disable URL submission during active work. A nonzero process exit, missing executable, missing output file, or cancellation should produce a visible error and must not mark the run completed.

## Verification

- Swift unit tests cover CLI argument construction, command parsing, state transitions, nonzero exit, missing executable, and expected output path selection.
- Build and test the Xcode project for macOS 13+ on Apple silicon.
- Manual smoke test: transcribe one public URL, decline review, then repeat and accept review with a local JSON-protocol runner; confirm both files exist and can be opened.

## Decisions left to implementation

- Use a small SwiftUI settings sheet for executable and output directory configuration.
- Use `NSWorkspace` to open generated files and reveal them in Finder.
- Keep the initial text-only output; expose broader formats in a later change.
