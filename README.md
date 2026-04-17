# mediagen

Image and video generation skill for [Hermes Agent](https://github.com/bfranceschin/hermes-agent) — powered by [fal.ai](https://fal.ai).

## Features

- **Image generation** via FLUX.2 (dev) and Nano Banana 2
- **Image editing** with reference images (1-4 inputs)
- **Video generation** via Seedance 1.5 Pro (text-to-video and image-to-video)
- **Start & end frame conditioning** for precise video transitions
- **Native audio generation** synchronized with video
- **Full persistence** — generated files, metadata (.md), and JSON logs
- **Reproducibility** — seed support for consistent results
- **Web search grounding** (Nano Banana 2 only)
- **Cinematic camera control** — dolly, pan, orbit, tripod mode

## Models

| Model | Key | Endpoint | Best for | Cost |
|-------|-----|----------|----------|------|
| FLUX.2 [dev] | `flux2` | `fal-ai/flux-2` | High-quality photorealistic/artistic images | ~$0.012/MP |
| Nano Banana 2 | `nano2` | `fal-ai/nano-banana-2` | Text rendering, complex composition, web grounding | ~$0.05/image |
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
  <base>.md      → One markdown file per image (embed + metadata)
videos/
  raw/           → Generated MP4 files
  <base>.md      → One markdown file per video (link + metadata)
external/        → Copies of user-provided input images
logs/            → Structured JSON logs per generation
```

### Filename Convention

**Images:** `<YYYYMMDD>_<HHMMSS>_<model>[_edit].{png,md,json}`
**Videos:** `<YYYYMMDD>_<HHMMSS>_<model>[_i2v].{mp4,md,json}`

## Testing

```bash
# Run unit tests (fast, no API calls, no cost)
python -m pytest tests/test_unit.py -v

# Run integration tests (calls real fal.ai API — costs ~$0.01-0.26)
python -m pytest tests/test_integration.py -v --run-integration

# Run all tests
python -m pytest tests/ -v
```

### Test structure

| File | Type | API calls? | Cost |
|------|------|-----------|------|
| `tests/test_unit.py` | Unit tests for pure functions | ❌ No | Free |
| `tests/test_integration.py` | Full pipeline with real API | ✅ Yes | ~$0.01-0.26 |

Integration tests are **skipped by default** — only run when `--run-integration` flag is passed, so you never accidentally spend money.

## License

MIT
