# AI features: clean up, review and choose models

`ytt` can use AI models that run on your Mac to make transcripts better. This
guide explains what each feature does, how to set it up, and how to check the
AI's work.

Everything here is optional. Without it, `ytt` still produces transcripts from
YouTube captions or from local speech recognition.

**Nothing leaves your Mac.** The models run locally. The only network use is
downloading a model from Hugging Face the first time you use it.

## Contents

- [What the AI does, and what it doesn't](#what-the-ai-does-and-what-it-doesnt)
- [Set up the AI model (once)](#set-up-the-ai-model-once)
- [Enhance a transcript](#enhance-a-transcript)
- [Review the AI's changes](#review-the-ais-changes)
- [What "AI unsure" and "Unclear audio" mean](#what-ai-unsure-and-unclear-audio-mean)
- [Find the best models for your Mac](#find-the-best-models-for-your-mac)
- [Which files you get](#which-files-you-get)
- [Using another model or tool](#using-another-model-or-tool)
- [Problems](#problems)

## What the AI does, and what it doesn't

There are two kinds of model in this project:

| Kind | Job | Examples |
|---|---|---|
| **Speech-to-text model** | Turns audio into words, when a video has no usable captions | whisper.cpp, MLX Whisper |
| **Language model (LLM)** | Reads a finished transcript and fixes its wording | Qwen2.5, Llama 3.2 (through MLX-LM) |

This guide is mostly about the second kind. We call its output the
**enhanced** transcript.

The language model reads the transcript in chunks, along with the sentences
around each chunk, and fixes what context makes clear:

- words that sound alike: *their / there*, *weather / whether*
- missing punctuation and capital letters
- sentence boundaries that caption timing cut in odd places

It can't hear the audio. If a word was misheard and the context doesn't make the
right word obvious, the model may guess wrong, or may "fix" something that was
right. That's why `ytt` keeps your original, shows you every change, and marks
the changes most worth checking.

## Set up the AI model (once)

The included helper uses **MLX-LM**, Apple's framework for running language
models on Apple silicon. It needs an M1 or later Mac.

Install MLX-LM in its own small Python environment, so it doesn't clash with
anything else on your Mac:

```bash
python3 -m venv ~/.venvs/ytt-ai
~/.venvs/ytt-ai/bin/pip install mlx-lm
```

Check that it worked. This should print nothing and return to the prompt:

```bash
~/.venvs/ytt-ai/bin/python -c "import mlx_lm"
```

If you see `No module named 'mlx_lm'`, the install didn't finish. Run the
`pip install` line again and read its last few lines for the error.

The first time you enhance a transcript, the model downloads automatically. The
default model, Qwen2.5 3B, is about 1.7 GB.

> **Why not `pipx install mlx-lm`?** pipx is great for command-line tools, but
> it puts MLX-LM in a private environment that the helper script can't see.
> The helper needs MLX-LM installed for the Python that runs it.

## Enhance a transcript

### In Terminal

Run these from the `yt-transcribe` folder (the helper lives in
`tools/`):

```bash
ytt https://youtu.be/aircAruvnKk -f txt srt \
  --rewrite-command ~/.venvs/ytt-ai/bin/python tools/rewrite_with_local_model.py
```

Two rules:

- **`--rewrite-command` must come last.** Everything after it is passed to the
  helper, not to `ytt`. Put `-f`, `-o` and other `ytt` options before it.
- **Long videos get more time automatically.** The limit is 2 minutes plus
  2 seconds per caption line. To set your own, add `--rewrite-timeout 1800`
  (30 minutes) *before* `--rewrite-command`.

To clean up a transcript you already have, save it with `-f json` and pass it
with `--rewrite-from`. Nothing is downloaded or transcribed again:

```bash
ytt --rewrite-from "Video.json" -f txt --rewrite-command ~/.venvs/ytt-ai/bin/python \
  tools/rewrite_with_local_model.py
```

To use a different model, add `--model` at the end:

```bash
ytt URL --rewrite-command ~/.venvs/ytt-ai/bin/python \
  tools/rewrite_with_local_model.py --model mlx-community/Qwen2.5-7B-Instruct-4bit
```

Bigger models usually make better fixes but are slower and need more memory.
Models up to 3B run on any Apple silicon Mac. 7B and 8B models need 16 GB of
memory or more. Not sure which one to use?
[Let the demo choose](#find-the-best-models-for-your-mac).

### In the Mac app

1. Open **Settings** and fill in **Local rewrite command** with the full paths, for
   example:

   ```text
   /Users/you/.venvs/ytt-ai/bin/python /Users/you/yt-transcribe/tools/rewrite_with_local_model.py
   ```

   Replace `/Users/you` with your home folder. Run `echo $HOME` in Terminal to
   see it. The app can't expand `~`, so use full paths.
2. Transcribe a single video as usual.
3. When the original is saved, the app asks whether to create an enhanced copy.
   Click yes. Playlists and batches skip this step.
4. The review screen opens when the AI is done.

## Review the AI's changes

Every enhancement comes with a review: a list of each place where the AI changed
the text, with the original and the new wording side by side. You decide what to
keep, then save a **Reviewed** copy.

### In the Mac app

The review screen opens by itself after an enhancement. For each change:

- **Accept** keeps the AI's wording.
- **Reject** keeps the original wording.

Helpful controls:

- **Only unsure** hides everything except the changes with a label (see below).
- **Next unsure** (⌥↓) jumps to the next labelled change.
- **Accept all without unsure marks** accepts every change that has no label,
  so you only look at the risky ones.
- **Save Reviewed** writes `<name>.reviewed.txt`. The original and enhanced
  files stay as they were.

In the **Library** tab, enhanced transcripts show **Needs review** until you
save a reviewed copy, then **Reviewed**. **Review Changes** reopens the screen
at any time.

### In a browser (for Terminal users)

Every enhancement also writes `<name>.review.html` next to your transcript.
Open it in any browser. It works offline and needs nothing installed.

- Each change has a **keep** checkbox. Untick the ones you disagree with.
- **Only unsure** and **Accept all without unsure marks** work like in the app.
- Timestamps link to that moment in the YouTube video, so you can listen.
- **Download Reviewed** saves `<name>.reviewed.txt`, the same file the app
  saves.

The page doesn't remember your choices. Download before you close it.

To rebuild the page from an existing review file, for example after updating
`ytt`:

```bash
ytt --review-report "My Video.review.json"
```

## What "AI unsure" and "Unclear audio" mean

Some changes carry a label. These are the ones most worth checking.

| Label | Meaning | When you'll see it |
|---|---|---|
| **AI unsure** | The language model wasn't confident about a word it wrote. | With the included MLX-LM helper. |
| **Unclear audio** | The speech-to-text model wasn't confident it heard the word right. | Only when the transcript came from local speech recognition (whisper.cpp or MLX Whisper). |

A change can have both labels. That's the riskiest case: nobody could hear the
word well, and the AI guessed.

**Unclear words the AI left alone** are also listed under their segment. The AI
didn't change them, but they may still be misheard, so they're worth a listen.

YouTube captions don't include confidence scores, so a transcript made from
captions never shows **Unclear audio**. To get those labels, transcribe locally
with `--asr always`.

The labels are hints about where to look, not verdicts. An unlabelled change can
still be wrong, and a labelled one is often fine. To change how sensitive the
**AI unsure** label is, pass `--unsure-below` to the helper: higher numbers
label more changes, and `0` turns the label off. The default is `0.5`.

```bash
ytt URL --rewrite-command ~/.venvs/ytt-ai/bin/python \
  tools/rewrite_with_local_model.py --unsure-below 0.7
```

## Find the best models for your Mac

Which speech-to-text model and which language model work best depends on your
Mac. `ytt demo` tests them for you:

```bash
ytt demo --runner ~/.venvs/ytt-ai/bin/python tools/rewrite_with_local_model.py
```

Without `--runner`, the demo still tests speech-to-text models. It needs the
`--runner` part to test language models, because MLX-LM is installed in
`~/.venvs/ytt-ai` rather than where `ytt` is. `--runner` must come last.

What it does:

1. Your Mac reads a short sample text aloud with its built-in voice. The sample
   was written for this project and is public domain. No YouTube video is used.
2. Every installed speech-to-text model transcribes it. Because the exact text
   is known, the demo can count the mistakes.
3. Every downloaded language model cleans up a deliberately garbled copy of the
   sample. The demo counts the mistakes left.
4. It recommends the fastest model that's nearly as accurate as the best one,
   and asks which ones you want as your defaults.

Your choice is saved in `~/.config/ytt/config.json`. After that, `ytt` and the
helper use those models unless you pass `--engine`, `--model` or the helper's
`--model`.

Useful variations:

```bash
ytt demo --download      # also download missing models first (can be several GB)
ytt demo --save          # save the recommendation without asking
ytt demo --audio me.m4a --reference me.txt   # test with your own recording
```

Synthetic speech is clearer than real recordings, so treat the accuracy numbers
as a best case.

In the Mac app, the **Benchmark** tab runs the same test. **Use** next to a
result, or **Use Recommended**, updates Settings for you.

See [demo.md](demo.md) for every option and how the recommendation is made.

## Which files you get

For a video called *My Video*, an enhanced `txt` run leaves these files:

| File | What it is | Made by |
|---|---|---|
| `My Video.txt` | The original transcript. Never changed. | `ytt` |
| `My Video.rewritten.txt` | The AI's enhanced version, with every change applied. | `ytt` |
| `My Video.review.json` | The list of changes and labels, for the app and the browser page. | `ytt` |
| `My Video.review.html` | The review page for your browser. | `ytt` |
| `My Video.reviewed.txt` | Your final version, with only the changes you kept. | You, from the app or the page |

If you ask for more formats (for example `-f txt srt`), each gets its own
`.rewritten` copy, such as `My Video.rewritten.srt`. Timings are the same as the
original.

## Using another model or tool

The helper is just one option. `ytt` can hand the transcript to any program
that reads a JSON request and returns the corrected text, for example a script
that calls Ollama or llama.cpp. The app's Settings accept the same command.
[local-rewriting.md](local-rewriting.md) describes the format for anyone writing
such a program.

Helpers that don't report confidence still work. You get the full review, just
without **AI unsure** labels.

## Problems

- **"No module named 'mlx_lm'":** MLX-LM isn't installed for the Python you
  passed. Use the same path in the command as in
  [the setup](#set-up-the-ai-model-once), for example `~/.venvs/ytt-ai/bin/python`.
- **"local rewrite failed: … timed out":** add `--rewrite-timeout 1800` before
  `--rewrite-command`, or try a smaller model.
- **A rewrite fails because of the number of segments:** the model returned more
  or fewer lines than it was given. The helper already retries. Add
  `--keep-original-on-failure` after the helper's path to keep the original text
  for chunks that still fail.
- **The Mac becomes very slow, or the model crashes:** it's probably too big for
  your memory. Try a smaller one, such as `mlx-community/Qwen2.5-1.5B-Instruct-4bit`.
- **The enhance option is greyed out in the app:** fill in **Local rewrite command**
  in Settings.
- **The demo says "mlx-lm is not installed":** add the `--runner` part shown
  [above](#find-the-best-models-for-your-mac).
- **There's no review file:** review files are only written when the enhancement
  succeeds. If it failed, your original is still saved. Check the error above
  the file paths.

More problems and fixes: [troubleshooting.md](troubleshooting.md).
