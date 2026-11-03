---
name: mediagen
description: "Generate/edit media: Codex GPT, SuperGrok, fal Nano 2.1."
repository: https://github.com/bfranceschin/mediagen
---

# mediagen — subscription-first media generation

Use this skill for image/video generation, editing and upscaling unless the user explicitly requests the native tool. Run the installed CLI; do not change Hermes global providers.

## Selection policy

1. **Images:** prefer ChatGPT/Codex OAuth (`gptimage2`, upgraded GPT Image 2.5 Sunburst). Grok Image 2.0 (`grokimage2`, SuperGrok OAuth) is the other subscription-backed option.
2. **Video:** prefer `grokvideo` (Grok Imagine Video 1.5 via SuperGrok OAuth).
3. Evaluate separately billed fal options only when subscriptions lack quota, required capability, availability, or adequate results. Explain additional spend before falling back. Never silently use an API key instead of OAuth.
4. Nano Banana is upgraded to **2.1**; FLUX.2 dev and Seedance 1.5 Pro are retained, not replaced. Do not add MiniMax/Wan or change global providers without authorization.
5. OAuth authentication identifies the credential route, not a guarantee of unlimited or included usage. Respect actual account entitlements and quota errors.

## Runtime

```bash
PYTHON=~/.hermes/hermes-agent/venv/bin/python
SCRIPT=~/.hermes/skills/media/mediagen/scripts/mediagen.py
$PYTHON $SCRIPT --help
```

Always use Hermes venv (auth helpers, httpx, fal_client). CLI `--model` is explicit; selection policy above guides the agent, not an automatic cross-provider fallback.

## Common commands

```bash
# Preferred image route (ChatGPT/Codex subscription)
$PYTHON $SCRIPT --model gptimage2 --quality high --prompt "..."
# Edit: omit dimensions to inherit source framing
$PYTHON $SCRIPT --model gptimage2 --quality high --inputs /path/input.png --prompt "..."
# SuperGrok image alternative
$PYTHON $SCRIPT --model grokimage2 --quality medium --prompt "..."
# Preferred video route (SuperGrok)
$PYTHON $SCRIPT --model grokvideo --duration 5 --resolution 720p --prompt "..."
$PYTHON $SCRIPT --model grokvideo --inputs /path/start.png --duration 5 --prompt "..."
# Separately billed Nano Banana 2.1; legacy CLI name retained
$PYTHON $SCRIPT --model nano2 --prompt "..."
# Separately billed FLUX alternative
$PYTHON $SCRIPT --model flux2 --width 1280 --height 720 --steps 28 --prompt "..."
# Opt-in upscale; never chain automatically
$PYTHON $SCRIPT --model seedvr --inputs /path/input.png --upscale-factor 2
```

GPT selector: `--image-model gpt-image-2.5-sunburst|gpt-image-2.5-flare|gpt-image-2`; default Sunburst (override default with `MEDIAGEN_GPT_IMAGE_MODEL`). Nano: `nano2` and `nano21` both select 2.1; `--resolution 1K|2K|4K` (default 1K), `--thinking-level minimal|medium|high` (default medium). Explicit separately billed xAI API-key opt-in: `--allow-xai-api-key`. Preserve the `FILENAME=... PROMPT=... SEED=...` last-line output contract.

## Models and routes

| CLI model | Backend / actual model | Role |
|---|---|---|
| `gptimage2` | Codex OAuth / GPT Image 2.5 Sunburst | Preferred images; legacy name retained |
| `grokimage2` | xAI OAuth / `grok-imagine-image-2.0` | Subscription image alternative, `medium` quality |
| `grokvideo` | xAI OAuth / `grok-imagine-video-1.5` | Preferred video |
| `nano2` / `nano21` | fal / `google/nano-banana-2.1` and `/edit` | Paid Nano alternative; upgraded from 2 |
| `flux2` | fal / `fal-ai/flux-2` and `/edit` | Paid budget alternative; unchanged |
| `seedance2` | fal / `fal-ai/bytedance/seedance/v1.5/pro/{text-to-video,image-to-video}` | Paid feature alternative; **not Seedance 2** |
| `seedvr` / `upscale` | fal / `fal-ai/seedvr/upscale/image` | Opt-in super-resolution |

Nano 2.1 bills by tokens, not a fixed per-image tariff. Published fal measurements (short 16:9 prompt, minimal/medium thinking) are ~$0.0396 at 1K and ~$0.0593 at 2K; actual cost varies with prompt, references, search and thinking. Source: https://fal.ai/nano-banana-2.1 . Do not reuse Nano 2's old ~$0.05 estimate.

