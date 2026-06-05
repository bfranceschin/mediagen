---
name: mediagen
description: "Generate and edit images using fal.ai (FLUX.2, Nano Banana 2). Script handles all API calls, file I/O, logging, and .md creation. Use this skill instead of the native image_generate tool unless the user explicitly asks for it."
repository: https://github.com/bfranceschin/mediagen
---

# mediagen — Image & Video Generation (v2)

Generate and edit images and videos via fal.ai with full persistence, logging, and edit support.

## When to Use

**Always use mediagen** for image/video generation unless the user explicitly asks for the native `image_generate` tool.

## Quick Reference

### Image Generate mode (no input images)

```bash
python3 ~/.hermes/skills/media/mediagen/scripts/mediagen.py \
  --model <flux2|nano2> \
  --prompt "your prompt here" \
  [--width 1280] [--height 720] \
  [--steps 28] [--seed 42] \
  [--enable-web-search]
```

### Image Edit mode (with input images)

```bash
python3 ~/.hermes/skills/media/mediagen/scripts/mediagen.py \
  --model <flux2|nano2> \
  --prompt "edit instruction here" \
  --inputs /path/to/image1.png [/path/to/image2.png ...] \
  [--width 1280] [--height 720] \
  [--steps 28] [--seed 42] \
  [--enable-web-search]
```

### Video Text-to-Video mode

```bash
python3 ~/.hermes/skills/media/mediagen/scripts/mediagen.py \
  --model seedance2 \
  --prompt "your video prompt here" \
  [--resolution 720p] [--aspect-ratio 16:9] \
  [--duration 5] [--seed 42] \
  [--camera-fixed] [--no-audio]
```

### Video Image-to-Video mode (with start frame)

```bash
python3 ~/.hermes/skills/media/mediagen/scripts/mediagen.py \
  --model seedance2 \
  --prompt "motion and sound description" \
  --inputs /path/to/start_frame.png \
  [--end-image /path/to/end_frame.png] \
  [--resolution 720p] [--aspect-ratio 16:9] \
  [--duration 5] [--seed 42] \
  [--camera-fixed] [--no-audio]
```

## Arguments

