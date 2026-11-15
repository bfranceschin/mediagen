# GPT Image via ChatGPT / Codex OAuth (`gptimage2`)

## Selection and auth

Prefer the existing ChatGPT/Codex subscription route before separately billed alternatives. The legacy CLI alias `gptimage2` is retained even when selecting a newer model. Never change global Hermes providers and never automatically fall back to the OpenAI paid API or fal on errors.

Use Hermes venv: `~/.hermes/hermes-agent/venv/bin/python`. Credential is Hermes `openai-codex`; use `hermes auth add openai-codex` only when credentials are actually missing. Current credential helper is `hermes_cli.auth_codex.resolve_codex_runtime_credentials()`; older Hermes versions may use `agent.auxiliary_client`. Do not print tokens.

## API surface

- URL: `https://chatgpt.com/backend-api/codex/responses`, streamed SSE.
- Default image tool model: `gpt-image-2.5-sunburst`.
- Other explicit selections: `gpt-image-2.5-flare`, legacy `gpt-image-2`.
- Top-level chat model only hosts the tool. Use verified account support; default `gpt-6.1-sol`, with `MEDIAGEN_CODEX_CHAT_MODEL` override.
- The tool remains `type: image_generation`; changing chat model does not itself upgrade the image model.
- Image 2.5 supports `low`, `medium`, `high`, `xhigh`, `max`; legacy Image 2 supports low/medium/high. Default CLI quality remains medium; prefer high for final-quality requests.
- Current CLI framing maps requested aspect to landscape `1536x1024`, square `1024x1024`, portrait `1024x1536`. This is an integration constraint, not a claim newer APIs only accept these sizes.
- Edit inputs are local PNG/JPEG/GIF/WebP data URLs, up to 16, each <=25 MB.
- No seed; log null for Media sync and display `n/a` in user-facing stdout.

## Verification

A live Codex OAuth generation using the Sunburst tool selector, host `gpt-6.1-sol`, high quality and 1024x1024 successfully returned a verified PNG. Acceptance of a requested model does not independently prove the server's internal routing; record a reported served model when available and do not invent one.

Public API docs: https://developers.openai.com/api/docs/guides/tools-image-generation
Availability announcement: https://openai.com/index/introducing-chatgpt-images-2-5/

Public API model support alone does not prove the private Codex OAuth route supports all the same parameters. Validate added selectors and qualities on the actual account; do not silently downgrade when unsupported.

## CLI and persistence

```bash
PYTHON=~/.hermes/hermes-agent/venv/bin/python
SCRIPT=~/.hermes/skills/media/mediagen/scripts/mediagen.py
$PYTHON $SCRIPT --help
$PYTHON $SCRIPT --model gptimage2 --quality high --prompt "..."
$PYTHON $SCRIPT --model gptimage2 --quality high --inputs /path/a.png --prompt "..."
```

Omit dimensions on edit unless explicitly changing format. Use `--image-model gpt-image-2.5-sunburst|gpt-image-2.5-flare|gpt-image-2` for explicit selection, or `MEDIAGEN_GPT_IMAGE_MODEL` for the default. A successful live CLI test returned a valid PNG and correct requested-model log label; the server reported the host chat model but not a served image model. Do not claim independent confirmation of internal image routing or exact output dimensions from the requested size alone. Preserve existing filenames `*_gptimage2_<quality>[_edit].png`, but JSON/markdown endpoint labels and model metadata must identify the actual requested image model, not hardcode Image 2.

## Failures

- Missing auth: stop and explain how to authenticate.
- Unsupported model/tool/quality: report the actual error; offer a supported subscription alternative first.
- Quota exhausted: report quota and ask before additional billing.
- Timeout: request outcome may be uncertain, so do not repeatedly resubmit blindly.
- Wrong Python: use Hermes venv for auth helpers and httpx.

Never interpret missing legacy token helpers as proof the user is logged out. Native `image_generate` is independent of this direct mediagen route.
