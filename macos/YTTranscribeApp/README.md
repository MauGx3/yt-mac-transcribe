# YT Transcribe for macOS

A lightweight SwiftUI wrapper around the existing `ytt` command and a small transcript manager.

The window has a sidebar with **Transcribe**, **All Transcripts**, **Needs Review** (with a count of transcripts waiting) and **Benchmark**.

- **Transcribe:** paste a single video, a whole playlist (`ytt --playlist`), or a batch of URLs (one per line) into the composer. Pick output formats (txt, srt, vtt, json, md) from the **Formats** menu in the toolbar. For a single video the run card then offers **Enhance**, which creates an enhanced copy with your local model command; playlist and batch runs skip this step. When a run finishes, the card shows a preview with Open, Review Changes and Show in Finder.
- **Review window:** after an enhancement, the app opens a diff of every change in its own window. Each change has Accept and Reject. Spots the model was unsure of are labelled **AI unsure**, and spots where the speech recognition was unsure are labelled **Unclear audio**. Unclear words the AI left unchanged are listed under their segment, since they may still be misheard. Unclear audio needs a local transcription (whisper.cpp or mlx-whisper); YouTube captions carry no scores. The floating bar moves between unsure spots (Option-Up and Option-Down). **Save Reviewed** (Command-S) writes `<name>.reviewed.txt`; the original and enhanced files are left as they are.
- **Library:** every transcript is remembered (`~/Library/Application Support/YTTranscribe/library.json`) in a sortable table with a review status column: **Needs review** until you save a Reviewed copy, then **Reviewed**. Search titles, links or transcript text from the toolbar. Double-click opens a transcript; right-click or the inspector opens, reveals, reviews or removes it. Removing an entry never deletes the transcript files.
- **Settings:** General (output folder, `ytt` location), Transcription (speech engine and model) and Enhancement (built-in AI model, or your own rewrite command), each with a check that the program is installed.

## Requirements

- macOS 14 or newer (Liquid Glass on macOS 26)
- Apple silicon
- Xcode 26 or newer for the Liquid Glass look. Xcode 15 and 16 still build the app, with the macOS 14 look everywhere.
- `yt-dlp` and the `ytt` CLI installed locally
- Nothing extra for enhancement: **Set Up AI Enhancement** installs it (see below). A custom rewrite runner that follows the [`ytt` JSON rewrite protocol](../../docs/local-rewriting.md) also works.

## Liquid Glass

Every Liquid Glass API call lives in `Sources/YTTranscribeApp/GlassCompat.swift`. Views use its helpers (`appGlass(in:)`, `AppGlassContainer`, `appPrimaryButtonStyle()`, `appSecondaryButtonStyle()`), which fall back to materials and bordered buttons on macOS 14 and 15. CI fails if a glass API appears in another file. The file's preview shows both styles side by side.

## Build and run

1. Open `YTTranscribeApp.xcodeproj` in Xcode.
2. Select the `YTTranscribeApp` scheme and **My Mac** destination.
3. Build and run.
4. The `ytt` CLI is packaged inside the app (`Contents/Resources/ytt.pyz`) by `scripts/bundle-ytt.sh`. Install `yt-dlp` (`brew install yt-dlp`). Optionally override the `ytt` path in **Settings**; the app adds Homebrew directories and `~/.local/bin` (where `pipx` installs `mlx-whisper` and `hf`) to `PATH` so those tools are found when the app is launched from Finder.
5. For enhanced transcripts, click **Set Up AI Enhancement** (on the run card or in **Settings → Enhancement**). Or enter your own command and its arguments, for example `ollama run local-model`.
6. Paste a single YouTube video URL and select **Transcribe**.

The default output directory is `~/Documents/yt-transcribe`. The app prints progress/errors in its status area. After the original transcript is saved, it asks whether to create an enhanced version. Files use the CLI-generated title, the `.rewritten.txt` suffix for the enhanced copy, `.review.json` for the diff, and `.reviewed.txt` for the copy you save after reviewing.

## Local command behavior

The app launches `ytt` directly with Foundation `Process`; it does not use a shell. A video URL and each rewrite argument are passed as separate process arguments. The app saves the original transcript before asking about local review. Accepting review invokes the CLI with `--rewrite-command`; `ytt` writes the original and enhanced files side by side.

The rewrite command can also be supplied through `YTT_REWRITE_COMMAND` when the app starts. App Settings are stored in `UserDefaults` and take precedence.

## Built-in AI enhancement

`scripts/bundle-ytt.sh` copies `tools/rewrite_with_local_model.py` into the app's Resources. **Set Up AI Enhancement** (`EnhancementSetup.swift`) then, without a shell:

1. downloads `uv` 0.13.9 from its GitHub release and refuses to run it unless its SHA-256 matches the pinned value;
2. has `uv` create a virtual environment with a private Python 3.12 (`--managed-python`, `--no-config`, with `uv`'s Python and cache directories inside the setup folder);
3. installs the pinned `mlx-lm==0.32.2` and checks that `import mlx_lm` works;
4. copies the bundled helper next to it, then downloads the model the helper will use (`--model`, `YTT_LLM_MODEL`, the `ytt demo` choice, or Qwen2.5 3B) to the Hugging Face cache;
5. writes `installed.json` last, so an interrupted setup never counts as installed, and fills in the rewrite command if it was empty.

Everything except the model lives in `~/Library/Application Support/YTTranscribe/AI`. The helper copy is refreshed from the app bundle at every launch, so app updates reach it. **Remove…** deletes the folder and turns enhancement off if the built-in model was in use. Apple silicon only.

## Benchmark

The Benchmark screen runs `ytt demo --json` on a copyright-free sample voiced with macOS `say`, then lists the time and accuracy of each installed speech model and, when a rewrite command is set, each MLX-LM model. **Use** or **Use Recommended** updates the speech engine, speech model and the rewrite command's `--model`. See [`docs/demo.md`](../../docs/demo.md).

## Troubleshooting

- **`ytt` not found:** set the executable path in Settings and confirm it is executable in Terminal.
- **Review option unavailable:** click **Set Up AI Enhancement**, or set a rewrite command in Settings (restart the app if you supplied it through the environment).
- **AI setup failed:** the message shows the last lines from the failing step. Check the internet connection and free space (about 2.5 GB), then **Try Again**; setup starts over cleanly.
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
