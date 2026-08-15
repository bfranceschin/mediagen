# mediagen

Image and video generation skill for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — powered by [fal.ai](https://fal.ai) plus optional GPT Image 2 via ChatGPT/Codex OAuth.

## Features

- **Image generation** via FLUX.2 (dev) and Nano Banana 2
- **Image editing** with reference images (1-4 inputs)
- **Video generation** via Seedance 1.5 Pro (text-to-video and image-to-video)
- **Start & end frame conditioning** for precise video transitions
- **Native audio generation** synchronized with video
- **Full persistence** — generated files, metadata (.md), and JSON logs
- **Optional Hostkit Media sync** — receipts + one-shot upload after generate (Telegram contract unchanged)
- **Reproducibility** — seed support for consistent results
- **Web search grounding** (Nano Banana 2 only)
- **Cinematic camera control** — dolly, pan, orbit, tripod mode

## Models

| Model | Key | Endpoint | Best for | Cost |
|-------|-----|----------|----------|------|
| FLUX.2 [dev] | `flux2` | `fal-ai/flux-2` | High-quality photorealistic/artistic images | ~$0.012/MP |
| Nano Banana 2 | `nano2` | `fal-ai/nano-banana-2` | Text rendering, complex composition, web grounding | ~$0.05/image |
| GPT Image 2 | `gptimage2` | ChatGPT/Codex OAuth (`openai-codex/gpt-image-2`) | GPT Image 2 without OpenAI API key; quality tiers low/medium/high | ChatGPT quota |
| Seedance 1.5 Pro | `seedance2` | `fal-ai/bytedance/seedance/v1.5/pro/text-to-video` | Short-form video with audio, dialogue, music | ~$0.26/5s@720p |
| Seedance 1.5 Pro | `seedance2` | `fal-ai/bytedance/seedance/v1.5/pro/image-to-video` | Animating images with start/end frame control | ~$0.26/5s@720p |

## Usage

### Image Generate

```bash
python3 scripts/mediagen.py \
  --model flux2 \
  --prompt "a cute puppy playing in the snow" \
  --width 1280 --height 720
```

### Image Edit

```bash
python3 scripts/mediagen.py \
  --model flux2 \
  --prompt "add a hat to the dog" \
  --inputs /path/to/image.png
```


### GPT Image 2 (ChatGPT/Codex OAuth)

Requires `hermes auth add openai-codex` and Hermes venv Python (`httpx` + token helpers).

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py   --model gptimage2   --prompt "a tiny flat blue frog icon"   --quality medium   --width 1024 --height 1024
```

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py   --model gptimage2   --prompt "make the sunglasses orange"   --inputs /path/to/image.png   --quality low
```

### Video — Text to Video

```bash
python3 scripts/mediagen.py \
  --model seedance2 \
  --prompt "A golden retriever playing fetch at sunset, slow motion" \
  --resolution 720p --duration 8
```

### Video — Image to Video

```bash
python3 scripts/mediagen.py \
  --model seedance2 \
  --prompt "the dog runs toward camera" \
  --inputs /path/to/start_frame.png \
  --resolution 720p --duration 5
```

### Video — Image to Video with End Frame

```bash
python3 scripts/mediagen.py \
  --model seedance2 \
  --prompt "smooth transition from sitting to standing" \
  --inputs /path/to/start_frame.png \
  --end-image /path/to/end_frame.png \
  --duration 6
```

## Arguments

### Shared

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--model` | Yes | — | `flux2`, `nano2`, or `seedance2` |
| `--prompt` | Yes | — | Text prompt or edit instruction |
| `--inputs` | No | — | Input images: 1-4 for image edit, exactly 1 for video |
| `--seed` | No | random | Reproducibility seed |

### Image-only

| Argument | Default | Description |
|----------|---------|-------------|
| `--width` | 1280 | Output width in pixels |
| `--height` | 720 | Output height in pixels |
| `--steps` | 28 | Inference steps (flux2 only) |
| `--enable-web-search` | false | Web search grounding (nano2 only) |

### Video-only (seedance2)

| Argument | Default | Description |
|----------|---------|-------------|
| `--end-image` | — | End frame image (image-to-video only, optional) |
| `--resolution` | `720p` | `480p`, `720p`, or `1080p` |
| `--aspect-ratio` | `16:9` | `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, `21:9`, `auto` |
| `--duration` | 5 | Video length in seconds (4-12) |
| `--camera-fixed` | false | Lock camera position (tripod mode) |
| `--no-audio` | false | Disable audio generation |

## Requirements

- Python 3.11+
- `fal_client` (`pip install fal-client`)
- `FAL_KEY` environment variable set

## File Structure

Generated outputs go to `~/.hermes/workspace/mediagen/`:

```
images/
  raw/           → Generated PNG files
  <base>.md      → One markdown file per image (embed + metadata; local legacy)
videos/
  raw/           → Generated MP4 files
  <base>.md      → One markdown file per video (link + metadata; local legacy)
external/        → Copies of user-provided input images
logs/            → Structured JSON logs per generation
receipts/        → Media sync receipts (optional Hostkit Media integration)
```

### Optional Hostkit Media sync

When configured, each successful generation creates a receipt and attempts one Media API sync after the file + JSON log are written. The stdout contract is unchanged:

```text
FILENAME=<filename> PROMPT=<prompt> SEED=<seed>
```

Media outages leave the binary/log/receipt intact and still exit `0`. Missing config disables sync (no error).

```text
MEDIA_API_URL=https://media.example.dev
MEDIA_API_TOKEN_FILE=~/.hermes/secrets/media-api-token
MEDIA_UPLOAD_TIMEOUT_SECONDS=180
```

Legacy markdown is never sent to Media as a canonical asset.

### Historical backfill (G1)

```bash
python scripts/media_backfill.py --workspace ~/.hermes/workspace/mediagen --dry-run --report /tmp/backfill-report.json
```

Default is dry-run (no HTTP). `--apply` is opt-in and uses the same `MEDIA_API_URL` / `MEDIA_API_TOKEN_FILE` passthrough as live sync. See [docs/BACKFILL.md](docs/BACKFILL.md).

### Filename Convention

**Images:** `<YYYYMMDD>_<HHMMSS>_<model>[_edit].{png,md,json}`
**Videos:** `<YYYYMMDD>_<HHMMSS>_<model>[_i2v].{mp4,md,json}`

## Testing

```bash
# Run unit tests (fast, no API calls, no cost)
python -m pytest tests/test_unit.py tests/test_media_client.py tests/test_mediagen_media_sync.py -q

# Run integration tests (calls real fal.ai API — costs ~$0.01-0.26)
python -m pytest tests/test_integration.py -v --run-integration

# Run all tests
python -m pytest tests/ -v
```

### Test structure

| File | Type | API calls? | Cost |
|------|------|-----------|------|
| `tests/test_unit.py` | Unit tests for pure functions | ❌ No | Free |
| `tests/test_media_client.py` | Media client + receipts (mocked HTTP) | ❌ No | Free |
| `tests/test_mediagen_media_sync.py` | Post-persist Media hook + FILENAME contract | ❌ No | Free |
| `tests/test_media_backfill.py` | Backfill parser/reconciliation (mocked HTTP) | ❌ No | Free |
| `tests/test_integration.py` | Full pipeline with real API | ✅ Yes | ~$0.01-0.26 |

Integration tests are **skipped by default** — only run when `--run-integration` flag is passed, so you never accidentally spend money.

## License

MIT
