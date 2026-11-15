# Common generation executor (Python API)

Custom adapters call `execute_generation`, not an uploader. Built-in CLI routes
retain their provider/auth handling and sidecars, but use the same
`persist_json` and `finalize_publication` boundary. Only `media_client` uploads.
This module is a local-output Python API, not a provider adapter. The separate CLI/fal adapter adds Wan and generic fal routes on top of it; see the [README](../README.md).

## Contract

- `GenerationSpec`: explicit `run_id`, operation, real provider/model/endpoint,
  prompt, integer-or-null seed and JSON params. No provider inference. A seed of
  zero is retained; adapters must not imply an unsupported seed was honored.
- `LocalInput(Path, role, kind)`: ordered local files. Supported operations are
  `generate`, `edit`, `upscale`, `text-to-video`, `image-to-video`. Roles are
  `edit_source`, `upscale_source`, `start_frame`, `end_frame`; current source/frame
  roles require images. Start precedes optional end. Positions follow tuple order.
- The callback receives a spec whose inputs are persistent copies, and returns
  a nonempty ordered sequence of `LocalOutput(Path, kind)` (`image` or `video`).
  Multiple image/video outputs are supported. Kinds are declarations, not byte
  sniffing or schema inference. File paths must be nonempty local regular files.
- **Local outputs only.** No arbitrary URL download, credential forwarding or
  automatic provider retry. A provider adapter must materialize its output with
  its own validated download policy before returning. A future remote-output
  contract needs explicit HTTPS/redirect/origin/size limits, not `urlretrieve`.
- Results contain persistent output paths, log path, optional receipt path and
  publication state. `publication` includes receipt asset IDs, generation run ID,
  attempts and idempotency keys when available. Only `status == 'completed'`
  means publication completed. Disabled/config-error/pending/failed/conflict are
  not publication success; local output remains usable.

Inputs/outputs use per-run, position-prefixed names, so equal source basenames
cannot overwrite each other. Metadata is recursively sanitized before disk and
before publication. Params include the explicit endpoint. Callback exceptions
are sanitized and raised as `GenerationError`; publication is never attempted.
An exclusive, fsynced intent is created before the callback. An uncertain attempt
(including callback timeout, malformed output or a crash before the complete
log) cannot be retried by reentering this run ID. Reconcile manually; do not
choose a new ID just to evade uncertainty.

Reenter the same workspace/run ID/spec to resume publication **without calling
back again**. Recovery uses saved files and the Task2 receipt payload, preserving
uploaded IDs/attempts/keys. Original temporary inputs/outputs can be gone. If the
complete log is lost, the receipt plus original executor intent can reconstruct
it. Missing persistent media, missing recovery evidence, or changed metadata
fail closed; they never trigger generation. Publication retries are sequential;
this API is not a worker or distributed job scheduler.

## Import-safe example

The launcher must pass its **active profile environment** unchanged (including
`HERMES_HOME`, provider credentials and optional `MEDIA_API_*`). This module does
not discover/read another profile or load a default profile `.env`.

```python
import os
import sys
from pathlib import Path

repo = Path('/home/bfranceschin/projects/mediagen')
sys.path.insert(0, str(repo / 'scripts'))  # also required for runpy launchers
from generation_executor import GenerationSpec, LocalInput, LocalOutput, execute_generation

# Implement this adapter using an authorized local/provider renderer. It must
# return an existing local file and must not publish or retry uncertain requests.
def generate(request):
    from my_authorized_adapter import render
    path = render(prompt=request.prompt, source=request.inputs[0].path,
                  seed=request.seed, params=request.params)
    return (LocalOutput(Path(path), 'image'),)

result = execute_generation(
    GenerationSpec(
        run_id='my-edit-001', operation='edit', provider='my-real-provider',
        model='my-real-model', endpoint='my-real-endpoint', prompt='Make the sky blue',
        seed=0, params={'steps': 20},
        inputs=(LocalInput(Path('/absolute/source.png'), 'edit_source', 'image'),),
    ),
    generate,
    workspace=Path(os.environ['MEDIAGEN_WORKSPACE']),
)
print(result.outputs, result.publication['status'], result.receipt_path)
```

No `publish()` call is left to remember. The existing CLI still ends stdout with
`FILENAME=... PROMPT=... SEED=...` and reports publication separately on stderr.

## Offline validation and isolation boundary

`tests/conftest.py` installs the shared `tests/offline_guard.py` **before test
collection**, then its autouse fixture clears inherited live/publication settings
before every test. This also removes provider API keys and GPT host/image-model
and workspace overrides so defaults do not depend on the invoking shell. Tests
may explicitly set synthetic configuration with `monkeypatch.setenv` after this
cleanup; mocked HTTP publication/recovery tests remain enabled. Paid integration
tests remain unconditionally skipped.

The guard rejects Python DNS resolution, socket connect/connect_ex and datagram
send paths before network I/O, including loopback by default. HTTP mocks and
in-memory fixtures are unaffected. No existing offline test requires a real
loopback server; any future local-server test needs a narrowly scoped, explicit
loopback allowance rather than disabling the suite guard globally.

This is a Python test guard, **not an OS/network sandbox**. A new interpreter
does not inherit monkeypatches. The executor subprocess probe explicitly installs
the same harness before importing application code; nested pytest probes load
this conftest. Any new subprocess must do likewise (or use equivalent explicit
isolation). Native clients/external commands and deliberately bypassing Python
socket wrappers are not contained by this harness and must not be used for
network access in offline tests. Existing paid-generation subprocess tests are
disabled, not authorized by the harness.

Regression tests use only synthetic URLs, tokens and local token files. Their
RED socket probe uses an invalid port, so even a missing guard cannot contact a
server. A separate test module launches pytest with synthetic inherited Media
settings, verifies configuration cleanup, and exercises the real local executor
with publication disabled and zero HTTP calls.

Incident scope: an earlier built-in boundary test inherited Media publication
configuration and attempted real HTTP. An `unsupported_media_type` response was
reported without an asset ID. **Remote state is unverified**: neither the response
nor the absence of an ID proves that no remote side effect occurred. No remote
audit, authentication check, upload or paid generation was performed as part of
this isolation correction. Offline passing tests do not resolve that uncertainty.

Run only the offline suite, with scratch outside the checkout:

```bash
env -u MEDIA_API_URL -u MEDIA_API_TOKEN_FILE -u MEDIAGEN_TEST_LIVE \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  TMPDIR=/home/bfranceschin/.hermes/profiles/coder/cache/scratch \
  /home/bfranceschin/.hermes/hermes-agent/venv/bin/python -m pytest -q \
  -p no:cacheprovider -m 'not integration' --ignore=tests/test_integration.py \
  --basetemp=/home/bfranceschin/.hermes/profiles/coder/cache/scratch/mediagen-global-offline tests/
```

The launcher cleanup is defense in depth, not the isolation mechanism.
