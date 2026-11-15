# Controlled Wan live smoke test

## Scope

User authorized one paid test after media-maker installation. One installed CLI invocation used Wan 2.6 Flash image-to-video, 5 seconds, 720p, native audio disabled, prompt expansion disabled, safety checker enabled, seed 363872830. No fallback or second generation was submitted.

- Run ID: `live-wan-smoke-20261115T140211Z`.
- Installed source release: `82b82647706765b95d89a6699f8c9694294c9436`.
- Profile: `media-maker`.
- Input: existing handoff image `images/upload_tmtheoz_.jpg` in that profile.
- Prompt: `The Iron Man toy gently raises one hand and waves once. Keep the same toy, background and framing. Static camera. No text.`
- Endpoint: `wan/v2.6/image-to-video/flash`.

## Actual result

CLI exited **2**. The provider returned `content_policy_violation` with category `model_moderated`: the content could not be processed by its content checker. No video was returned. This does not establish which input aspect triggered moderation, nor whether the provider charged for the rejected attempt. No actual-cost claim is made.

Local read-back found only:

`/home/bfranceschin/.hermes/workspace/mediagen/logs/live-wan-smoke-20261115T140211Z.intent.json`

No completed generation log or publication receipt for this run existed. The generation did not reach the common publication finalizer; no platform upload was attempted by this test. There is no video or media detail URL to deliver.

## Same-run recovery safety verification

Repeated the same command through the installed CLI with global offline socket/DNS guard and explicit forbidden mocks on fal upload/subscribe. Expected exit **2**, diagnostic `previous provider attempt uncertain`, **zero provider calls**. The existing intent prevented automatic resubmission. No network request occurred during this reentry verification.

This proves fail-closed replay protection for this actual failed run, not successful publication recovery. The existing implementation conservatively labels callback/provider errors uncertain; distinguishing definitive moderation failure is not changed in this smoke test.

## Acceptance status

- Installed CLI reaches real fal provider: verified.
- No automatic duplicate generation after failure: verified offline against actual intent.
- Successful media generation, automatic platform publication and completed-run recovery: **not verified live**, blocked by moderation.
- Another paid generation requires a new user-approved run; do not delete/reuse this intent to force regeneration. Do not disable or bypass safety checks.
- The earlier unintended implementation-test HTTP incident remains a separate event with remote state unverified.
