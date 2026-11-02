# SwiftUI Native Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight SwiftUI macOS app that accepts one YouTube URL, runs `ytt`, asks whether to generate a locally reviewed transcript, and exposes both transcript files.

**Architecture:** The SwiftUI view binds to a view model state machine. A `TranscriptionRunner` launches the configured `ytt` executable using `Process` with an argument array, never a shell. Python remains responsible for transcription and producing the `.rewritten.txt` companion.

**Tech Stack:** Swift 5.9+, SwiftUI, Foundation `Process`, AppKit `NSWorkspace`, XCTest, macOS 13+.

**Spec:** `docs/superpowers/specs/2026-11-02-swiftui-native-wrapper-design.md`

## Global Constraints

- Target macOS 13 or newer and Apple silicon.
- Accept one URL per run.
- Use the existing `ytt` CLI; do not reimplement transcription or rewriting.
- Add no external Swift package dependencies and bundle no model.
- Keep the original transcript and the `.rewritten.txt` companion together.
- Pass executable arguments directly to `Process`; never evaluate a shell string.
- Keep output format text-only in v1.

## Review Focus

- **Missing or malformed rewrite command:** disable reviewed flow with a clear explanation; test empty and invalid executable configuration.
- **URL with shell metacharacters:** pass as one Process argument without shell interpretation; test spaces and shell metacharacters remain in one argument.
- **Executable missing or exits nonzero:** show failure and do not show completed state; test missing executable and nonzero exit.
- **Process cancellation or view lifecycle changes:** terminate or retain process predictably and leave UI out of completed state; test cancellation result.
- **CLI succeeds without expected output files:** fail the run with an actionable error; test missing original and missing rewritten outputs.

---

## File structure

- Create `macos/YTTranscribeApp/YTTranscribeApp.xcodeproj/project.pbxproj` — minimal native macOS app target and test target.
- Create `macos/YTTranscribeApp/Sources/YTTranscribeApp/YTTranscribeApp.swift` — `@main` app and settings scene.
- Create `macos/YTTranscribeApp/Sources/YTTranscribeApp/AppSettings.swift` — persisted executable, rewrite command, and output directory settings.
- Create `macos/YTTranscribeApp/Sources/YTTranscribeApp/TranscriptionRunner.swift` — safe process launch, output capture, result validation, and cancellation.
- Create `macos/YTTranscribeApp/Sources/YTTranscribeApp/TranscriptionViewModel.swift` — workflow state machine and async task coordination.
- Create `macos/YTTranscribeApp/Sources/YTTranscribeApp/ContentView.swift` — URL form, progress/status, review choice, and file actions.
- Create `macos/YTTranscribeApp/Tests/YTTranscribeAppTests/` — runner argument, process failure, and state tests.
- Modify `README.md` — macOS app build/run instructions and one-URL/review flow.
- Create `macos/YTTranscribeApp/README.md` — Xcode build, configuration, and troubleshooting details.

### Task 1: Process runner and settings

**Files:**
- Create: `macos/YTTranscribeApp/Sources/YTTranscribeApp/AppSettings.swift`
- Create: `macos/YTTranscribeApp/Sources/YTTranscribeApp/TranscriptionRunner.swift`
- Create: `macos/YTTranscribeApp/Tests/YTTranscribeAppTests/TranscriptionRunnerTests.swift`

**Interfaces:**
- Produces `AppSettings` with `yttExecutable: URL`, `rewriteCommand: [String]`, and `outputDirectory: URL`.
- Produces `TranscriptionRunner.transcribe(url:settings:) async throws -> TranscriptFiles`.
- Produces `TranscriptionRunner.review(url:settings:) async throws -> TranscriptFiles`.
- Produces `TranscriptFiles.original: URL` and optional `TranscriptFiles.reviewed: URL`.

- [ ] **Step 1: Write failing tests**
  - `testTranscribeArgumentsKeepURLAsSingleArgument`: use a URL containing spaces and shell metacharacters; assert the runner passes one URL argument and does not invoke a shell.
  - `testReviewAddsRewriteArguments`: assert `--rewrite-command` and the configured executable/arguments are passed as individual arguments.
  - `testNonzeroExitIncludesStderr`: run a tiny test helper process that exits nonzero and writes a diagnostic to stderr; assert the thrown error contains the diagnostic.
  - `testMissingOutputIsFailure`: simulate successful exit without the expected text file and assert a validation error.
- [ ] **Step 2: Run tests to confirm they fail**
  - Run: `xcodebuild test -project macos/YTTranscribeApp/YTTranscribeApp.xcodeproj -scheme YTTranscribeApp -destination 'platform=macOS'`
  - Expected: tests fail because the runner/settings types do not exist.
- [ ] **Step 3: Implement settings and process runner**
  - Transcribe arguments: `[url, "-f", "txt", "-o", outputDirectory.path]`.
  - Review arguments append `"--rewrite-command"` followed by the configured command tokens.
  - Use `Process.executableURL` and `Process.arguments`; capture stdout and stderr with `Pipe`.
  - Store files as `<sanitized video title>.txt` and `<same stem>.rewritten.txt`; derive title from `ytt` output or use a stable video-ID fallback if the CLI exposes no title.
  - Validate the expected file exists before returning `TranscriptFiles`.
- [ ] **Step 4: Run runner tests**
  - Run the `xcodebuild test` command above.
  - Expected: all runner tests pass.

### Task 2: SwiftUI state machine and workflow

**Files:**
- Create: `macos/YTTranscribeApp/Sources/YTTranscribeApp/TranscriptionViewModel.swift`
- Create: `macos/YTTranscribeApp/Tests/YTTranscribeAppTests/TranscriptionViewModelTests.swift`

