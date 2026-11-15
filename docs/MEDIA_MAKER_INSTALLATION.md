# media-maker installation — reviewed generation/publication release

## Installed artifact

- Profile: `/home/bfranceschin/.hermes/profiles/media-maker`.
- Skill target: `skills/media/mediagen/` within that profile.
- Source commit: `82b82647706765b95d89a6699f8c9694294c9436`.
- Source branch: `feat/unified-generation-publication`.
- Backup/rollback manifest: `/home/bfranceschin/.hermes/profiles/media-maker/backups/mediagen-20261115T134831Z/manifest.json`.
- Installation used an explicit Git-tracked source/docs/tests allowlist, no deletion. Changed 24 files; read-back equality verified for all 40 selected files.
- No config, credential, workspace, cache or other-profile files copied/removed. No gateway restart performed; CLI scripts are read on invocation.

## Verification on the installed copy

- Full offline suite: **641 passed** with global socket/DNS guard, bytecode and pytest cache disabled; artifacts confined to coder scratch.
- Installed CLI help contains `wan26flash`, generic fal endpoint/input/output mappings and `--run-id`.
- Isolated auth-path tests under the offline guard: **9 passed; 1 live skipped**. These do not validate live credentials or entitlements.
- Loaded only the generating profile's `.env` in memory for configuration inspection: `FAL_KEY` present; `media_client.load_config` enabled publication locally. No secret values printed. `publication_status=pending` is the initial configured state, not evidence of an upload or a queued existing item.
- No provider/platform request, generation, publication, receipt replay or worker activation in this installation/verification step.

## Remaining gates and limits

- Real provider generation/publication is not verified and requires separate authorization, including paid usage.
- Push/merge not performed as part of this offline installation.
- Automatic worker/backoff and uncertain provider-request recovery remain out of scope.
- Earlier implementation-test HTTP incident remains remotely unverified; this installation does not establish its remote outcome.
- Existing in-flight chats may have loaded old skill text. Use a fresh media-maker conversation or explicitly reload the skill before relying on new instructions.

## Rollback scope

The backup manifest lists each changed path, whether it existed, and old/new SHA-256. A scoped rollback restores only entries with `existed=true` from `backup/files/<path>` and removes only newly installed entries after checking their current hashes match the installed release. Do not restore an entire profile or overwrite config/credentials. Rollback has not been executed.
