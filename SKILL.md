---
name: mediagen
description: "Generate and edit images/videos via fal.ai (FLUX.2, Nano Banana 2, Seedance), GPT Image 2 via ChatGPT/Codex OAuth, and Grok Imagine via xAI (grokimage2 / grokvideo). Script handles API calls, file I/O, logging, and .md creation. Use this skill instead of the native image_generate tool unless the user explicitly asks for it."
repository: https://github.com/bfranceschin/mediagen
---

# mediagen — Image & Video Generation (v2.1)

Generate and edit images and videos with full persistence, logging, and edit support.

**Backends:**
- **fal.ai** (`FAL_KEY`): `flux2`, `nano2`, `seedance2`
- **ChatGPT/Codex OAuth** (no OpenAI API key): `gptimage2`
- **xAI Grok Imagine** (OAuth first, then `XAI_API_KEY`): `grokimage2`, `grokvideo`

Default stack stays on fal.ai. Use `gptimage2` / `grokimage2` / `grokvideo` only when the user asks for those models. Do not silently switch Hermes global `image_gen.provider` or `video_gen.provider`.

### Support files
- `references/gptimage2-codex.md` — Codex OAuth API surface, sizes/quality, smoke-test without touching global image_gen, failure table
- `references/grok-imagine-xai.md` — xAI OAuth/API key, Imagine params, smoke-test without touching global providers, failure table
- `docs/FUTURE.md` — Grok features deliberately not in this CLI (reference-to-video, video edit/extend)

## When to Use

**Always use mediagen** for image/video generation unless the user explicitly asks for the native `image_generate` tool.

## Quick Reference

### Image Generate mode (no input images)

```bash
# Prefer Hermes venv (needed for gptimage2 auth helpers + fal_client):
PYTHON=~/.hermes/hermes-agent/venv/bin/python
SCRIPT=~/.hermes/skills/media/mediagen/scripts/mediagen.py

$PYTHON $SCRIPT \
  --model <flux2|nano2|gptimage2|grokimage2> \
  --prompt "your prompt here" \
  [--width 1280] [--height 720] \
  [--steps 28] [--seed 42] \
  [--enable-web-search] \
  [--quality low|medium|high]
```

### Image Edit mode (with input images)

```bash
$PYTHON $SCRIPT \
  --model <flux2|nano2|gptimage2|grokimage2> \
  --prompt "edit instruction here" \
  --inputs /path/to/image1.png [/path/to/image2.png ...] \
  [--width 1280] [--height 720] \
  [--steps 28] [--seed 42] \
  [--enable-web-search] \
  [--quality low|medium|high]
```

### Video Text-to-Video mode

```bash
$PYTHON $SCRIPT \
  --model <seedance2|grokvideo> \
  --prompt "your video prompt here" \
  [--resolution 720p] [--aspect-ratio 16:9] \
  [--duration 5] [--seed 42] \
  [--camera-fixed] [--no-audio]
```

### Video Image-to-Video mode (with start frame)

```bash
$PYTHON $SCRIPT \
  --model <seedance2|grokvideo> \
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
| `--model` | Yes | — | `flux2`, `nano2`, `gptimage2`, `grokimage2`, `seedance2`, or `grokvideo` |
| `--prompt` | Yes | — | Text prompt or edit instruction |
| `--inputs` | No | — | Input images: 1-4 for fal image edit, up to 16 for gptimage2 edit, up to 3 for grokimage2 edit, exactly 1 for image-to-video |
| `--seed` | No | random | Reproducibility seed (fal/seedance only; ignored by gptimage2 and Grok) |

### Image-only

| Argument | Default | Description |
|----------|---------|-------------|
| `--width` | 1280 | Output width in pixels (fal exact; gptimage2/grokimage2 mapped) |
| `--height` | 720 | Output height in pixels |
| `--steps` | 28 | Inference steps (**flux2 only**) |
| `--enable-web-search` | false | Web search grounding (**nano2 only**) |
| `--quality` | `medium` | gptimage2: `low`/`medium`/`high`; grokimage2: `low`/`medium` (**high rejected**) |

### Video-only

| Argument | Default | Description |
|----------|---------|-------------|
| `--end-image` | — | End frame image (**seedance2** i2v only; rejected by grokvideo) |
| `--resolution` | `720p` | `480p`, `720p`, or `1080p` |
| `--aspect-ratio` | `16:9` | seedance: `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, `21:9`, `auto`; grokvideo also `3:2`/`2:3`, not `21:9`/`auto` |
| `--duration` | 5 | seedance 4–12s; grokvideo 1–15s |
| `--camera-fixed` | false | Lock camera (**seedance2** only; rejected by grokvideo) |
| `--no-audio` | false | Disable audio (**seedance2** only; rejected by grokvideo) |