**Interfaces:**
- Consumes `AppSettings` and `TranscriptionRunner` from Task 1.
- Produces `TranscriptionState`: `.idle`, `.transcribing`, `.awaitingReviewChoice`, `.rewriting`, `.completed(TranscriptFiles)`, `.failed(String)`.
- Produces `start(url:) async`, `declineReview()`, `acceptReview() async`, and `cancel()` operations.

- [ ] **Step 1: Write failing state tests**
  - `testStartMovesThroughTranscribingAndStoresOriginal`: successful transcription enters `.awaitingReviewChoice` and retains the original path.
  - `testDeclineReviewCompletesWithOriginalOnly`: declining finishes with reviewed path absent and does not call review.
  - `testAcceptReviewCompletesWithBothPaths`: accepting review enters `.rewriting`, then `.completed` with both paths.
  - `testRunnerErrorMovesToFailed`: a process error results in `.failed` and no completion state.
  - `testCancelDoesNotComplete`: cancellation stops active work and leaves no completed result.
- [ ] **Step 2: Run tests to confirm failure**
  - Run: `xcodebuild test -project macos/YTTranscribeApp/YTTranscribeApp.xcodeproj -scheme YTTranscribeApp -destination 'platform=macOS'`
  - Expected: state-machine tests fail because the view model is absent.
- [ ] **Step 3: Implement the view model**
  - Keep process work off the main actor; publish state changes on `@MainActor`.
  - After transcription success, wait for the explicit user review choice.
  - On decline, finish with original only; on accept, run review and retain both paths.
  - Propagate launch, exit, output-validation, and cancellation errors into visible state.
- [ ] **Step 4: Run view model tests**
  - Run the `xcodebuild test` command above.
  - Expected: all state tests pass.

### Task 3: Native interface and settings

**Files:**
- Create: `macos/YTTranscribeApp/Sources/YTTranscribeApp/YTTranscribeApp.swift`
- Create: `macos/YTTranscribeApp/Sources/YTTranscribeApp/ContentView.swift`
- Modify: `macos/YTTranscribeApp/Sources/YTTranscribeApp/AppSettings.swift`
- Create: `macos/YTTranscribeApp/YTTranscribeApp.xcodeproj/project.pbxproj`

**Interfaces:**
- Consumes the view model state and operations from Task 2.
- Settings view edits the `ytt` executable path, local rewrite command, and output directory.
- Main view accepts exactly one URL and exposes original/reviewed output actions.

- [ ] **Step 1: Add UI-level model tests**
  - `testSettingsRoundTrip`: settings persist and reload executable path, rewrite command, and output directory.
  - `testReviewChoiceOnlyAppearsAfterOriginalSuccess`: the model does not expose a review prompt before original generation succeeds.
- [ ] **Step 2: Run tests to confirm failure**
  - Run: `xcodebuild test -project macos/YTTranscribeApp/YTTranscribeApp.xcodeproj -scheme YTTranscribeApp -destination 'platform=macOS'`
  - Expected: settings/UI state tests fail until persistence and transitions are connected.
- [ ] **Step 3: Implement SwiftUI UI and app target**
  - Main window contains a single URL field, **Transcribe** button, progress indicator, status text, and output actions.
  - Show a confirmation dialog after original transcription with the exact choice “Would you like to create a reviewed version using your local model?”
  - If rewrite command is unset, present a clear configuration hint and disable acceptance.
  - Use `NSWorkspace.shared.open` for file opening and `activateFileViewerSelecting` to reveal in Finder.
  - Add Settings scene for executable, rewrite command, and output directory selection.
  - Configure deployment target macOS 13.0; set Apple silicon architecture support.
- [ ] **Step 4: Run app tests and build**
  - Run: `xcodebuild test -project macos/YTTranscribeApp/YTTranscribeApp.xcodeproj -scheme YTTranscribeApp -destination 'platform=macOS'`
  - Expected: test target passes and the app target builds.

### Task 4: Documentation and end-to-end verification

**Files:**
- Modify: `README.md`
- Create: `macos/YTTranscribeApp/README.md`

- [ ] **Step 1: Document app build, configuration, and workflow**
  - Include Xcode open/build instructions, minimum macOS, locating `ytt`, setting a local rewrite command, output directory behavior, and troubleshooting.
  - State that the app accepts one URL and saves the original before asking about review.
- [ ] **Step 2: Run complete verification**
  - Run the macOS app XCTest target and `xcodebuild build` for the app scheme.
  - Expected: build succeeds and all native tests pass.
  - Run the Python network-free suite: `python3 -m unittest discover -s tests -p 'test_*.py' -v`.
  - Expected: all CLI tests pass unchanged.
- [ ] **Step 3: Manual smoke test**
  - Transcribe one public URL and decline review; confirm only the original text is produced and can be opened.
  - Transcribe the same URL and accept review using a local JSON-protocol test runner; confirm original and reviewed files exist and both UI actions open the intended file.
- [ ] **Step 4: Commit and publish the PR branch**
  - Commit the Xcode app, tests, and docs with message `Add lightweight SwiftUI macOS wrapper` and the required Chatbox co-author trailer.

## Self-review

- Spec coverage: app entry, one-URL form, CLI invocation, post-original review prompt, local rewrite, output preservation, open/reveal actions, settings, errors, macOS target, and docs are covered by Tasks 1–4.
- Type consistency: runner settings, result, state enum, and view model methods are defined before consumers.
- Review Focus conditions are pinned to runner/state tests.
- No Python production behavior changes are planned.
- The plan includes native app packaging and UI as one coherent deliverable; the CLI remains a separate tested boundary.
