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
4. Nano Banana is upgraded to **2.1**; FLUX.2 dev and Seedance 1.5 Pro are retained, not replaced. Wan Flash and generic fal are explicit separately billed opt-ins, never automatic fallbacks. Do not add models or change global providers without authorization.
5. OAuth authentication identifies the credential route, not a guarantee of unlimited or included usage. Respect actual account entitlements and quota errors.

## Runtime

```bash
PYTHON=~/.hermes/hermes-agent/venv/bin/python
SCRIPT="${HERMES_HOME:-$HOME/.hermes}/skills/media/mediagen/scripts/mediagen.py"
$PYTHON $SCRIPT --help
```

Always use Hermes venv (auth helpers, httpx, fal_client). CLI `--model` is explicit; selection policy above guides the agent, not an automatic cross-provider fallback.

Keep `HERMES_HOME` pointed at the active credential profile. This profile's script locates the source checkout independently: explicit `HERMES_AGENT_DIR`, profile-local checkout, named profile's base checkout, `~/.hermes/hermes-agent`, installed `hermes_cli`, then venv-adjacent locations. Ordinary named-profile use needs no `HERMES_AGENT_DIR` override and works outside the checkout. An explicit override is authoritative; fix an invalid override rather than changing credential homes. Missing code or xAI helper imports now report a code/import error instead of falsely claiming that OAuth credentials are missing. Other runtime credential errors retain existing handling.

For a read-only regression check (no image/video generation or paid fallback), run outside the checkout:

```bash
env -u HERMES_AGENT_DIR -u PYTHONPATH \
  HERMES_HOME="$HOME/.hermes/profiles/media-maker" MEDIAGEN_TEST_LIVE=1 \
  "$PYTHON" -I -B "${SCRIPT%/*}/test_mediagen_auth_paths.py"
```

The opt-in live test checks `xai-oauth`, preserved credential home and authenticated `GET /models` status 200, without printing tokens. Without `MEDIAGEN_TEST_LIVE=1`, tests are offline. A successful models request verifies authentication, not media-generation quota or model entitlement. Diagnose import failures before requesting re-authentication; never silently switch to API-key billing.

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
| `wan26flash` / `wan2.6flash` / `wan` | fal / `wan/v2.6/image-to-video/flash` | Explicit paid Wan 2.6 Flash i2v only |
| `fal` | fal / explicit `--fal-endpoint` | Explicit paid generic schema; never infer output fields |

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

## Explicit Wan Flash and generic fal

`--model wan26flash --inputs /path/start.png --prompt "..." --run-id my-run`
uses only `wan/v2.6/image-to-video/flash`. One readable image, dimensions each
240–7680; prompt required, max1500; negative prompt max500 (`--negative-prompt`).
Duration `5|10|15` (string on wire), resolution `720p|1080p`; CLI defaults 5/720p,
not the provider's 1080p resolution default. Expansion defaults true
(`--no-prompt-expansion`); `--multi-shots` requires expansion. Audio defaults true
(`--no-audio`); safety checker always true. Optional integer seed includes zero.
Reject end-image/camera-fixed/aspect-ratio and unsupported controls before upload.
No optional audio URL input is exposed. This route is separately billed, never a
subscription fallback, and has not been live-tested by the offline implementation.

Generic `--model fal` requires endpoint identifier, inline JSON `--fal-args`,
`--operation`, `--fal-kind image|video`, and nonempty JSON `--fal-output-map`
(`[{"path":"images.0.url","kind":"image"}]`). Map every local `--inputs` item
explicitly in order with `--fal-input-map`
(`[{"input":0,"path":"images.0","role":"edit_source","kind":"image"}]`),
using existing JSON placeholder locations and executor-supported roles. No path
overlap, eval, wildcards, magic local-path detection or provider schema inference.
Dot paths support list indices, including root lists. Multiple mapped outputs
must match declared kind. Put custom controls in JSON, not built-in flags. Retain
full generic prompts, request JSON/mappings, explicit endpoint/model and returned
seed in sanitized metadata; do not impose Wan's prompt limit on other endpoints.

Both routes use persistent inputs and LOCAL callback outputs through the common
executor/finalizer: one CLI invocation generates, persists and attempts optional
Media publication. `MEDIAGEN_WORKSPACE` overrides the workspace. Repeat the same
command/run ID to retry publication without generation or original inputs; uncertain
provider attempts require manual reconciliation, not replay. Incomplete explicit
publication retries exit nonzero while retaining the final FILENAME stdout line;
PUBLICATION/run ID diagnostics go to stderr. Adapter/run-id flags are not available
on legacy built-ins. CDN downloads are unauthenticated HTTPS only, exact fal.media
boundary, no redirects/proxy inheritance, bounded time/bytes; never widen this to
an arbitrary SSRF fetcher or log signed URLs. See README for complete examples.

## Persistence and delivery

