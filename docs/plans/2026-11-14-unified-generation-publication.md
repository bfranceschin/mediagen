# Unified generation and publication Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make built-in, generic fal and custom generators persist and publish via one common path, without requiring a separate agent upload step.

**Architecture:** Reuse media_client and durable receipts. Extract a common executor/finalizer, persist sanitized complete publication metadata and resume existing receipts. Add an explicit Wan adapter and a generic fal adapter with explicit input/output mapping. Preserve local generation success separately from publication status.

**Tech Stack:** Python, argparse, fal_client, stdlib HTTP, pytest.

## Scope and operational gates

User authorized controlled implementation. No paid generations, live uploads, replay of existing receipts, credential changes, scheduled worker, deployment or writes to other profiles. Work only in repository; named profiles are read-only reference. Installation requires a separate explicit gate. No arbitrary cross-provider fallback. Second delivery (worker and durable provider request recovery) is deferred.

Each behavior change uses vertical RED/GREEN cycles. Controller runs verification independently. Each slice requires independent spec review, then independent quality/security review; blocking findings must be fixed and re-reviewed before next slice. Commit only after gates. Never add profile data, secrets, logs, receipts or generated media.

## Task 1: Reconcile versioned baseline

Files: README.md, SKILL.md, references/gptimage2-codex.md, references/grok-imagine-xai.md, scripts/mediagen.py, scripts/test_mediagen_auth_paths.py, tests/conftest.py, tests/test_unit.py, tests/test_model_upgrade.py.

1. Run explicit offline baseline in checkout and installed reference; disable bytecode/cache/live tests and use coder scratch temporary paths.
2. Bring installed source/tests/docs through an explicit file allowlist, preserving existing versioned plans. This is preservation of existing behavior, not new provider features.
3. Merge SKILL.md semantically: preserve coder recovery diagnostics and media-maker active-profile environment guidance. Never copy profile secrets.
4. Validate paid integration remains disabled in offline runs.
5. Run offline suite plus isolated auth-path tests (without MEDIAGEN_TEST_LIVE).
6. Independent spec review, quality/security review, controller verification and reconciliation commit.

## Task 2: Durable and observable publication contract

Files: scripts/media_client.py, scripts/media_sync.py, scripts/mediagen.py, tests/test_media_client.py, tests/test_media_sync.py, tests/test_mediagen_media_sync.py.

For each item: write failing behavioral test, run RED, minimal implementation, run GREEN and regression tests.
- Persist sanitized complete generation payload in receipts; old receipts remain recoverable through existing reconstruction.
- Re-enter same publication by loading existing receipt and retaining completed/progress state and stable idempotency keys.
- Explicitly distinguish intentionally disabled publication, completed publication, pending/failed/conflict and configuration/import problems; retain final FILENAME stdout contract and generation success on upload failure. Diagnostics must not leak secrets.
- Define expected publication intent separately from usable credentials; avoid silent loss of recoverable publication when configured integration is broken.
- Do not expand into automatic worker or provider recovery.
- Two reviews, controller verification, commit.

## Task 3: Common generation executor

Files: create scripts/generation_executor.py and tests/test_generation_executor.py; modify scripts/mediagen.py and tests/test_mediagen_media_sync.py as needed.

Define narrow typed/dataclass contracts for operation/provider/model/prompt/seed/params, explicit local inputs/roles, and outputs. Callback-based custom generation runs through executor; persist binaries and metadata, then durable publication automatically. Support image/video and multiple outputs without assuming Seedance args. Reuse existing client; do not create a second upload implementation. Preserve current provider auth and CLI behavior. Test via local fake adapters and mocked boundary HTTP only, including publication outage, malformed output and retry without regeneration. Add public API example and import-path-safe usage. RED/GREEN per behavior, spec then quality/security review, controller verification, commit.

## Task 4: Wan and generic fal entry

Files: scripts/mediagen.py, scripts/generation_executor.py or a narrow fal adapter module if needed; tests/test_unit.py, tests/test_generic_fal.py, tests/test_wan.py; README.md and SKILL.md.

First retrieve current official Wan endpoint schema using public read-only documentation, never generation calls. Implement explicit Wan option with validated endpoint-specific parameters; never assume Seedance schema. Implement generic fal entry with endpoint, JSON arguments, declared operation, explicit local input binding/roles and explicit output mapping for nonstandard results. Validate before provider submission, preserve actual provider endpoint and sanitized parameters. No eval/exec, arbitrary URL credential forwarding or silent paid fallback. Both use the common executor so one invocation generates, persists and attempts publication. Exercise real CLI parsing and local adapter/HTTP simulations; clearly label simulations, no fabricated provider evidence. RED/GREEN per behavior, spec then quality/security review, controller verification, commit.

## Task 5: Documentation and final verification

Update README.md, SKILL.md and this plan status: supported Wan scope, generic invocation, minimal custom adapter example, publication states, configuration semantics, receipts retry limitations and deferred worker/provider-recovery scope. Run full offline suite with integration excluded, isolated auth tests and CLI help smoke tests; independent final integration/security review. Commit all approved changes. Report tested facts separately from untested live provider/platform behavior. Do not install to media-maker or activate automation without explicit authorization at the installation gate.

## Safe verification commands

Use /home/bfranceschin/.hermes/hermes-agent/venv/bin/python. Set PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, unset MEDIAGEN_TEST_LIVE. pytest -p no:cacheprovider -m 'not integration' --ignore=tests/test_integration.py --basetemp=/home/bfranceschin/.hermes/profiles/coder/cache/scratch/mediagen-<slice> tests/. Run auth paths with python -I -B scripts/test_mediagen_auth_paths.py and live flag absent. Never run retry against the real workspace during development.

## Status

- Discovery complete: installed coder/media-maker scripts identical; checkout behind installed behavior. media_client/media_sync identical in all copies. Existing publication tests: 53 passed offline on installed reference.
- Reconciliation: complete. Controller verified 329 offline tests; independent SPEC and quality/security re-review PASS after narrow xAI download-credential and helper fallback fixes. Isolated auth paths: 9 passed, 1 live skipped; reviewer also passed 8 additional offline redirect probes. No installation or live provider calls.
- Executor/receipts: Task2 complete; controller verified 523 offline tests, independent SPEC and quality/security re-reviews PASS after sanitizer/config/retry fixes. Payload persistence, recovery, progress and stdout contracts verified with local HTTP simulations. Common executor not started; no installation/live uploads.
- Wan/generic: pending.
- Final verification: pending.