## Models

### FLUX.2 [dev] — `flux2`
- **Backend:** fal.ai
- **Endpoint:** `fal-ai/flux-2` (generate) / `fal-ai/flux-2/edit` (edit)
- **Strengths:** High-quality photorealistic and artistic images, full parameter control
- **Cost:** ~$0.012/MP (≈$0.01 for 1280×720)
- **Best for:** Most generation tasks, detailed artistic control

### Nano Banana 2 — `nano2`
- **Backend:** fal.ai
- **Endpoint:** `fal-ai/nano-banana-2` (generate) / `fal-ai/nano-banana-2/edit` (edit)
- **Strengths:** Multimodal reasoning, excellent text rendering, character consistency, web search grounding
- **Cost:** ~$0.05/image
- **Best for:** Images with text, complex composition reasoning, web-grounded generation

### GPT Image 2 — `gptimage2`
- **Backend:** ChatGPT/Codex OAuth (Hermes `openai-codex` auth). **No OpenAI API key** and **not fal.ai**
- **Endpoint label logs as:** `openai-codex/gpt-image-2` (+ `/edit`)
- **Auth prerequisite:** `hermes auth add openai-codex`
- **Quality tiers:** `--quality low|medium|high` (default `medium`)
- **Sizes:** mapped from `--width`/`--height` to nearest fixed GPT size:
  - landscape → `1536×1024`
  - square → `1024×1024`
  - portrait → `1024×1536`
- **Edit:** pass local images via `--inputs` (sent as Responses `input_image` data URLs)
- **Seed:** not supported by the API (logged as `n/a`)
- **Best for:** when you want GPT Image 2 charged/usage against ChatGPT, strong prompt adherence, or to save fal credits
- **Runtime:** always use Hermes venv Python so Codex token helpers + `httpx` resolve:
  `~/.hermes/hermes-agent/venv/bin/python`

### Grok Imagine Image — `grokimage2`
- **Backend:** xAI (`xai-oauth` first, then `XAI_API_KEY`). **Not fal.ai**
- **API model:** `grok-imagine-image-2.0`
- **Endpoints:** `https://api.x.ai/v1/images/generations` / `.../images/edits`
- **Auth prerequisite:** `hermes auth add xai-oauth --type oauth` (or `XAI_API_KEY`)
- **Quality:** `--quality low|medium` (default `medium`). `high` → ERROR
- **Sizes:** `--width/--height` mapped to Imagine `aspect_ratio`; long edge ≥1536 → `2k`, else `1k`. `1280×720` → `16:9` / `1k`
- **Edit:** `--inputs` as data URLs, up to 3
- **Seed:** not supported (`SEED=n/a`)
- **Runtime:** Hermes venv Python

### Grok Imagine Video — `grokvideo`
- **Backend:** xAI (`xai-oauth` first, then `XAI_API_KEY`). **Not fal.ai**
- **API model:** `grok-imagine-video-1.5`
- **Endpoints:** `POST https://api.x.ai/v1/videos/generations` + poll `GET /v1/videos/{request_id}`
- **Modes:** text-to-video, or image-to-video with exactly 1 start frame
- **Duration:** 1–15 seconds
- **Rejected flags:** `--end-image`, `--camera-fixed`, `--no-audio`
- **Seed:** not supported (`SEED=n/a`)
- **Download immediately:** result URLs expire