FLUX.2 dev generation: ~$0.012/MP; edit may bill inputs too. Seedance 1.5 Pro: ~$0.26 per 720p 5s with audio, roughly half without. SeedVR2: ~$0.001/MP output. Recheck live rates before estimates. Subscription usage is subject to account limits, not equivalent to unlimited free generation.

## Framing and parameters

- Generate defaults to 1280×720. On image edit omit width/height to inherit the first input; to change format explicitly pass **both**. GPT maps to fixed supported boxes; Grok snaps to supported ratios. A prompt alone does not select output dimensions.
- Nano width/height controls aspect ratio; use the Nano-specific resolution control for 1K/2K/4K. Thinking is separately selectable. Never assume a larger width alone selects 2K.
- GPT quality and image-model selector must be validated together; extra `xhigh`/`max` tiers belong to 2.5, not legacy GPT Image 2. The top-level Codex chat model hosts the tool and is not the image model.
- Grok image supports `low`/`medium`, not `high`. Default `medium` already requests finer detail. Long edge ≥1536 selects 2K, otherwise 1K.
- On image-to-video omit `--aspect-ratio` to inherit the start frame; text-to-video defaults to 16:9. Grok 4:5 snaps to 3:4.
- Grok video supports 1–15s; rejects `--end-image`, `--camera-fixed`, `--no-audio` in this CLI. Seedance supports 4–12s, optional end frame and those controls.
- Seeds work for FLUX/Seedance/SeedVR; GPT and Grok have no seed. Nano may return a null seed: do not treat provided seeds as guaranteed reproducibility.
- Upscale takes exactly one input. Use factor 1–10 (default 2) or target `--resolution 1080p|1440p|2160p`, not both. GPT/Grok edit-at-larger-size is a redraw, not super-resolution.

## Persistence and delivery

All outputs live in `~/.hermes/workspace/mediagen/`:
- `images/raw/`, `videos/raw/`: persistent media binaries
- `images/*.md`, `videos/*.md`: local legacy sidecars
- `external/`: copies of user inputs
- `logs/`: generation JSON (record real provider, image model, quality and parameters)
- `receipts/`: durable optional Hostkit Media sync receipts

Generated media must be downloaded immediately; remote Grok/fal URLs can expire. Deliver the local file with `MEDIA:<absolute path>`; include model and relevant quality/duration settings. No need to expose internal request URLs.

Hostkit Media sync is optional after local persistence. `MEDIA_API_URL`, `MEDIA_API_TOKEN_FILE`, `MEDIA_UPLOAD_TIMEOUT_SECONDS` configure it. Upload binary assets and generation runs, not legacy markdown. Sync errors must not turn a successful local generation into failure or break final stdout. Input roles: `edit_source`, `upscale_source`, `start_frame`, `end_frame`. Media seed is integer or null, never `"n/a"`.

## Important failure handling

- Never silently cross from subscription OAuth to separately billed API keys/fal. Stop with a clear error; use the CLI's explicit opt-in for API-key billing only with user authorization.
- Missing old Codex token helper is not proof of logout. Use `hermes_cli.auth_codex.resolve_codex_runtime_credentials()` when needed, without printing credentials.
- Codex host model may be overridden by `MEDIAGEN_CODEX_CHAT_MODEL`; choose a verified account-supported model. Changing the host alone does not upgrade the image model.
- Public OpenAI API model support does not establish parity on `chatgpt.com/backend-api/codex/responses`; smoke-test the actual OAuth route. Retain explicit legacy selection rather than quietly downgrading on errors.
- fal requires `FAL_KEY`. Never print secrets. Missing/expired auth or exhausted subscription quota must not trigger paid fallback.
- `fal_client.subscribe()` has no timeout argument; use the script's timeout mechanism. Upload local files with `fal_client.upload_file(path)`, not `upload(file_handle)`.
- FLUX.2 may adjust requested dimensions (1280×720 → 1280×736). FLUX edit tends to preserve viewpoint; for radical perspective/composition changes prefer subscription GPT/Grok first, Nano as a paid alternative.
- Seedance native-audio content validation can be stricter than visual-only. Offer `--no-audio` when appropriate, without retrying indefinitely or assuming visual flags disable server-side policy.
- Default timeouts: fal image 120s; GPT/Grok/upscale/video 300s. Treat timeouts as uncertain request outcomes rather than blindly resubmitting repeatedly.

## References

- `references/gptimage2-codex.md`: Codex tool selection, auth, verification and quality
- `references/grok-imagine-xai.md`: xAI OAuth, billing opt-in, image/video behavior
- `references/seedvr-upscale.md`: upscaler schema and CLI
- `docs/FUTURE.md`: out-of-scope features; not proof a feature is implemented
