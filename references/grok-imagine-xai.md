# Grok Imagine via xAI (`grokimage2` / `grokvideo`)

## When to use
- User asks for Grok Imagine / grokimage2 / grokvideo inside **mediagen**
- Want image or short video billed against SuperGrok OAuth or `XAI_API_KEY`
- Do **not** switch Hermes global `image_gen.provider` or `video_gen.provider` just to use these models — the skill talks to `api.x.ai` directly

## Auth
- Preferred: Hermes `xai-oauth` (`hermes auth add xai-oauth --type oauth`)
- Resolver: `tools.xai_http.resolve_xai_http_credentials` (OAuth pool first), then `hermes_cli.auth.resolve_xai_oauth_runtime_credentials`, then `XAI_API_KEY`
- Always run the script with Hermes venv Python so helpers + `httpx` resolve:
  ```bash
  ~/.hermes/hermes-agent/venv/bin/python \
    ~/.hermes/skills/media/mediagen/scripts/mediagen.py \
    --model grokimage2 --prompt "..." --quality low
  ```

## API surface (script embeds this; do not invent paths)
- Image generate: `POST https://api.x.ai/v1/images/generations`
- Image edit: `POST https://api.x.ai/v1/images/edits` (local files as data URLs; 1 image → `image`, 2–3 → `images`)
- Video: `POST https://api.x.ai/v1/videos/generations` then `GET /v1/videos/{request_id}` until `done` | `failed` | `expired`
- Image model: `grok-imagine-image-2.0` (alias `grokimage2`)
- Video model: `grok-imagine-video-1.5` (alias `grokvideo`)
- Image quality: `low` | `medium` (default `medium`). `high` is rejected
- Image size: `--width/--height` → nearest Imagine `aspect_ratio`; `max(w,h) ≥ 1536` → `2k`, else `1k`. `1280×720` → `16:9` / `1k`
- Video duration: 1–15 seconds (not Seedance's 4–12)
- Video reuses `--duration`, `--aspect-ratio`, `--resolution`
- grokvideo rejects `--end-image`, `--camera-fixed`, `--no-audio`
- Seed: **not supported** → stdout `SEED=n/a`
- Media URLs are temporary (`imgen.x.ai` / `vidgen.x.ai`) — download immediately into the workspace

## CLI / filenames
```bash
# image generate
--model grokimage2 --quality low --width 1280 --height 720 --prompt "..."

# image edit (up to 3 refs)
--model grokimage2 --quality medium --inputs /path/a.png --prompt "edit..."

# text-to-video
--model grokvideo --duration 5 --aspect-ratio 16:9 --resolution 720p --prompt "..."

# image-to-video (exactly 1 start frame)
--model grokvideo --inputs /path/start.png --duration 5 --prompt "motion..."
```
Filenames:
- `YYYYMMDD_HHMMSS_grokimage2_<quality>[_edit].png`
- `YYYYMMDD_HHMMSS_grokvideo[_i2v].mp4`

Endpoint labels in md/log: the real `https://api.x.ai/v1/...` URL. Provider is `xai-oauth` or `xai`, never `fal`.

## Smoke test without changing Hermes global providers
Global `image_gen.provider` / `video_gen.provider` can stay on fal. Test only via mediagen CLI above.

Cheap smoke:
```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model grokimage2 --quality low --width 1280 --height 720 \
  --prompt "a tiny flat blue square icon, solid background"
```

## Failure signals
| Symptom | Meaning | Action |
|---------|---------|--------|
| `No xAI credentials` | Not logged in / wrong Python | `hermes auth add xai-oauth --type oauth`; use Hermes venv; or set `XAI_API_KEY` |
| HTTP 401/403 + quota hint | Auth expired or out of credits | Re-auth or add credits; fall back to `flux2`/`seedance2` |
| `--quality high is not supported for grokimage2` | API only has low/medium | Use `low` or `medium` |
| `--end-image` / `--camera-fixed` / `--no-audio` | Not on grokvideo | Drop the flag or use `seedance2` |
| `httpx not installed` | wrong interpreter | Hermes venv |

## Defaults / product choice
- Keep **fal.ai** (`flux2`/`nano2`/`seedance2`) as the day-to-day default
- Use **`grokimage2` / `grokvideo` when explicitly requested**
- Do **not** auto-promote Grok or rewrite `image_gen.provider` / `video_gen.provider`

## Out of scope (see docs/FUTURE.md)
- Reference-to-video (needs `--refs` + a new Media input role)
- Video edit / extend (need a still-valid Imagine result URL, not a local mp4)

## Relation to native Hermes tools
- Native `image_generate` / `video_generate` backend = whatever Hermes config says
- mediagen Grok path is independent and preferred for skill workflows
