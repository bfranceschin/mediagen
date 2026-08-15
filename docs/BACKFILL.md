# Media backfill (G1)

Parse historical `logs/*.json` in a mediagen workspace and plan (or apply) Hostkit Media uploads.

## CLI

```bash
# Default is dry-run (no HTTP)
python scripts/media_backfill.py --workspace ~/.hermes/workspace/mediagen --dry-run --report /tmp/backfill-report.json

# Explicit apply (requires Media env; do not point at prod casually)
python scripts/media_backfill.py --workspace /path/to/workspace --apply --report /tmp/backfill-report.json
```

If both `--apply` and `--dry-run` are passed, dry-run wins.

## Environment (Hermes passthrough)

Same pattern as `FAL_KEY` / live mediagen sync:

| Variable | Purpose |
|----------|---------|
| `MEDIA_API_URL` | Base URL of Hostkit Media API (no trailing slash required) |
| `MEDIA_API_TOKEN_FILE` | Path to a file containing the bearer token (not the token itself) |
| `MEDIA_UPLOAD_TIMEOUT_SECONDS` | Optional upload timeout (default 180) |

Hermes skills/agents that invoke mediagen should pass through `MEDIA_API_URL` and `MEDIA_API_TOKEN_FILE` the same way they pass `FAL_KEY` — never embed the token in prompts, receipts, or reports.

## Behavior summary

- Outputs resolve to `images/raw/<filename>` or `videos/raw/<filename>` (video extensions: `.mp4`, `.webm`, `.mov`).
- Mode → operation: `generate` / `edit` / `image-to-video` / `text-to-video`.
- Provider: `openai-codex` if endpoint contains `openai-codex` or starts with `openai`, else `fal`.
- Model short key from endpoint (`flux2`, `nano2`, `gptimage2`, `seedance2`); original endpoint kept in `params.endpoint`.
- Edit inputs → `edit_source` by position; i2v first input → `start_frame` pos 0, `end_image` → `end_frame` pos 1.
- Assets use `ingested_via=backfill`. Generation outputs: `origin=mediagen_generation`, `show_in_grid=true`. Unique externals: `origin=external_import`, `show_in_grid=false`.
- External copy of an output is reconciled only when **basename + SHA-256** match that output (no global hash merge); referenced copies remap run inputs to the output path (`images/raw/...` / `videos/raw/...`).
- Distinct log paths with byte-identical files remain distinct assets/keys.
- Unreferenced external that is a byte-alias of a referenced input → report `orphan_aliases` only.
- Incomplete logs → report issues; no invented metadata.
- MIME/dimensions are server-owned; plan/upload metadata does not copy mime/width/height/duration from logs.
- Idempotency: `mediagen:asset:{rel}` and `mediagen:run:{log_path}`.

## Report safety

Reports include relative paths, abbreviated hashes, counts, and errors — never full prompts, bearer tokens, signed URLs, or absolute filesystem paths.