### Seedance 1.5 Pro — `seedance2`
- **Backend:** fal.ai
- **Endpoints:** `fal-ai/bytedance/seedance/v1.5/pro/text-to-video` / `.../image-to-video`
- **Strengths:** Broadcast-ready video with synchronized audio (dialogue, foley, music), cinematic camera control, start/end frame conditioning
- **Cost:** ~$0.26 for 720p 5s with audio (varies by resolution/duration)
- **Best for:** Short-form drama, music videos, talking-head avatars, product reveals, pre-visualization

## Type Inference

The script automatically determines image vs video mode from the `--model` argument:
- `flux2`, `nano2`, `gptimage2`, or `grokimage2` → **image** mode
- `seedance2` or `grokvideo` → **video** mode

No `--type` argument needed.

## Choosing a model

| Goal | Model |
|------|--------|
| Default quality, cheap iterations | `flux2` |
| Text in image / hard composition / spatial edits | `nano2` |
| GPT Image 2 via ChatGPT auth (no fal charge) | `gptimage2` |
| Grok Imagine image via xAI | `grokimage2` |
| Video (default fal) | `seedance2` |
| Grok Imagine video via xAI | `grokvideo` |

Keep fal as default while credits remain; pick `gptimage2` / `grokimage2` / `grokvideo` explicitly when desired.

## Output Parsing

### Success (exit 0)
```
FILENAME=20260417_090400_flux2.png PROMPT=a cute puppy SEED=12345
FILENAME=20260718_233100_gptimage2_low.png PROMPT=a green frog SEED=n/a
FILENAME=20260817_120000_grokimage2_low.png PROMPT=a blue square SEED=n/a
FILENAME=20260417_090400_seedance2.mp4 PROMPT=a bouncing ball SEED=12345
FILENAME=20260417_090400_seedance2_i2v.mp4 PROMPT=the ball bounces SEED=12345
FILENAME=20260817_120100_grokvideo.mp4 PROMPT=a bouncing ball SEED=n/a
```

### Error (exit 1)
```
ERROR=Timeout after 300s. Try again or use a different model.
ERROR=No ChatGPT/Codex OAuth credentials. Run: hermes auth add openai-codex --no-browser
ERROR=No xAI credentials. Run: hermes auth add xai-oauth --type oauth (or set XAI_API_KEY). Use Hermes venv Python.
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
  <base>.md      → One markdown file per image (embed + metadata; legacy local only)
videos/
  raw/           → Generated MP4 files
  <base>.md      → One markdown file per video (link + metadata; legacy local only)
external/        → Copies of user-provided input images
logs/            → Structured JSON logs per generation
receipts/        → Durable Media sync receipts (when Media API is configured)
```

Legacy `.md` sidecars are still written for local browsing compatibility. They are **never** uploaded to Hostkit Media as canonical assets.

### Optional Hostkit Media sync

After a successful generation (binary + JSON log on disk), mediagen may sync assets to Hostkit Media:

1. Create a local receipt under `receipts/`
2. Attempt one upload + generation-run POST (timeout `MEDIA_UPLOAD_TIMEOUT_SECONDS`, default 180)
3. Always print the Telegram/Hermes contract on the last stdout line:
   `FILENAME=<file> PROMPT=<prompt> SEED=<seed>`

Media failures do **not** change generation exit code `0`. Missing Media config is a no-op (local generation/Telegram unchanged).

```text
MEDIA_API_URL=https://media.example.dev
MEDIA_API_TOKEN_FILE=~/.hermes/secrets/media-api-token
MEDIA_UPLOAD_TIMEOUT_SECONDS=180
```

Role mapping on generation-run inputs:

- image edit: each `--inputs` path → `edit_source` by position
- image-to-video: first `--inputs` → `start_frame`; `--end-image` → `end_frame`

### Filename Convention

