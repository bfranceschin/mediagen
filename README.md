# mediagen

Image and video generation skill for [Hermes Agent](https://github.com/bfranceschin/hermes-agent) — powered by [fal.ai](https://fal.ai).

## Features

- **Image generation** via FLUX.2 (dev) and Nano Banana 2
- **Image editing** with reference images (1-4 inputs)
- **Full persistence** — generated images, metadata (.md), and JSON logs
- **Reproducibility** — seed support for consistent results
- **Web search grounding** (Nano Banana 2 only)

## Models

| Model | Key | Endpoint | Best for | Cost |
|-------|-----|----------|----------|------|
| FLUX.2 [dev] | `flux2` | `fal-ai/flux-2` | High-quality photorealistic/artistic images | ~$0.012/MP |
| Nano Banana 2 | `nano2` | `fal-ai/nano-banana-2` | Text rendering, complex composition, web grounding | ~$0.05/image |

## Usage

### Generate

```bash
python3 scripts/mediagen.py \
  --model flux2 \
  --prompt "a cute puppy playing in the snow" \
  --width 1280 --height 720
```

### Edit

```bash
python3 scripts/mediagen.py \
  --model flux2 \
  --prompt "add a hat to the dog" \
  --inputs /path/to/image.png
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--model` | Yes | — | `flux2` or `nano2` |
| `--prompt` | Yes | — | Text prompt or edit instruction |
| `--inputs` | No | — | 1-4 image paths → triggers edit mode |
| `--width` | No | 1280 | Output width in pixels |
| `--height` | No | 720 | Output height in pixels |
| `--steps` | No | 28 | Inference steps (flux2 only) |
| `--seed` | No | random | Reproducibility seed |
| `--enable-web-search` | No | false | Web search grounding (nano2 only) |

## Requirements

- Python 3.11+
- `fal_client` (`pip install fal-client`)
- `FAL_KEY` environment variable set

## File Structure

Generated outputs go to `~/.hermes/workspace/mediagen/`:

```
images/
  raw/           → Generated PNG files
  <base>.md      → One markdown file per image (embed + metadata)
external/        → Copies of user-provided input images
logs/            → Structured JSON logs per generation
```

## Testing

```bash
# Run unit tests (fast, no API calls, no cost)
python -m pytest tests/test_unit.py -v

# Run integration tests (calls real fal.ai API — costs ~$0.01-0.05)
python -m pytest tests/test_integration.py -v --run-integration

# Run all tests
python -m pytest tests/ -v
```

### Test structure

| File | Type | API calls? | Cost |
|------|------|-----------|------|
| `tests/test_unit.py` | Unit tests for pure functions | ❌ No | Free |
| `tests/test_integration.py` | Full pipeline with real API | ✅ Yes | ~$0.01-0.05 |

Integration tests are **skipped by default** — only run when `--run-integration` flag is passed, so you never accidentally spend money.

## License

MIT
