# Troubleshooting

Start here when `ytt` or the Mac app doesn't do what you expect. Each section
describes what you see, why it happens, and how to fix it.

**First, two things that fix many problems:**

1. Update yt-dlp. YouTube changes often, and old versions break:
   `brew upgrade yt-dlp`
2. Run the command again with `-v` (verbose) to see each step:
   `ytt URL -v`

## Contents

- [`ytt: command not found`](#ytt-command-not-found)
- [`yt-dlp` is missing](#yt-dlp-is-missing)
- [The video has no usable captions](#the-video-has-no-usable-captions)
- [whisper.cpp model not found](#whispercpp-model-not-found)
- [`mlx_whisper` or `hf` not found after `pipx install`](#mlx_whisper-or-hf-not-found-after-pipx-install)
- [Caption downloads are slow, or `CERTIFICATE_VERIFY_FAILED`](#caption-downloads-are-slow-or-certificate_verify_failed)
- [HTTP 429: YouTube is throttling you](#http-429-youtube-is-throttling-you)
- [Private, members-only or age-restricted videos](#private-members-only-or-age-restricted-videos)
- [The transcript is in the wrong language](#the-transcript-is-in-the-wrong-language)
- [The transcript has lots of mistakes](#the-transcript-has-lots-of-mistakes)
- [I get an old result after a video changed](#i-get-an-old-result-after-a-video-changed)
- [The local cleanup step failed](#the-local-cleanup-step-failed)
- [Only part of a batch or playlist worked](#only-part-of-a-batch-or-playlist-worked)
- [Mac app problems](#mac-app-problems)
- [Reporting a bug](#reporting-a-bug)

## `ytt: command not found`

The shell can't find the `ytt` command.

- **If you installed with pipx:** run `pipx ensurepath`, then **open a new
  Terminal window**. The change only applies to new windows.
- **If you installed in a virtual environment:** that environment is only active
  in the window where you ran `source .venv/bin/activate`. Go back to the
  project folder and run it again.
- **Without installing:** you can run it straight from the project folder with
  `PYTHONPATH=src python3 -m ytt URL`.

## `yt-dlp` is missing

`ytt` stops with an error about `yt-dlp` and exits with code `2`.

```bash
brew install yt-dlp
yt-dlp --version    # should print a date-style version
```

If you installed `yt-dlp` some other way (pip, pipx, a download), make sure
`which yt-dlp` prints a path.

## The video has no usable captions

You see `no usable captions and the local ASR fallback is not installed`,
followed by a list of tools marked `not found`.

The video either has no captions or only captions too poor to use. To
transcribe it, `ytt` needs to process the audio on your Mac, and that's not set
up yet. Follow
[Videos without captions](../README.md#videos-without-captions-transcribing-on-your-mac)
in the README. In short:

```bash
brew install ffmpeg whisper-cpp
mkdir -p ~/.cache/whisper
curl -L -o ~/.cache/whisper/ggml-small.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
```

To check what a video offers before transcribing it, run
`ytt URL --list-tracks`.

## whisper.cpp model not found

You see `whisper.cpp model 'small.en' not found`.

whisper.cpp is installed, but the model file isn't in a folder `ytt` searches.
The error message prints the exact download command and the list of folders.
The usual fix is to download the model into `~/.cache/whisper`:

```bash
mkdir -p ~/.cache/whisper
curl -L -o ~/.cache/whisper/ggml-small.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
```

Replace `small.en` with the model you want (`tiny.en`, `base.en`, `medium.en`,
`large-v3`). If the file is somewhere else, give its full path:
`--model ~/Downloads/ggml-small.en.bin`.

Homebrew's `whisper-cpp` doesn't install a `whisper-cpp-download-ggml-model`
script, so older instructions that mention it won't work.

## `mlx_whisper` or `hf` not found after `pipx install`

pipx puts commands in `~/.local/bin`. Terminal only looks there after
`pipx ensurepath` and a new window:

```bash
pipx ensurepath
# open a new Terminal window, then:
which mlx_whisper
```

The Mac app adds `~/.local/bin` to its search path on its own, so this affects
the Terminal only.

## Caption downloads are slow, or `CERTIFICATE_VERIFY_FAILED`

This happens with Python installed from the python.org installer, which doesn't
set up security certificates until you run one extra step. Without them, the
direct caption download fails and `ytt` falls back to a much slower route
through `yt-dlp`.

**Fix:** open Finder, go to **Applications → Python 3.x**, and double-click
**Install Certificates.command**.

`ytt` also works around this by itself. It uses the `certifi` package if it's
installed, and otherwise the certificates macOS keeps in `/etc/ssl/cert.pem`.
The command above is still the proper fix, because other Python programs need
it too. If you set the `SSL_CERT_FILE` environment variable, `ytt` always uses
that file.

## HTTP 429: YouTube is throttling you

YouTube limits how many requests one connection can make in a short time. `ytt`
waits and retries once, then tells you it's being throttled.

- Wait a few minutes and try again. The block usually lifts quickly.
- Slow down batches: `--delay 5`.
- Use your browser's YouTube login: `--cookies-from-browser chrome` (or
  `firefox`, `safari`, `edge`, `brave`).
- Re-running a video you've already done reuses its cached captions.

**Safari cookies:** macOS protects Safari's data. To use
`--cookies-from-browser safari`, give Terminal **Full Disk Access** in
**System Settings → Privacy & Security**.

## Private, members-only or age-restricted videos

These need you to be logged in. Log in to YouTube in your browser, then add
`--cookies-from-browser chrome` (or your browser). Private videos only work if
your account can watch them. Some videos can't be read at all.

## The transcript is in the wrong language

`ytt` uses English unless you tell it otherwise. List what's available, then ask
for the language you want:

```bash
ytt URL --list-tracks
ytt URL -l pt          # Portuguese
ytt URL -l es,en       # Spanish if available, otherwise English
```

If only a machine translation exists in your language, `ytt` uses it and says so
in the transcript. The original language is usually more accurate.

For local transcription in a language other than English, use a model without
`.en`, for example `--model large-v3`.

## The transcript has lots of mistakes

YouTube's automatic captions often get names, technical terms and accents wrong.
`ytt` cleans up formatting, but it can't fix words YouTube misheard.

Things to try, from least to most effort:

1. Check whether creator-written captions exist with `--list-tracks`. `ytt`
   already prefers them, but they may be in another language code (for example
   `en-US` instead of `en`).
2. Transcribe the audio yourself with a bigger model:
   `ytt URL --asr always --model medium.en`. On Apple silicon, try
   `--engine mlx --model large-v3-turbo`.
3. Run the [local cleanup](../README.md#cleaning-up-a-transcript-with-a-local-ai-model)
   step to fix wording using the surrounding sentences.

## I get an old result after a video changed

Captions are cached for a week, and video details for an hour. To skip the cache for one run,
use `--no-cache`. To delete everything cached, use `ytt --clear-cache`. The
cache lives in `~/.cache/yt-transcribe`.

## The local cleanup step failed

The original transcript is always saved first, so you don't lose it. Common
causes:

- **Timeout:** long videos can take more than the default five minutes. Add
  `--rewrite-timeout 1800`, placed *before* `--rewrite-command`.
- **Options in the wrong place:** everything after `--rewrite-command` is sent
  to the model runner. Put `-f`, `-o` and other `ytt` options before it.
- **`mlx_lm` not installed:** the bundled runner needs it. Run
  `python3 -m pip install mlx-lm`, using the same `python3` you pass to
  `--rewrite-command`.
- **Wrong number of segments:** the model returned more or fewer lines than it
  was given. The bundled runner retries. Add `--keep-original-on-failure` after
  the runner's path to keep the original text for chunks that still fail.

See [local-rewriting.md](local-rewriting.md#failure-behavior) for the details.

## Only part of a batch or playlist worked

`ytt` keeps going when one video fails. It ends with a `failed:` list of the
links that didn't work and exits with code `3`. Re-run just those links. If most failures mention 429, see
[HTTP 429](#http-429-youtube-is-throttling-you).

## Mac app problems

- **"ytt not found":** the app normally uses its own built-in copy. If you set a
  custom path in Settings, check it, or clear it.
- **Can't find `yt-dlp` or `mlx_whisper`:** the app searches the Homebrew
  folders and `~/.local/bin`. Check in Terminal that `which yt-dlp` prints a path
  in one of those places.
- **"Review" option is greyed out:** set a local rewrite command in Settings.
- **macOS won't open the app:** it isn't signed yet. Go to
  **System Settings → Privacy & Security** and click **Open Anyway**.
- **An error appears in the status area:** it's the message from `ytt`. Look it
  up on this page.

See the [app's README](../macos/YTTranscribeApp/README.md#troubleshooting) for
more.

## Reporting a bug

Open an issue with:

- the command you ran, and the output of the same command with `-v`
- `ytt --version`, `yt-dlp --version`, your macOS version and your chip (from
  **About This Mac**)
- for a caption problem, the output of `ytt URL --list-tracks`

Don't paste cookies, signed caption URLs (long links containing `signature=`
or `expire=`), or details of private videos.