**Images (fal):** `<YYYYMMDD>_<HHMMSS>_<model>[_edit].{png,md,json}`
**Images (gptimage2):** `<YYYYMMDD>_<HHMMSS>_gptimage2_<quality>[_edit].{png,md,json}`
**Images (grokimage2):** `<YYYYMMDD>_<HHMMSS>_grokimage2_<quality>[_edit].{png,md,json}`
**Videos:** `<YYYYMMDD>_<HHMMSS>_<model>[_i2v].{mp4,md,json}`

Examples:
- `20260417_090400_flux2.png` (image generate)
- `20260417_090400_nano2_edit.png` (image edit)
- `20260718_233100_gptimage2_medium.png` (GPT Image 2 generate)
- `20260718_233130_gptimage2_low_edit.png` (GPT Image 2 edit)
- `20260817_120000_grokimage2_low.png` (Grok Imagine generate)
- `20260817_120030_grokimage2_medium_edit.png` (Grok Imagine edit)
- `20260417_090400_seedance2.mp4` (text-to-video)
- `20260417_090400_seedance2_i2v.mp4` (image-to-video)
- `20260817_120100_grokvideo.mp4` (Grok text-to-video)
- `20260817_120130_grokvideo_i2v.mp4` (Grok image-to-video)

## Tips

- Use `--seed` when you want reproducible results or iterate on a specific image/video (not available on gptimage2 / grokimage2 / grokvideo)
- Image mode (fal) has a 120s internal timeout; gptimage2, grokimage2, and video use 300s
- Grok image/video result URLs expire — the script downloads immediately into the workspace
- For image edit mode, previously generated images live at `~/.hermes/workspace/mediagen/images/raw/`
- For image-to-video, previously generated images can be used as start/end frames
- The script auto-creates directories if they don't exist
- Safety/censor settings are hardcoded to most permissive where the backend allows it (not overridable)
- Seedance video generation takes ~30-45s for a 5-second clip — longer for higher resolution/duration
- For gptimage2 / grokimage2 edits, keep source images under 25MB and use PNG/JPEG/GIF/WebP

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