### Shared

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--model` | Yes | — | `flux2`, `nano2`, or `seedance2` |
| `--prompt` | Yes | — | Text prompt or edit instruction |
| `--inputs` | No | — | Input images: 1-4 for image edit, exactly 1 for image-to-video |
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

## Models

### FLUX.2 [dev] — `flux2`
- **Endpoint:** `fal-ai/flux-2` (generate) / `fal-ai/flux-2/edit` (edit)
- **Strengths:** High-quality photorealistic and artistic images, full parameter control
- **Cost:** ~$0.012/MP (≈$0.01 for 1280×720)
- **Best for:** Most generation tasks, detailed artistic control

### Nano Banana 2 — `nano2`
- **Endpoint:** `fal-ai/nano-banana-2` (generate) / `fal-ai/nano-banana-2/edit` (edit)
- **Strengths:** Multimodal reasoning, excellent text rendering, character consistency, web search grounding
- **Cost:** ~$0.05/image
- **Best for:** Images with text, complex composition reasoning, web-grounded generation

### Seedance 1.5 Pro — `seedance2`
- **Endpoints:** `fal-ai/bytedance/seedance/v1.5/pro/text-to-video` / `.../image-to-video`
- **Strengths:** Broadcast-ready video with synchronized audio (dialogue, foley, music), cinematic camera control, start/end frame conditioning
- **Cost:** ~$0.26 for 720p 5s with audio (varies by resolution/duration)
- **Best for:** Short-form drama, music videos, talking-head avatars, product reveals, pre-visualization

## Type Inference

The script automatically determines image vs video mode from the `--model` argument:
- `flux2` or `nano2` → **image** mode
- `seedance2` → **video** mode

No `--type` argument needed.

## Output Parsing

### Success (exit 0)
```
FILENAME=20260417_090400_flux2.png PROMPT=a cute puppy SEED=12345
FILENAME=20260417_090400_seedance2.mp4 PROMPT=a bouncing ball SEED=12345
FILENAME=20260417_090400_seedance2_i2v.mp4 PROMPT=the ball bounces SEED=12345
```

### Error (exit 1)
```
ERROR=Timeout after 300s. Try again or use a different model.
```

## Response Format

### Image
```
✅ Image generated
File: <filename>.png
Prompt: <prompt used>
Model: <model>
Seed: <seed>
[embed image using MEDIA:~/.hermes/workspace/mediagen/images/raw/<filename>]
```

### Video
```
✅ Video generated
File: <filename>.mp4
Prompt: <prompt used>
Model: <model>
Seed: <seed>
Duration: <duration>s | Resolution: <resolution> | Audio: <yes|no>
[send video using MEDIA:~/.hermes/workspace/mediagen/videos/raw/<filename>]
```

## File Structure

All outputs go to `~/.hermes/workspace/mediagen/`:

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

Examples:
- `20260417_090400_flux2.png` (image generate)
- `20260417_090400_nano2_edit.png` (image edit)
- `20260417_090400_seedance2.mp4` (text-to-video)
- `20260417_090400_seedance2_i2v.mp4` (image-to-video)

## Tips

- Use `--seed` when you want reproducible results or iterate on a specific image/video
- For image edit mode, previously generated images live at `~/.hermes/workspace/mediagen/images/raw/`
- For image-to-video, previously generated images can be used as start/end frames
- The script auto-creates directories if they don't exist
- Safety/censor settings are hardcoded to most permissive (not overridable)
- Image mode has a 120s internal timeout; video mode has a 300s timeout
- Seedance video generation takes ~30-45s for a 5-second clip — longer for higher resolution/duration

## Video Prompting Guide

For best results with Seedance, structure prompts like a professional shot description:

| Element | Example |
|---------|---------|
| **Scene** | "Rainy Tokyo alley at night, neon reflections on wet pavement" |
| **Action** | "A woman in a trench coat turns and walks toward camera" |
| **Dialogue** | `"Wait, I forgot something"` (use quotes for speech) |
| **Camera** | "Slow dolly-in ending on a close-up" |
| **Audio/Foley** | "Rain on metal, distant traffic, her heels on concrete" |

**Pro tips:**
- For image-to-video, the start frame already defines the visual scene — focus prompts on **motion** and **sound**
- Limit clips to one location and 1-2 characters for maximum coherence
- Use `--camera-fixed` for tripod shots, omit for dynamic camera movement
- Use `--no-audio` when you only need visuals (saves cost too)

## Pitfalls

- **FAL_KEY not set:** Script will fail. The key is stored in the Hermes env file. Ensure `FAL_KEY` is in `env_passthrough` in config.yaml — otherwise it won't reach the terminal shell. After adding to env_passthrough, a new Hermes session is required for it to take effect
- **fal_client.subscribe() has NO timeout param:** Do NOT pass `timeout=` to `fal_client.subscribe()` — it will raise TypeError. The script uses `signal.SIGALRM` for timeout instead
- **fal_client.upload() crashes:** Do NOT use `fal_client.upload(file_handle)` — it crashes with `TypeError: object of type '_io.BufferedReader' has no len()`. Always use `fal_client.upload_file(path_string)` which accepts a file path directly
- **Large input files:** fal_client.upload_file() handles this, but very large images (>10MB) may be slow
- **Nano2 aspect ratio:** The script converts --width/--height to aspect ratio automatically. Non-standard ratios may be rounded
- **Edit mode requires image_urls:** The script uploads local files to fal.ai storage via upload_file() before calling the edit endpoint
- **Nano2 doesn't return seed:** The nano2 API response has `"seed": null` even when a seed is provided. The script handles this by displaying the user-provided seed or "random". Do not rely on `result["seed"]` being non-null for nano2
- **"Exhausted balance" can be transient:** fal.ai sometimes returns this error temporarily even with valid balance. If it happens, retry once before assuming the balance is actually empty
- **FLUX.2 image_size:** Accepts both dict `{"width": N, "height": M}` and enum strings like `"landscape_4_3"`. The script uses dict format. FLUX.2 may adjust to the nearest supported resolution (e.g. 1280×720 → 1280×736)
- **Native image_generate tool upscaler cost:** The built-in `image_generate` tool auto-upscales at $0.10/MP via fal-ai/flux-vision-upscaler — this can cost 10-30x more than the generation itself. mediagen does NOT auto-upscale
- **Pricing reference:** FLUX.2 dev $0.012/MP (~$0.011 for 1280×720), Nano Banana 2 ~$0.05/image, Seedance 1.5 Pro ~$0.26 per 720p 5s video with audio (cheaper without audio: $1.20/1M tokens vs $2.40/1M with audio), Upscaler $0.10/MP
- **Seedance API param names:** Use `enable_audio` (not `generate_audio`), `static_video` (not `camera_fixed`). The script maps CLI flags to correct API names
- **Seedance video response:** Both text-to-video and image-to-video return `result["video"]["url"]` (same schema)
- **Seedance duration:** Must be 4-12 seconds. The script validates this
- **Seedance audio content checker is stricter than visual:** The `enable_safety_checker: False` flag only disables the **visual** post-generation filter. There is a separate **server-side content policy checker** that runs before/during generation and cannot be disabled. This checker is significantly more restrictive when `enable_audio=True` — combinations of input images (e.g. painted bodies, partial nudity) + action prompts (e.g. diving, jumping) + audio generation will be blocked, while the same image + prompt without audio passes fine. If you hit `content_policy_violation` with audio, retry with `--no-audio` — it often resolves the block
- **Seedance image-to-video:** Requires exactly 1 input image (`--inputs`). Optional end frame via `--end-image`. End frame without start frame is an error
- **Seedance content policy: audio pipeline is stricter than visual-only:** `enable_safety_checker: False` only disables the visual *post-generation* filter. There is a separate server-side content policy *pre-check* that runs during generation and is NOT controllable. The audio pipeline (`generate_audio: True`) has a significantly more restrictive checker — the same image + prompt can pass without audio but fail with audio. If you get `content_policy_violation` with Seedance + audio, retry with `--no-audio`. Workaround: generate video without audio, then add audio in post if needed.
- **Cross-model arg validation:** The script rejects incompatible args (e.g. `--camera-fixed` with `flux2`, `--enable-web-search` with `seedance2`)
- **Subagent with cheaper LLM not worth it:** For mediagen the LLM cost is negligible (~$0.001 per interaction) vs generation cost ($0.01-0.26). A subagent adds overhead, complexity, and may produce worse prompts
- **Skill category affects directory paths:** When creating skills with a category (e.g. 'media'), the directory becomes ~/.hermes/skills/<category>/<skill-name>/ — all paths in SKILL.md must include the category subdirectory or scripts won't be found
- **FLUX.2 edit mode preserves original composition:** When the edit instruction requires a radical change in camera angle or perspective (e.g. "show the scene from the opposite side"), FLUX.2 edit tends to re-render the same viewpoint with minor tweaks, ignoring the perspective change. **Use Nano Banana 2 (`nano2`) instead** — its multimodal reasoning understands spatial/compositional changes and correctly reinterprets the scene from a new angle. Example: "view from the opposite side of the pool" failed 3× with FLUX.2 edit (same back-view every time) but succeeded on first try with nano2 edit (correct front-facing view).