All outputs live in `~/.hermes/workspace/mediagen/`:
- `images/raw/`, `videos/raw/`: persistent media binaries
- `images/*.md`, `videos/*.md`: local legacy sidecars
- `external/`: copies of user inputs
- `logs/`: generation JSON (record real provider, image model, quality and parameters)
- `receipts/`: durable optional Hostkit Media sync receipts

Generated media must be downloaded immediately; remote Grok/fal URLs can expire. Deliver the local file with `MEDIA:<absolute path>`; include model and relevant quality/duration settings. No need to expose internal request URLs.

For publication-only recovery, never call generation providers. Load the generating profile's `.env` explicitly, then launch the CLI by subprocess with the inherited environment. If using `runpy.run_path`, insert the script directory into `sys.path` first: the optional `media_client` import otherwise silently disables sync. Check `load_config().enabled` without printing credentials.

Hostkit Media multipart diagnostics: a 400 `invalid_multipart` for a large valid MP4 can originate before Busboy. Check the live Next middleware configuration and application logs; Next 15.5.22 defaults `experimental.middlewareClientMaxBodySize` to 10 MiB and truncates cloned bodies, yielding `Unexpected end of form`. Match the app's 100 MiB file budget plus multipart overhead (101 MiB) in the built config, retaining the streaming parser and edge limits. This requires a rebuilt standalone image, not a `MAX_UPLOAD_BYTES` env-only change. Verify an actual >10 MiB upload after rollout.

Recover only named targets using their original asset/run idempotency keys; reuse and remotely verify existing input IDs. `media_sync.py retry` ignores `failed` receipts, so an explicitly selected, diagnosed failed receipt needs `sync_receipt` directly after the cause is fixed. Do not reset or bulk-replay unrelated receipts. Preserve prompts, seed, provider/auth route, model, params and input roles from logs; publish existing FFmpeg compositions honestly as local processing, not a model generation. Confirm each item through GET, original-byte SHA-256, ready poster, catalog uniqueness, run lineage and rendered gallery links. Internal UID-1001 trusted-header gallery checks are not proof of human Google/browser login.

Hostkit Media sync is optional after local persistence. `MEDIA_API_URL`, `MEDIA_API_TOKEN_FILE`, `MEDIA_UPLOAD_TIMEOUT_SECONDS` configure it. Upload binary assets and generation runs, not legacy markdown. Sync errors must not turn a successful local generation into failure or break final stdout. Input roles: `edit_source`, `upscale_source`, `start_frame`, `end_frame`. Media seed is integer or null, never `"n/a"`.

## Important failure handling

- Never silently cross from subscription OAuth to separately billed API keys/fal. Stop with a clear error; use the CLI's explicit opt-in for API-key billing only with user authorization.
- Missing old Codex token helper is not proof of logout. Use `hermes_cli.auth_codex.resolve_codex_runtime_credentials()` when needed, without printing credentials.
- Codex host model may be overridden by `MEDIAGEN_CODEX_CHAT_MODEL`; choose a verified account-supported model. Changing the host alone does not upgrade the image model.
- Public OpenAI API model support does not establish parity on `chatgpt.com/backend-api/codex/responses`; smoke-test the actual OAuth route. Retain explicit legacy selection rather than quietly downgrading on errors.
- fal requires `FAL_KEY`. Never print secrets. If the CLI reports `MissingCredentialsError`, check whether the active profile's `.env` contains the key without exposing its value; the standalone script may not load that file. Load only that profile's `.env` with `dotenv.load_dotenv()` before launching the CLI as a subprocess with the inherited environment. If using `runpy.run_path()` instead, first insert the script's parent directory into `sys.path`: otherwise the optional sibling `media_client` import silently fails and generation succeeds without Media synchronization or receipts. Do not borrow credentials from another profile. Missing/expired auth or exhausted subscription quota must not trigger paid fallback.
- `fal_client.subscribe()` has no timeout argument; use the script's timeout mechanism. Upload local files with `fal_client.upload_file(path)`, not `upload(file_handle)`.
- FLUX.2 may adjust requested dimensions (1280×720 → 1280×736). FLUX edit tends to preserve viewpoint; for radical perspective/composition changes prefer subscription GPT/Grok first, Nano as a paid alternative.
- Seedance native-audio content validation can be stricter than visual-only. Offer `--no-audio` when appropriate, without retrying indefinitely or assuming visual flags disable server-side policy.
- Default timeouts: fal image 120s; GPT/Grok/upscale/video 300s. Treat timeouts as uncertain request outcomes rather than blindly resubmitting repeatedly.

## References

- `references/gptimage2-codex.md`: Codex tool selection, auth, verification and quality
- `references/grok-imagine-xai.md`: xAI OAuth, billing opt-in, image/video behavior
- `references/seedvr-upscale.md`: upscaler schema and CLI
- `docs/FUTURE.md`: out-of-scope features; not proof a feature is implemented
