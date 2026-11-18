# Local context-aware rewriting

`ytt` can run a local language model after transcription to repair wording that depends on surrounding context. This is useful for homophones, punctuation, sentence boundaries, and captions where each cue is understandable only with its neighbors.

The rewriter never changes the original transcript. For every requested format it writes both files:

```text
My Video.txt
My Video.rewritten.txt

My Video.srt
My Video.rewritten.srt
```

The rewritten file keeps the original segment timings, word timings, video metadata, and source URL. Its JSON/Markdown provenance reports `rewrite` as the engine and records the original engine in `rewritten_from`.

## Command

```bash
ytt URL --rewrite-command COMMAND [COMMAND_ARGS ...]
```

`--rewrite-command` must be the **last** `ytt` option. Everything after it, including flags such as `--model`, is passed unchanged to the runner. Put URLs, `-f`, `-o`, and `--rewrite-timeout` before it.

The command must be a local executable. `ytt` sends a JSON request on stdin and expects a JSON response on stdout. The command does not need network access, and no model library is added to the Python package.

Example using a local Python runner:

```bash
ytt https://youtu.be/aircAruvnKk \
  -f txt srt json \
  --rewrite-command python3 tools/rewrite_with_local_model.py
```

The rewrite timeout defaults to five minutes:

```bash
ytt URL --rewrite-timeout 900 \
  --rewrite-command ./bin/my-apple-silicon-rewriter --model qwen2.5:7b
```

The model runner can call an on-device engine such as a native MLX, llama.cpp, or Ollama setup. The repository does not prescribe a model runtime because hardware, model size, quantization, and installation choices vary across Apple silicon machines.

## Input protocol

The stdin JSON object contains the video metadata and the complete ordered segment list:

```json
{
  "title": "Example video",
  "url": "https://youtu.be/example",
  "language": "en",
  "instructions": "Rewrite only wording that improves meaning, grammar, punctuation, or speaker intent. Preserve the segment count and return JSON with a segments array containing one text field per segment.",
  "segments": [
    {
      "index": 0,
      "start_ms": 1000,
      "end_ms": 2000,
      "text": "their going home",
      "previous_text": "",
      "next_text": "because its late"
    }
  ]
}
```

The neighboring text fields are convenience context. The full `segments` array is always present so a runner can use broader document context.

## Output protocol

Write one JSON object to stdout:

```json
{
  "segments": [
    {"text": "They are going home"},
    {"text": "because it is late"}
  ]
}
```

The response must contain exactly one item for every input segment, in the same order. Each item must contain a string `text` value. `ytt` rejects invalid JSON, a different segment count, non-object items, or non-string text values and leaves no partial rewritten output.

A runner should preserve meaning and avoid adding information that is not supported by the transcript. It should correct wording and punctuation while keeping each segment concise enough for its existing subtitle timing.

## Review file and uncertainty (protocol v2)

Every successful rewrite also writes `My Video.review.json` next to the original. It holds, per segment, the original text, the enhanced text, the word-level changes between them (`hunks`), and any spans the runner reported as uncertain. A review screen or report reads this file; nothing else needs the rewritten files to show a diff. Its path is printed after the original and rewritten paths, followed by the HTML report described below.

Requests now carry `"protocol": 2`. A runner may add an optional `uncertain` list to any response segment:

```json
{"text": "They're going home",
 "uncertain": [{"start": 0, "end": 7, "score": 0.41, "reason": "low token probability"}]}
```

`start` and `end` are character offsets into that segment's `text`; `score` (0 to 1, optional) is the runner's confidence. Runners that do not send `uncertain` keep working: the review file then has the diff but no "AI unsure" markers, and `stats.has_ai_confidence` is `false`. Malformed spans are dropped instead of failing the rewrite. The bundled `tools/rewrite_with_local_model.py` fills `uncertain` from the model's token probabilities: a word the model changed is reported when its lowest token probability is under `--unsure-below` (default 0.5, `0` turns it off). Unchanged words are never reported. These are hints about where to look, not a judgement that the text is wrong.

### Unclear audio

