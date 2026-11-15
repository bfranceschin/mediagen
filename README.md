# mediagen

Image and video generation skill for [Hermes Agent](https://github.com/NousResearch/hermes-agent). Prefer existing subscriptions: GPT Image 2.5 Sunburst via ChatGPT/Codex OAuth for images, Grok Imagine Video 1.5 via SuperGrok OAuth for video. fal.ai alternatives remain explicit, separately billed options.

## Features

- **Image generation** via Codex GPT Image 2.5, Grok Image 2.0, FLUX.2 (dev), and Nano Banana 2.1
- **Image editing** with reference images (1-4 inputs)
- **Image upscale** via SeedVR2 (`seedvr` / alias `upscale`) — opt-in, never automatic
- **Video generation** via Seedance 1.5 Pro (text-to-video and image-to-video)
- **Start & end frame conditioning** for precise video transitions
- **Native audio generation** synchronized with video
- **Full persistence** — generated files, metadata (.md), and JSON logs
- **Optional Hostkit Media sync** — receipts + one-shot upload after generate (Telegram contract unchanged)
- **Reproducibility** — seed support for consistent results
- **Web search grounding** (Nano Banana 2.1)
- **Cinematic camera control** — dolly, pan, orbit, tripod mode

## Models

| Model | Key | Endpoint | Best for | Cost |
|-------|-----|----------|----------|------|
| FLUX.2 [dev] | `flux2` | `fal-ai/flux-2` | High-quality photorealistic/artistic images | ~$0.012/MP |
| Nano Banana 2.1 | `nano2` / `nano21` | `google/nano-banana-2.1` | Explicit 1K/2K/4K resolution and minimal/medium/high thinking | Token-based; measured ~$0.04 at 1K, variable |
| GPT Image 2.5 Sunburst | `gptimage2` | ChatGPT/Codex OAuth (`openai-codex/gpt-image-2.5-sunburst`) | Preferred images; `--image-model` also selects Flare or legacy Image 2 | ChatGPT quota |
| Grok Imagine Image 2.0 | `grokimage2` | `https://api.x.ai/v1/images/generations` | Grok image generate/edit; quality low/medium; 1k/2k | SuperGrok / `XAI_API_KEY` |
| SeedVR2 | `seedvr` (alias `upscale`) | `fal-ai/seedvr/upscale/image` | Opt-in image upscale 1–10× or 1080p–2160p | $0.001/MP out |
| Seedance 1.5 Pro | `seedance2` | `fal-ai/bytedance/seedance/v1.5/pro/text-to-video` | Short-form video with audio, dialogue, music | ~$0.26/5s@720p |
| Seedance 1.5 Pro | `seedance2` | `fal-ai/bytedance/seedance/v1.5/pro/image-to-video` | Animating images with start/end frame control | ~$0.26/5s@720p |
| Grok Imagine Video 1.5 | `grokvideo` | `https://api.x.ai/v1/videos/generations` | Text-to-video and image-to-video (1 start frame); 1–15s | SuperGrok / `XAI_API_KEY` |
| Wan 2.6 Flash | `wan26flash` / `wan2.6flash` / `wan` | `wan/v2.6/image-to-video/flash` | Explicit image-to-video only | Separately billed fal |
| Generic fal | `fal` | Explicit `--fal-endpoint` identifier | Explicit request/input/output schema | Separately billed fal |

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


### GPT Image 2.5 (ChatGPT/Codex OAuth)

Requires `hermes auth add openai-codex` and Hermes venv Python (`httpx` + token helpers).

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py   --model gptimage2   --prompt "a tiny flat blue frog icon"   --quality medium   --width 1024 --height 1024
```

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py   --model gptimage2   --prompt "make the sunglasses orange"   --inputs /path/to/image.png   --quality low
```

### Grok Imagine (xAI OAuth or XAI_API_KEY)

Requires Hermes venv Python. Prefers `hermes auth add xai-oauth`; separately billed `XAI_API_KEY` usage requires explicit `--allow-xai-api-key`. No silent paid fallback. Do not change Hermes `image_gen.provider` / `video_gen.provider`.

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model grokimage2 \
  --prompt "a tiny flat blue square icon" \
  --quality low \
  --width 1280 --height 720
```

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model grokvideo \
  --prompt "a red ball bouncing once on a white floor" \
  --duration 5 --aspect-ratio 16:9 --resolution 720p
```

### Image Upscale (SeedVR2)

```bash
python3 scripts/mediagen.py \
  --model seedvr \
  --inputs /path/to/image.png \
  --upscale-factor 2
```

`--model upscale` is an alias. `--prompt` is optional.

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

### Wan 2.6 Flash — explicit paid image-to-video

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model wan26flash --run-id my-wan-run \
  --inputs /path/to/start.png --prompt "The camera slowly approaches the subject" \
  --duration 5 --resolution 720p --seed 0 --no-audio
```

Aliases `wan2.6flash` and `wan` select the same Flash endpoint, never a different
Wan route. This is an explicit separately billed choice, **not** a fallback from
Grok or another model. Requires `FAL_KEY` and the Hermes venv's `fal_client`.

- Exactly one readable start image; each dimension must be 240–7680 pixels.
- Required prompt: 1–1500 characters, rejected rather than truncated.
- `--duration 5|10|15` is sent as a string. `--resolution 720p|1080p`;
  CLI default is **720p**, intentionally overriding the provider's 1080p default.
- `--negative-prompt` defaults to empty, maximum 500 characters.
- Prompt expansion defaults on; `--no-prompt-expansion` disables it.
  `--multi-shots` defaults off and requires expansion on.
- Audio defaults on; `--no-audio` disables it. Safety checking is always on.
- Optional integer `--seed` preserves zero; returned seed and `actual_prompt`
  are retained in sanitized generation metadata.
- No end frame, fixed camera or aspect-ratio controls: these and other unsupported
  controls fail before any provider upload. Optional provider `audio_url` is not exposed.

### Generic fal — explicit schema, no response heuristics

The following endpoint is illustrative, not a verified available model:

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/mediagen.py \
  --model fal --run-id my-custom-run --fal-endpoint example/model/edit \
  --operation edit --fal-kind image --inputs /path/to/input.png \
  --fal-args '{"prompt":"Change the background","seed":0,"images":[null],"strength":0.4}' \
  --fal-input-map '[{"input":0,"path":"images.0","role":"edit_source","kind":"image"}]' \
  --fal-output-map '[{"path":"images.0.url","kind":"image"}]'
```

`--fal-args` is an inline JSON object, not a file path. Duplicate keys and
non-finite values are rejected. Provider-specific parameters belong in this JSON;
built-in controls such as `--width`, `--duration` and `--no-audio` are rejected.
Optional `--prompt`/`--seed` may supply missing top-level JSON fields but cannot
contradict them. Prompts are not limited to Wan's length in generic mode.

Required `--operation`: `generate`, `edit`, `upscale`, `text-to-video`, or
`image-to-video`. Input roles follow the common executor contract: no inputs for
generate/text-to-video; ordered `edit_source` images for edit; one `upscale_source`
image for upscale; `start_frame` followed optionally by `end_frame` for i2v.
Every local input must have exactly one ordered mapping (zero-based `input`,
existing request `path`, `role`, `kind`). Input mapping paths cannot overlap.
No local paths are automatically detected or uploaded from arbitrary JSON fields.

`--fal-kind image|video` declares the output kind. `--fal-output-map` is a nonempty
ordered array of `{path,kind}` objects; all kinds must match the declaration.
Paths use dot-separated object keys and zero-based list indices, including root
list indices, e.g. `clips.0.media.url` or `0.clip.link`. No eval, bracket syntax,
wildcards or schema guessing. Multiple mapped outputs are persisted and published
in order. The explicit endpoint is also the generic model identifier; arguments,
input/output mappings, returned seed and sanitized provider result are logged.

Both new modes download to temporary local files, then use the common
`execute_generation` → `media_client` finalizer automatically in the same CLI
invocation. Downloads attach no provider authentication, disable inherited proxies,
allow only HTTPS `fal.media` and valid subdomains on port 443, reject redirects,
and are bounded by 120 seconds/100 MiB per output (300-second overall callback).
Other CDNs require a separately reviewed adapter change, not an arbitrary URL bypass.

Set `MEDIAGEN_WORKSPACE` to override the persistent workspace. Use `--run-id` to
repeat the **same command** for publication-only recovery, even after deleting
original inputs. Existing provider-uncertain intents fail closed, never regenerate.
Changing request identity conflicts rather than overwriting progress. Newly
generated local success remains successful if publication is pending; an explicit
incomplete retry exits 1. Publication state and run ID go to stderr; the final
stdout line remains `FILENAME=... PROMPT=... SEED=...` (first output only; all
outputs remain in the log/receipt). `--run-id` and adapter-specific flags are
rejected for older built-in routes, whose existing finalization remains intact.

## Arguments

### Shared

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--model` | Yes | — | `flux2`, `nano2`/`nano21`, `gptimage2`, `grokimage2`, `seedance2`, `grokvideo`, `seedvr`/`upscale`, `wan26flash`/`wan2.6flash`/`wan`, or `fal` |
| `--prompt` | Model-dependent | — | Text prompt/edit instruction; optional for upscale or supplied in generic fal JSON |
| `--inputs` | Model-dependent | — | Image edit/upscale/frame inputs; Wan requires exactly one image; generic fal uses explicit input bindings |
| `--seed` | No | random | Reproducibility seed |

### Image-only

| Argument | Default | Description |
|----------|---------|-------------|
| `--width` | generate 1280; edit inherit | Omit both on edit to keep the first input. Set both to force a format. |
| `--height` | generate 720; edit inherit | Must be set together with `--width`. |
| `--steps` | 28 | Inference steps (flux2 only) |
| `--enable-web-search` | false | Web search grounding (nano2 only) |

### Video-only

| Argument | Default | Description |
|----------|---------|-------------|
| `--end-image` | — | End frame image (seedance2 i2v only) |
| `--resolution` | `720p` | `480p`, `720p`, or `1080p` |
| `--aspect-ratio` | t2v 16:9; i2v inherit | Omit on i2v to match the start frame. Set to force a format. |
| `--duration` | 5 | seedance 4–12s; grokvideo 1–15s; Wan 5/10/15s; generic fal uses JSON |
| `--camera-fixed` | false | Lock camera (seedance2 only) |
| `--no-audio` | false | Disable audio (seedance2 or Wan); generic fal uses JSON |

## Requirements

- Python 3.11+
- `fal_client` (`pip install fal-client`) for fal models
- `FAL_KEY` for fal routes: `flux2`, `nano2`/`nano21`, `seedance2`, `seedvr`/`upscale`, Wan and generic `fal`
- Hermes venv + `hermes auth add openai-codex` for `gptimage2`
- Hermes venv + `hermes auth add xai-oauth` or `XAI_API_KEY` for `grokimage2`/`grokvideo`

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

A successful local generation remains successful when publication fails, with `PUBLICATION=<status>` on stderr and local artifacts retained. Omitting both publication settings intentionally disables sync; partial, empty or invalid settings produce `config_error` and a recoverable receipt. Reentering a Wan/generic run solely to retry publication returns nonzero if publication remains incomplete; see [publication receipts](docs/publication-receipts.md).

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

# Run the offline suite (global environment cleanup and socket guard)
python -m pytest tests/ -v --ignore=tests/test_integration.py
```

### Test structure

| File | Type | API calls? | Cost |
|------|------|-----------|------|
| `tests/test_unit.py` | Unit tests for pure functions | ❌ No | Free |
| `tests/test_media_client.py` | Media client + receipts (mocked HTTP) | ❌ No | Free |
| `tests/test_mediagen_media_sync.py` | Post-persist Media hook + FILENAME contract | ❌ No | Free |
| `tests/test_media_backfill.py` | Backfill parser/reconciliation (mocked HTTP) | ❌ No | Free |
| `tests/test_integration.py` | Full pipeline with real API | ✅ Yes | ~$0.01-0.26 |

Tests marked `integration` are **unconditionally skipped** by the current offline conftest. There is no supported `--run-integration` opt-in in this suite. Live generation/publication requires a separately approved verification procedure; do not weaken the offline guard to run it.

## License

MIT
