# SeedVR2 image upscale (`seedvr` / `upscale`)

## When to use
- User asks to **upscale** / enlarge / 2× / 4K an **existing** local image
- Do **not** run after every generate. Opt-in only
- Do **not** fake this with `gptimage2` or `grokimage2` edit — those redraw

## Auth
- `FAL_KEY` (same as flux2/nano2)
- Hermes venv Python for `fal_client`

## API
- Endpoint: `fal-ai/seedvr/upscale/image`
- Input: `image_url` (upload via `fal_client.upload_file(path)`, never `upload(handle)`)
- Factor mode: `upscale_mode=factor`, `upscale_factor` 1–10 (CLI default 2)
- Target mode: `upscale_mode=target`, `target_resolution` `1080p`|`1440p`|`2160p`
- Output: `result["image"]["url"]` (singular `image`, not `images[]`)
- `output_format`: png
- Price: $0.001 per output megapixel
- Timeout: 300s via SIGALRM (do not pass `timeout=` to `subscribe`)

## CLI
```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model seedvr \
  --inputs /path/to/image.png \
  [--upscale-factor 2] \
  [--resolution 2160p] \
  [--seed 42]
```

`--model upscale` aliases `seedvr`. `--prompt` optional → stdout `PROMPT=upscale`.

Exactly one `--inputs`. `--width`/`--height` rejected. Custom `--upscale-factor` cannot combine with a target `--resolution`.

Filenames: `YYYYMMDD_HHMMSS_seedvr_upscale.png`

Media: `operation=upscale`, input role `upscale_source`.

## Failure signals
| Symptom | Meaning | Action |
|---------|---------|--------|
| `Upscale requires exactly one input image` | 0 or >1 `--inputs` | Pass one file |
| `--upscale-factor and --resolution target cannot be combined` | Both modes set | Drop one |
| `No upscaled image returned` | Unexpected fal schema | Retry; check fal dashboard |
| `FAL_KEY` / fal API error | Missing key or billing | Same as other fal models |
