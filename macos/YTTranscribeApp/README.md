# YT Transcribe for macOS

A lightweight SwiftUI wrapper around the existing `ytt` command and a small transcript manager.

- **Transcribe tab:** a single video, a whole playlist (`ytt --playlist`), or a batch of URLs (one per line). Pick one or more output formats (txt, srt, vtt, json, md). For a single video the app then asks whether to create a reviewed copy with a configured local model command; playlist and batch runs skip review.
- **Library tab:** every transcript is remembered (`~/Library/Application Support/YTTranscribe/library.json`). Search by title, URL, or the transcript text itself; open, reveal, or remove entries. Removing an entry never deletes the transcript files.

## Requirements

- macOS 14 or newer (Liquid Glass on macOS 26)
- Apple silicon
- Xcode 26 or newer for the Liquid Glass look. Xcode 15 and 16 still build the app, with the macOS 14 look everywhere.
- `yt-dlp` and the `ytt` CLI installed locally
- Optional local rewrite runner that follows the [`ytt` JSON rewrite protocol](../../docs/local-rewriting.md)

## Liquid Glass

Every Liquid Glass API call lives in `Sources/YTTranscribeApp/GlassCompat.swift`. Views use its helpers (`appGlass(in:)`, `AppGlassContainer`, `appPrimaryButtonStyle()`, `appSecondaryButtonStyle()`), which fall back to materials and bordered buttons on macOS 14 and 15. CI fails if a glass API appears in another file. The file's preview shows both styles side by side.

## Build and run

1. Open `YTTranscribeApp.xcodeproj` in Xcode.
2. Select the `YTTranscribeApp` scheme and **My Mac** destination.
3. Build and run.
4. The `ytt` CLI is packaged inside the app (`Contents/Resources/ytt.pyz`) by `scripts/bundle-ytt.sh`. Install `yt-dlp` (`brew install yt-dlp`). Optionally override the `ytt` path in **Settings**; the app adds Homebrew directories and `~/.local/bin` (where `pipx` installs `mlx-whisper` and `hf`) to `PATH` so those tools are found when the app is launched from Finder.
5. Set a local rewrite command if you want the reviewed-transcript choice enabled. Enter the executable and its arguments, for example `ollama run local-model`.
6. Paste a single YouTube video URL and select **Transcribe**.

The default output directory is `~/Documents/yt-transcribe`. The app prints progress/errors in its status area. After the original transcript is saved, it asks whether to create a reviewed version. Files use the CLI-generated title and the `.rewritten.txt` suffix for the reviewed copy.

## Local command behavior

The app launches `ytt` directly with Foundation `Process`; it does not use a shell. A video URL and each rewrite argument are passed as separate process arguments. The app saves the original transcript before asking about local review. Accepting review invokes the CLI with `--rewrite-command`; `ytt` writes the original and reviewed files side by side.

The rewrite command can also be supplied through `YTT_REWRITE_COMMAND` when the app starts. App Settings are stored in `UserDefaults` and take precedence. No model is downloaded or bundled by this app.

## Troubleshooting

- **`ytt` not found:** set the executable path in Settings and confirm it is executable in Terminal.
- **Review option unavailable:** set a local rewrite command in Settings and restart the app if you supplied it through the environment.
- **Command failed:** the app displays stderr from `ytt` or the rewrite runner.
- **No output file found:** confirm the configured output directory is writable and that `ytt` prints generated paths to stdout.

## Development

Run the shared scheme’s tests in Xcode or with:

```bash
xcodebuild test \
  -project YTTranscribeApp.xcodeproj \
  -scheme YTTranscribeApp \
  -destination 'platform=macOS'
```
