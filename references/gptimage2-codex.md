# GPT Image 2 via ChatGPT / Codex OAuth (`gptimage2`)

## When to use
- User asks for GPT Image 2 / ChatGPT image gen inside **mediagen**
- Want to avoid burning fal.ai credits while ChatGPT/Codex OAuth is signed in
- Do **not** switch Hermes global `image_gen.provider` just to use mediagen gptimage2 — the skill talks to Codex directly

## Auth
- Credential: Hermes `openai-codex` OAuth (`hermes auth add openai-codex --no-browser` on headless hosts)
- Token reader: `agent.auxiliary_client._read_codex_access_token` (+ `_codex_cloudflare_headers`)
- Always run the script with Hermes venv Python so helpers + `httpx` resolve:
  ```bash
  ~/.hermes/hermes-agent/venv/bin/python \
    ~/.hermes/skills/media/mediagen/scripts/mediagen.py \
    --model gptimage2 --prompt "..." --quality low
  ```

## API surface (script embeds this; do not invent REST /images paths)
- Base: `https://chatgpt.com/backend-api/codex/responses` (SSE stream)
- Host chat model: `gpt-5.5` (only hosts the tool call)
- Image tool: `type=image_generation`, `model=gpt-image-2`
- Qualities: `low` | `medium` | `high` (CLI `--quality`)
- Fixed sizes only:
  - landscape `1536x1024`
  - square `1024x1024`
  - portrait `1024x1536`
- mediagen maps `--width/--height` → nearest aspect (ratio ≥1.2 landscape, ≤0.833 portrait, else square)
- Edit: local files as Responses `input_image` data URLs (PNG/JPEG/GIF/WebP, ≤25MB, up to 16)
- Seed: **not supported** → stdout `SEED=n/a`
- Output: PNG bytes in SSE `image_generation_call.result` / `partial_image_b64`

## CLI / filenames
```bash
# generate
--model gptimage2 --quality medium --width 1024 --height 1024 --prompt "..."

# edit
--model gptimage2 --quality low --inputs /path/a.png --prompt "edit..."
```
Filenames: `YYYYMMDD_HHMMSS_gptimage2_<quality>[_edit].png`
Endpoint labels in md/log: `openai-codex/gpt-image-2` and `.../edit`

## Smoke test without changing Hermes global image_gen
Global `image_gen.use_gateway: true` / FAL can stay. Test Codex path only via mediagen CLI above, or one-shot importing the bundled plugin:
`plugins/image_gen/openai-codex` with `OPENAI_IMAGE_MODEL=gpt-image-2-low`.

## Failure signals
| Symptom | Meaning | Action |
|---------|---------|--------|
| `No ChatGPT/Codex OAuth credentials` | Not logged in / wrong Python | `hermes auth add openai-codex --no-browser`; use Hermes venv |
| `Image generation is not enabled for the current ChatGPT/Codex account` | Account lacks tool | fall back to `flux2`/`nano2` |
| HTTP 400 with tool_choice image_generation not found | same capability gap | fall back to fal models |
| `httpx not installed` | wrong interpreter | Hermes venv |

## Defaults / product choice
- Keep **fal.ai** (`flux2`/`nano2`/`seedance2`) as the day-to-day default
- Use **`gptimage2` when explicitly requested** or when avoiding fal spend is the goal
- Do **not** auto-promote gptimage2 or rewrite `image_gen.provider` during mediagen work unless asked

## Relation to native Hermes `image_generate`
- Native tool backend = whatever `image_gen.provider` / gateway says (often FAL via Nous)
- mediagen `gptimage2` is independent and preferred for skill workflows
- Native tool may auto-upscale on fal (costly); mediagen does not