When the transcript came from local speech recognition, `ytt` also keeps how sure the recogniser was of each word: whisper.cpp runs with `-ojf` (per-token probability) and mlx-whisper with `--word-timestamps True` (per-word probability). These scores also appear as `conf` on each word in `-f json` output. A word scored under 0.5 is added to its segment's `flags` with `"kind": "unclear_audio"`, the word itself, its `score`, and `changed`:

- `changed: true`: the rewrite edited that word, and the change carries the `unclear_audio` flag. The AI may have guessed at a word nobody could hear well.
- `changed: false`: the rewrite left the word alone. It may still be misheard, so the review screen lists it under the segment.

A change can carry both `ai_unsure` and `unclear_audio`. `stats.unclear_words` counts the unclear words, `stats.has_audio_confidence` says whether scores were available, and `stats.has_confidence` is `true` when either kind was. YouTube captions carry no scores, so transcripts made from captions never show "Unclear audio".

### HTML report

Next to the review file, `ytt` also writes `My Video.review.html`: one self-contained page (no network access, nothing else to download) that shows every change, the **AI unsure** and **Unclear audio** labels, and the unclear words the rewrite left unchanged. Timestamps link to that moment of the video. Open it in any browser.

In the page, each change has a **keep** checkbox. Untick the ones you disagree with, then press **Download Reviewed** to save `My Video.reviewed.txt` with your choices, the same file the macOS app saves. **Only unsure** hides the segments with nothing to check, and **Accept all without unsure marks** ticks every change that has no label. Your choices are not stored in the page, so download before closing it.

To rebuild the page from an existing review file, for example after updating `ytt`:

```bash
ytt --review-report "My Video.review.json"
```

## Building a local runner

A runner only needs standard input/output handling. The model call is intentionally outside `ytt` so the same CLI feature can work with different local engines:

```python
import json
import sys

request = json.load(sys.stdin)
# Replace this with an on-device model call.
rewritten = [
    {"text": segment["text"]}
    for segment in request["segments"]
]
json.dump({"segments": rewritten}, sys.stdout, ensure_ascii=False)
```

For a real runner, pass `request["segments"]` as structured context to the local model, validate that the response contains the same number of segments, and emit only the required JSON object. Diagnostics should go to stderr so stdout remains parseable JSON.

## Bundled MLX-LM runner

`tools/rewrite_with_local_model.py` is a ready-made runner for Apple silicon. It needs `mlx-lm`, which is installed separately and is not a dependency of `ytt`:

```bash
python3 -m pip install mlx-lm
ytt URL -f txt srt --rewrite-command \
  python3 tools/rewrite_with_local_model.py --model mlx-community/Qwen2.5-7B-Instruct-4bit
```

Options: `--model` (default `mlx-community/Qwen2.5-3B-Instruct-4bit`), `--chunk-size`, `--context`, `--retries`, `--max-tokens`, and `--keep-original-on-failure`. The first run downloads the model from Hugging Face. The transcript is sent in chunks with a few neighboring segments as read-only context, and a chunk whose reply has the wrong segment count is retried. If it still fails, the runner exits non-zero (or keeps that chunk's original text with `--keep-original-on-failure`). Remember to put `--rewrite-timeout` before `--rewrite-command` for long videos.

## Failure behavior

- A non-zero runner exit code fails the video rewrite.
- Invalid JSON fails the video rewrite.
- A segment count mismatch fails the video rewrite.
- A timeout fails the video rewrite.
- The original transcript is written before the rewritten companion is attempted.
- When rewriting fails, `ytt` still prints the original output paths on stdout, logs the error, and records the URL in the batch `failed:` summary instead of silently presenting an unverified rewrite.
- A single-video run whose rewrite fails exits with status `1`; the original files remain on disk.

## Development notes

The implementation lives in `src/ytt/rewriter.py`. It builds the request, runs the local command, validates the response, copies original timings, and marks provenance. CLI integration and companion naming live in `src/ytt/cli.py`; tests are in `tests/test_rewriter.py` and `tests/test_rewrite_cli.py`.
