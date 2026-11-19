# YT Transcribe for macOS

A lightweight SwiftUI wrapper around the existing `ytt` command and a small transcript manager.

The window has a sidebar with **Transcribe**, **All Transcripts**, **Needs Review** (with a count of transcripts waiting) and **Benchmark**.

- **Transcribe:** paste a single video, a whole playlist (`ytt --playlist`), or a batch of URLs (one per line) into the composer. Pick output formats (txt, srt, vtt, json, md) from the **Formats** menu in the toolbar. For a single video the run card then offers **Enhance**, which creates an enhanced copy with your local model command; playlist and batch runs skip this step. When a run finishes, the card shows a preview with Open, Review Changes and Show in Finder.
- **Review window:** after an enhancement, the app opens a diff of every change in its own window. Each change has Accept and Reject. Spots the model was unsure of are labelled **AI unsure**, and spots where the speech recognition was unsure are labelled **Unclear audio**. Unclear words the AI left unchanged are listed under their segment, since they may still be misheard. Unclear audio needs a local transcription (whisper.cpp or mlx-whisper); YouTube captions carry no scores. The floating bar moves between unsure spots (Option-Up and Option-Down). **Save Reviewed** (Command-S) writes `<name>.reviewed.txt`; the original and enhanced files are left as they are.
- **Library:** every transcript is remembered (`~/Library/Application Support/YTTranscribe/library.json`) in a sortable table with a review status column: **Needs review** until you save a Reviewed copy, then **Reviewed**. Search titles, links or transcript text from the toolbar. Double-click opens a transcript; right-click or the inspector opens, reveals, reviews or removes it. Removing an entry never deletes the transcript files.
- **Settings:** General (output folder, `ytt` location), Transcription (speech engine and model) and Enhancement (on-device AI setup, and an optional custom rewrite command), each with a check that the program is installed.

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
5. For enhanced transcripts, press **Set Up On-Device AI…** on the run card (or use **Settings → Enhancement**). See [On-device AI setup](#on-device-ai-setup). To use another runner instead, enter it as the custom command, for example `ollama run local-model`.

The build needs network access once, to fetch the pinned `uv` (it is then cached in `~/Library/Caches/yt-transcribe-build`). To build offline, set `YTT_SKIP_UV_BUNDLE=1` (the app then can't set up on-device AI) or point `YTT_UV_BINARY` at a local `uv`.
6. Paste a single YouTube video URL and select **Transcribe**.

The default output directory is `~/Documents/yt-transcribe`. The app prints progress/errors in its status area. After the original transcript is saved, it asks whether to create an enhanced version. Files use the CLI-generated title, the `.rewritten.txt` suffix for the enhanced copy, `.review.json` for the diff, and `.reviewed.txt` for the copy you save after reviewing.

## Local command behavior

The app launches `ytt` directly with Foundation `Process`; it does not use a shell. A video URL and each rewrite argument are passed as separate process arguments. The app saves the original transcript before asking about local review. Accepting review invokes the CLI with `--rewrite-command`; `ytt` writes the original and enhanced files side by side.

The rewrite command can also be supplied through `YTT_REWRITE_COMMAND` when the app starts. App Settings are stored in `UserDefaults` and take precedence. When no custom command is set, Enhance uses the on-device AI runtime. No model is bundled; models download on first use, or during setup if the user asks.

## On-device AI setup

The app ships what it needs to install MLX, and installs it only when the user agrees. Python and MLX are not bundled: together they would add a few hundred MB to every copy of the app, each of their native libraries would need signing for notarization, and users who never press Enhance would carry them for nothing.

What ships in the bundle (`scripts/bundle-ai-runtime.sh`):

- `Contents/Helpers/uv`: [uv](https://docs.astral.sh/uv/) at a pinned version, downloaded from PyPI at build time and checked against a SHA-256 written in the script, then signed with the app's identity.
- `Contents/Resources/AIRuntime/requirements-enhance.txt` and `requirements-speech.txt`: locks with an exact version and the SHA-256 of every wheel (regenerate with `scripts/lock-ai-runtime.sh` after editing the `.in` files in `AIRuntime/`).
- `rewrite_with_local_model.py` and `fetch_mlx_model.py` from `tools/`.

What setup does (`AIRuntime.swift`, `AIRuntimeManager.swift`):

1. `uv python install 3.12 --no-bin` into `~/Library/Application Support/YTTranscribe/AIRuntime/python`. Nothing is added to `~/.local/bin` or `PATH`.
2. `uv venv --relocatable` into a staging folder, `venv.new`.
3. `uv pip sync <lock> --require-hashes --only-binary :all:`: only the locked files, only prebuilt wheels, so no package code runs at install time.
4. A check that `mlx` and `mlx_lm` import and run on the GPU.
5. The staging folder replaces `venv` and `manifest.json` records which lock was installed. A failed or cancelled install leaves the previous environment working.

uv runs with `UV_NO_CONFIG=1`, its cache in `~/Library/Caches/com.maugx3.yttranscribe/uv`, and the macOS keychain's certificates (`UV_SYSTEM_CERTS=1`). `PYTHONPATH`, `PYTHONHOME` and `VIRTUAL_ENV` are cleared, and the runner starts with `python -I`, so a shell setup can't change which packages load. Models go to the normal Hugging Face cache. When an app update ships a new lock, Settings offers **Update**. **Remove** deletes the runtime and uv's cache.

Once installed, the runtime's `bin` folder (with `mlx_whisper` and `hf`) is added to the `PATH` the app gives `ytt`, and the bundled `ytt.pyz` runs with the runtime's Python. Without the runtime it uses Homebrew's `python3`, then the developer tools' one. It never calls the `/usr/bin/python3` stub on a Mac without developer tools, which would open an install dialog.

## Benchmark

The Benchmark screen runs `ytt demo --json` on a copyright-free sample voiced with macOS `say`, then lists the time and accuracy of each installed speech model and, when a rewrite command is set, each MLX-LM model. **Use** or **Use Recommended** updates the speech engine, speech model and the rewrite command's `--model`. See [`docs/demo.md`](../../docs/demo.md).

## Troubleshooting

- **`ytt` not found:** set the executable path in Settings and confirm it is executable in Terminal.
- **Review option unavailable:** press **Set Up On-Device AI…**, or set a custom rewrite command in Settings (restart the app if you supplied it through the environment).
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
