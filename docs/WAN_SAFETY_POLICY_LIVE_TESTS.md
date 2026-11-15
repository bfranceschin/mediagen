# Configurable safety policy and two authorized Wan live tests

## User-authorized change

Source policy release: `86b9303` on `feat/unified-generation-publication`.

Wan now hardcodes `enable_safety_checker=false`. Existing FLUX/Seedance false settings and Nano tolerance 6 remain unchanged. Generic fal normalizes an explicitly supplied top-level enable_safety_checker to false before identity/persistence/submission; absent or nested schema fields are not invented/rewritten. README/SKILL record the preference without promising mandatory server moderation or account restrictions can be disabled. Both independent SPEC and quality/security reviews passed; controller and installed-profile suites each passed **645 offline tests**.

Five changed source/docs/test files installed and read-back verified in media-maker only. Backup manifest:
`/home/bfranceschin/.hermes/profiles/media-maker/backups/mediagen-safety-20261115T141636Z/manifest.json`.

## Live test bounds

Exactly two new user-authorized provider generations were submitted, one per input. Both used Wan 2.6 Flash i2v, duration 5, requested 720p, seed 363872830, audio disabled, prompt expansion disabled, and enable_safety_checker=false (confirmed from both persisted request identities). No automatic provider retry, fallback or further generation followed. Actual billing was not retrieved.

### Neutral input: successful generation and automatic publication

- Run ID: `live-wan-neutral-20261115T141636Z`.
- Input: locally drawn geometric landscape, 768x512, no image provider called.
- CLI exit 0; stderr PUBLICATION=completed.
- Receipt completed on attempt 1.
- Generation run returned by platform: `run_FUNB9Sq3xtDHX0VJofUDi` (receipt evidence; no run-by-ID read route used).
- Persisted input item: `med_KTW6U2elsyCNSz14dEgGH`; private, hidden from grid, external_import.
- Video item: `med_E14YwbtRVka6RiD3sCPJm`; private, show_in_grid=true, mediagen_generation.
- Direct authenticated GET of both exact item IDs: HTTP 200; ingest_status=ready and derivative_status=ready. Local original-byte SHA-256 equals remote content_hash for each asset.
- Remote/local probe: 1176x784, 5000 ms, no audio streams. This is the actual provider output geometry for the requested 720p tier, not a claim of exact 1280x720.
- Video: `/home/bfranceschin/.hermes/workspace/mediagen/videos/raw/live-wan-neutral-20261115T141636Z/0-output-0.mp4`.
- Detail URL: https://media.bfranceschin.dev/admin/media/med_E14YwbtRVka6RiD3sCPJm
- A first verification request using the default urllib user agent returned 403; a subsequent request with the client's explicit hermes-mediagen/1.0 user agent returned 200. No credentials or permissions changed; the exact upstream cause of the initial 403 was not determined.

### Previous image: still rejected by the provider

- Run ID: `live-wan-original-20261115T141636Z`.
- Input: original handoff image `media-maker/images/upload_tmtheoz_.jpg`.
- Same waving-toy prompt as the earlier smoke test, no audio.
- CLI exit 2; provider content_policy_violation / model_moderated despite requested enable_safety_checker=false.
- No output video/completed generation log/publication receipt for this run. No media upload was reached.
- An exclusive intent records the failed/uncertain provider attempt and blocks resubmission.
- The result does not identify which content triggered moderation and does not establish whether this rejected attempt was billed.

## Replay checks without any external operation

Installed CLI repeated with the same inputs/prompts/run IDs and active profile config, under socket/DNS guard plus explicit forbidden fal upload/subscribe and media HTTP mocks:

- Neutral: exit 0, PUBLICATION=completed, zero provider/platform calls; receipt bytes unchanged and attempts still 1.
- Original: exit 2, previous provider attempt uncertain, zero provider/platform calls.

These checks did not submit another paid request. No original inputs/intents were deleted or altered to force replay.

## Remaining limitations

Mandatory server moderation may still reject content when a configurable checker is disabled. Do not claim that the setting guarantees acceptance. No worker activated, no push/merge performed. The earlier unintended implementation-test HTTP incident remains a separate remotely unverified event.
