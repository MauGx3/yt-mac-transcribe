# Demo and benchmark (`ytt demo`)

`ytt demo` checks how well and how fast this Mac transcribes speech, compares
the LLMs that can clean up a transcript, and saves the models you choose.
It works for anyone who has installed `ytt`: no YouTube video, account, or
network access is needed unless you ask it to download models.

```bash
ytt demo                 # run what is installed, show results, ask which models to use
ytt demo --download      # also download missing MLX models (can be several GB)
ytt demo --save          # save the recommended models without asking
ytt demo --json          # machine-readable report (the Mac app uses this)
```

## The sample is copyright free

The demo does not use any video or third-party recording. It ships a short
script written for this project and dedicated to the public domain (CC0),
and voices it on your Mac with the built-in `say` command. The audio is made
on your machine at run time and never leaves it. Because the exact text is
known, every result can be scored.

Synthetic speech is clearer than a real recording, so treat the accuracy
numbers as a best case. To test with your own voice, record yourself reading
any text you have the rights to and run:

```bash
ytt demo --audio my-recording.m4a --reference my-text.txt
```

`--audio` needs `ffmpeg`. `--voice NAME` picks another macOS voice for the
built-in sample (`say -v '?'` lists them).

## What is measured

**Speech to text.** Every installed engine (whisper.cpp, mlx-whisper) runs
every model that is already downloaded (`tiny.en` to `large-v3-turbo`; pick
others with `--asr-models`). For each run the demo reports:

- time, including model load, as a real user would see it
- speed as a multiple of real time (`15x` means a minute of audio in four seconds)
- word error rate (WER) against the script, ignoring case and punctuation

Models that are not downloaded are listed with the command that fetches them.

**LLM cleanup.** The demo gives each MLX-LM model a deliberately garbled
copy of the script: no capitals or punctuation, and twelve mistakes such as
*their/there*, *bred/bread* and *weather/whether*. It uses the same runner
and protocol as `ytt --rewrite-command`, so the result matches real use.
For each model it reports the time and the errors left, both as words only
and strict (case and punctuation count too).

The built-in list covers Qwen2.5 (0.5B, 1.5B, 3B, 7B), Llama 3.2 (1B, 3B),
Qwen3 4B Instruct 2507 and Llama 3.1 8B, all 4-bit builds from
`mlx-community`. Pass `--llm-models` to try others. Models larger than your
memory comfortably fits are marked. This part needs `mlx-lm`
(`python3 -m pip install mlx-lm`) and the repository's
`tools/rewrite_with_local_model.py`; point `--runner` at another runner if
you use one. `--runner` takes the rest of the line, so put it last.

## How a model is recommended

For each job, the demo keeps the models whose error rate is within two
points of the best one and recommends the fastest of those. An LLM that
leaves more word errors than the garbled input had is never recommended.
When nothing could be measured, it suggests a model that fits your memory.

## Saving a choice

In a terminal, the demo asks which speech model and LLM to use, with the
recommendation as the default. `--save` takes the recommendation without
asking. The choice goes to `~/.config/ytt/config.json` (`$YTT_CONFIG`
overrides the path):

```json
{
  "asr_engine": "mlx",
  "asr_model": "small.en",
  "llm_model": "mlx-community/Qwen2.5-3B-Instruct-4bit"
}
```

After that, `ytt` uses the saved `--engine` and `--model` by default, and
`tools/rewrite_with_local_model.py` uses the saved LLM. Flags on the command
line still win, and `$YTT_LLM_MODEL` overrides the saved LLM.

## In the Mac app

The **Benchmark** tab runs the same demo and shows the results in two
tables. **Use** next to a row, or **Use Recommended**, sets the speech
engine and model in Settings and the `--model` of your local rewrite command.
The LLM part runs only when a rewrite command is set in Settings.