- **FAL_KEY not set:** fal models (`flux2`/`nano2`/`seedance2`) fail without it. The key is stored in the Hermes env file. Ensure `FAL_KEY` is in `env_passthrough` in config.yaml — otherwise it won't reach the terminal shell. After adding to env_passthrough, a new Hermes session is required for it to take effect
- **gptimage2 auth missing:** needs `hermes auth add openai-codex` and Hermes venv Python so `agent.auxiliary_client` can refresh/read the token
- **grokimage2/grokvideo auth missing:** needs `hermes auth add xai-oauth --type oauth` (or `XAI_API_KEY`) and Hermes venv Python
- **Do not change global `image_gen.provider` or `video_gen.provider` for mediagen Grok/GPT** — mediagen talks to the APIs directly
- **Grok media URLs expire:** never return the remote URL to Telegram; the script always downloads first
- **grokimage2 `--quality high` is an error** — API only allows `low`/`medium`
- **grokvideo duration is 1–15s**, not Seedance's 4–12
- **grokvideo rejects `--end-image`, `--camera-fixed`, `--no-audio`**
- **gptimage2 account capability:** if ChatGPT/Codex account has image gen disabled, script returns a clear ERROR and you should fall back to flux2/nano2
- **fal_client.subscribe() has NO timeout param:** Do NOT pass `timeout=` to `fal_client.subscribe()` — it will raise TypeError. The script uses `signal.SIGALRM` for timeout instead
- **fal_client.upload() crashes:** Do NOT use `fal_client.upload(file_handle)` — it crashes with `TypeError: object of type '_io.BufferedReader' has no len()`. Always use `fal_client.upload_file(path_string)` which accepts a file path directly
- **Large input files:** fal_client.upload_file() handles this, but very large images (>10MB) may be slow; gptimage2 hard-caps inputs at 25MB
- **Nano2 aspect ratio:** The script converts --width/--height to aspect ratio automatically. Non-standard ratios may be rounded
- **gptimage2 aspect ratio:** free WxH is snapped to landscape/square/portrait fixed sizes (see Models)
- **Edit mode requires image_urls (fal):** The script uploads local files to fal.ai storage via upload_file() before calling the edit endpoint
- **gptimage2 edit** embeds local files as data URLs (no fal upload)
- **Nano2 doesn't return seed:** The nano2 API response has `"seed": null` even when a seed is provided. The script handles this by displaying the user-provided seed or "random". Do not rely on `result["seed"]` being non-null for nano2
- **"Exhausted balance" can be transient:** fal.ai sometimes returns this error temporarily even with valid balance. If it happens, retry once before assuming the balance is actually empty
- **FLUX.2 image_size:** Accepts both dict `{"width": N, "height": M}` and enum strings like `"landscape_4_3"`. The script uses dict format. FLUX.2 may adjust to the nearest supported resolution (e.g. 1280×720 → 1280×736)
- **Native image_generate tool upscaler cost:** The built-in `image_generate` tool auto-upscales at $0.10/MP via fal-ai/flux-vision-upscaler — this can cost 10-30x more than the generation itself. mediagen does NOT auto-upscale
- **Pricing reference:** FLUX.2 dev $0.012/MP (~$0.011 for 1280×720), Nano Banana 2 ~$0.05/image, Seedance 1.5 Pro ~$0.26 per 720p 5s video with audio (cheaper without audio: $1.20/1M tokens vs $2.40/1M with audio), Upscaler $0.10/MP; gptimage2 uses ChatGPT subscription quotas (not fal credits)
- **Seedance API param names:** Use `enable_audio` (not `generate_audio`), `static_video` (not `camera_fixed`). The script maps CLI flags to correct API names
- **Seedance video response:** Both text-to-video and image-to-video return `result["video"]["url"]` (same schema)
- **Seedance duration:** Must be 4-12 seconds. The script validates this
- **Seedance audio content checker is stricter than visual:** The `enable_safety_checker: False` flag only disables the **visual** post-generation filter. There is a separate **server-side content policy checker** that runs before/during generation and cannot be disabled. This checker is significantly more restrictive when `enable_audio=True` — combinations of input images (e.g. painted bodies, partial nudity) + action prompts (e.g. diving, jumping) + audio generation will be blocked, while the same image + prompt without audio passes fine. If you hit `content_policy_violation` with audio, retry with `--no-audio` — it often resolves the block
- **Seedance image-to-video:** Requires exactly 1 input image (`--inputs`). Optional end frame via `--end-image`. End frame without start frame is an error
- **Seedance content policy: audio pipeline is stricter than visual-only:** `enable_safety_checker: False` only disables the visual *post-generation* filter. There is a separate server-side content policy *pre-check* that runs during generation and is NOT controllable. The audio pipeline (`generate_audio: True`) has a significantly more restrictive checker — the same image + prompt can pass without audio but fail with audio. If you get `content_policy_violation` with Seedance + audio, retry with `--no-audio`. Workaround: generate video without audio, then add audio in post if needed.
- **Cross-model arg validation:** The script rejects incompatible args (e.g. `--camera-fixed` with `flux2`, `--enable-web-search` with `seedance2` / `gptimage2`, `--quality` with fal models)
- **Subagent with cheaper LLM not worth it:** For mediagen the LLM cost is negligible (~$0.001 per interaction) vs generation cost ($0.01-0.26). A subagent adds overhead, complexity, and may produce worse prompts
- **Skill category affects directory paths:** When creating skills with a category (e.g. 'media'), the directory becomes ~/.hermes/skills/<category>/<skill-name>/ — all paths in SKILL.md must include the category subdirectory or scripts won't be found
- **FLUX.2 edit mode preserves original composition:** When the edit instruction requires a radical change in camera angle or perspective (e.g. "show the scene from the opposite side"), FLUX.2 edit tends to re-render the same viewpoint with minor tweaks, ignoring the perspective change. **Use Nano Banana 2 (`nano2`) instead** — its multimodal reasoning understands spatial/compositional changes and correctly reinterprets the scene from a new angle. Example: "view from the opposite side of the pool" failed 3× with FLUX.2 edit (same back-view every time) but succeeded on first try with nano2 edit (correct front-facing view).
