"""Local-output generation executor; publication is owned by media_client only.

Callbacks receive persistent local inputs and return an ordered sequence of
LocalOutput. They must materialize provider URLs themselves (no URL/auth policy
is guessed here). Explicit run IDs resume publication, never provider requests.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal, Sequence, Any
import json
import shutil
import re
import os
import hashlib

import media_client

MediaKind = Literal['image', 'video']
InputRole = Literal['edit_source', 'upscale_source', 'start_frame', 'end_frame']


@dataclass(frozen=True)
class LocalInput:
    path: Path
    role: InputRole
    kind: MediaKind


@dataclass(frozen=True)
class LocalOutput:
    path: Path
    kind: MediaKind


@dataclass(frozen=True)
class GeneratedOutputs:
    """Optional callback envelope; request identity remains separate from results."""
    outputs: Sequence[LocalOutput]
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationSpec:
    run_id: str
    operation: str
    provider: str
    model: str
    endpoint: str
    prompt: str
    seed: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    inputs: tuple[LocalInput, ...] = ()


@dataclass(frozen=True)
class GenerationResult:
    outputs: tuple[Path, ...]
    log_path: Path
    receipt_path: Path | None
    publication: dict[str, Any]


class GenerationError(RuntimeError):
    """Callback/output failure or uncertain previous provider attempt. Never auto-retry."""


def persist_json(path: Path, payload: dict, *, token: str | None = None) -> None:
    """Atomically persist recursively sanitized metadata, never raw provider data."""
    if token is None:
        token = media_client.load_config().token
    media_client._atomic_write_json(path, media_client.sanitize_payload(payload, token=token))


def finalize_publication(*, workspace: Path, log_path: Path, assets: list[dict],
                         generation: dict, load_config=None, sync=None) -> tuple[dict, Path | None]:
    """One shared finalization boundary for custom adapters and built-in CLI."""
    cfg = None
    receipt_path = workspace / 'receipts' / media_client.receipt_filename(
        media_client.run_idempotency_key(log_path.relative_to(workspace).as_posix()))
    try:
        cfg = (load_config or media_client.load_config)()
        receipt = (sync or media_client.sync_if_enabled)(
            cfg, workspace=workspace, log_path=log_path.relative_to(workspace).as_posix(),
            assets=assets, generation=generation)
        publication = ({'status': 'disabled', 'last_error': None} if receipt is None else
                       {**receipt, 'status': receipt['status']})
    except media_client.ReceiptConflictError:
        publication = {'status': 'conflict', 'last_error': 'incompatible publication receipt; original preserved'}
    except Exception as exc:
        publication = {'status': 'pending', 'last_error':
                       'publication finalization failed; check receipt before retry: ' + str(exc)}
    publication = media_client.sanitize_payload(publication, token=getattr(cfg, 'token', None))
    return publication, receipt_path if receipt_path.is_file() else None


def _validate_spec(spec: GenerationSpec) -> None:
    if not isinstance(spec.run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', spec.run_id):
        raise ValueError('run_id must be a safe explicit identifier (1-96 characters)')
    if spec.seed is not None and type(spec.seed) is not int:
        raise ValueError('seed must be an integer or None')
    if any(not isinstance(value, str) or not value.strip()
           for value in (spec.operation, spec.provider, spec.model, spec.endpoint)):
        raise ValueError('operation, provider, model and endpoint must be explicit')
    if not isinstance(spec.prompt, str) or not isinstance(spec.params, dict):
        raise ValueError('prompt must be text and params must be a dictionary')
    roles = [item.role for item in spec.inputs]
    valid_roles = {
        'generate': not roles,
        'text-to-video': not roles,
        'edit': bool(roles) and all(role == 'edit_source' for role in roles),
        'upscale': roles == ['upscale_source'],
        'image-to-video': roles in (['start_frame'], ['start_frame', 'end_frame']),
    }
    if not valid_roles.get(spec.operation, False):
        raise ValueError('unsupported operation or incompatible input roles/order')
    if any(item.kind not in ('image', 'video') for item in spec.inputs):
        raise ValueError('input kind must be image or video')
    # Current roles represent image sources/frames only, not arbitrary video conditioning.
    if any(item.kind != 'image' for item in spec.inputs):
        raise ValueError('source/frame roles require image inputs')


def _validate_file(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_file() or path.stat().st_size == 0:
        raise ValueError('media must be a nonempty local regular file (Path)')


def _workspace_path(workspace: Path, path: Path, *, directory: bool = False) -> Path:
    """Check containment and existing topology; not an OS-level race sandbox."""
    try:
        path.resolve().relative_to(workspace)
    except ValueError:
        raise ValueError('persistence path must stay inside workspace') from None
    # Check ancestors first, including the workspace itself, so a regular file
    # cannot masquerade as an absent descendant. Internal symlinks keep the same
    # containment policy but must resolve to the expected filesystem type.
    for parent in reversed(path.parents):
        if parent.exists() or parent.is_symlink():
            if not parent.is_dir():
                raise ValueError('persistence ancestors must be directories')
    if path.exists() or path.is_symlink():
        if not (path.is_dir() if directory else path.is_file()):
            raise ValueError('persistence destination has incompatible file type')
    return path


def execute_generation(spec: GenerationSpec,
                       generate: Callable[[GenerationSpec], Sequence[LocalOutput] | GeneratedOutputs], *,
                       workspace: Path) -> GenerationResult:
    """Generate once, persist locally, and automatically attempt publication."""
    _validate_spec(spec)
    workspace = Path(workspace).resolve()
    log_path = workspace / 'logs' / f'{spec.run_id}.json'
    input_destinations = tuple(
        workspace / 'external' / spec.run_id / f'{position}-{Path(item.path).name}'
        for position, item in enumerate(spec.inputs))
    # Validate every deterministic input target before any writes or exclusive
    # claim: a bad later input must not leave a false uncertain provider attempt.
    for path in (log_path, log_path.with_suffix('.intent.json'), *input_destinations):
        _workspace_path(workspace, path)
    for path in (workspace / 'receipts', workspace / 'external' / spec.run_id,
                 workspace / 'images' / 'raw' / spec.run_id,
                 workspace / 'videos' / 'raw' / spec.run_id):
        _workspace_path(workspace, path, directory=True)
    token = media_client.load_config().token
    raw_identity = {
        'operation': spec.operation, 'provider': spec.provider, 'model': spec.model,
        'prompt': spec.prompt, 'seed': spec.seed,
        'params': {**spec.params, 'endpoint': spec.endpoint},
        # Request identity is lexical: originals (including symlinks) may be
        # removed after copying. Filesystem containment is resolved separately.
        'inputs': [{'path': str(Path(i.path).absolute()), 'role': i.role, 'kind': i.kind}
                   for i in spec.inputs]}
    # Compare the original request even if available redaction credentials change
    # between config_error and recovery. Raw metadata is never persisted.
    spec_digest = hashlib.sha256(json.dumps(raw_identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
    identity = media_client.sanitize_payload(raw_identity, token=token)
    intent_path = log_path.with_suffix('.intent.json')
    receipt_path = workspace / 'receipts' / media_client.receipt_filename(
        media_client.run_idempotency_key(log_path.relative_to(workspace).as_posix()))
    _workspace_path(workspace, receipt_path)
    if not log_path.exists() and receipt_path.exists():
        # Recover publication only, using the sealed Task2 payload and our
        # original intent identity. Never interpret an uncertain provider call
        # as authorization to generate a second time.
        if not intent_path.is_file():
            raise GenerationError('receipt has no executor identity; use publication-only recovery')
        intent = json.loads(intent_path.read_text())
        if intent.get('spec_digest') != spec_digest:
            raise media_client.ReceiptConflictError('incompatible generation spec for run_id')
        receipt = media_client.load_receipt(receipt_path)
        if not receipt.get('generation'):
            raise GenerationError('legacy receipt has no generation payload; use publication-only recovery')
        persist_json(log_path, {'identity': identity, 'spec_digest': spec_digest, 'assets': [
            {k: v for k, v in asset.items() if k in
             ('path', 'role', 'position', 'kind', 'origin', 'show_in_grid')}
            for asset in receipt['assets']], 'generation': receipt['generation']})
    if log_path.exists():
        log = json.loads(log_path.read_text())
        if log.get('spec_digest') != spec_digest:
            raise media_client.ReceiptConflictError('incompatible generation spec for run_id')
    else:
        intent_path = log_path.with_suffix('.intent.json')
        if intent_path.exists():
            raise GenerationError('previous provider attempt uncertain; reconcile manually, never auto-regenerate')
        for item in spec.inputs:
            _validate_file(item.path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive claim prevents concurrent callbacks for this run ID. A crash
        # at any point before the complete log remains uncertain by design.
        try:
            with intent_path.open('x', encoding='utf-8') as handle:
                json.dump({'identity': identity, 'spec_digest': spec_digest, 'status': 'provider_uncertain'}, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            raise GenerationError('provider attempt uncertain or already running') from None
        inputs = []
        refs = []
        assets = []
        for position, (item, dest) in enumerate(zip(spec.inputs, input_destinations)):
            _workspace_path(workspace, dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.path, dest)
            inputs.append(replace(item, path=dest))
            rel = dest.relative_to(workspace).as_posix()
            refs.append({'path': rel, 'role': item.role, 'position': position})
            assets.append({'path': rel, 'role': item.role, 'position': position, 'kind': item.kind,
                           'origin': 'external_import', 'show_in_grid': False})
        try:
            generated = generate(replace(spec, inputs=tuple(inputs)))
            returned = None
            if isinstance(generated, GeneratedOutputs):
                returned = generated
                if returned.seed is not None and type(returned.seed) is not int:
                    raise ValueError('returned seed must be an integer or None')
                if not isinstance(returned.metadata, dict):
                    raise ValueError('returned metadata must be a dictionary')
                outputs = tuple(returned.outputs)
            else:
                outputs = tuple(generated)
            if not outputs:
                raise ValueError('callback must return at least one LocalOutput')
            for output in outputs:
                if not isinstance(output, LocalOutput) or output.kind not in ('image', 'video'):
                    raise ValueError('callback must return LocalOutput with explicit image/video kind')
                _validate_file(output.path)
        except Exception as exc:
            error = media_client.sanitize_error_text(str(exc), token=token)
            persist_json(intent_path, {'identity': identity, 'spec_digest': spec_digest, 'status': 'provider_uncertain', 'last_error': error})
            raise GenerationError('generation callback/output failed; provider outcome uncertain: ' + error) from None
        out_refs = []
        for position, output in enumerate(outputs):
            folder = 'images' if output.kind == 'image' else 'videos'
            dest = workspace / folder / 'raw' / spec.run_id / f'{position}-{Path(output.path).name}'
            _workspace_path(workspace, dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output.path, dest)
            rel = dest.relative_to(workspace).as_posix()
            assets.append({'path': rel, 'position': position, 'kind': output.kind,
                           'origin': 'mediagen_generation', 'show_in_grid': True})
            out_refs.append({'path': rel, 'position': position})
        generation = {k: v for k, v in identity.items() if k != 'inputs'}
        if returned is not None:
            generation['params'] = {**generation['params'], 'provider_result':
                                    media_client.sanitize_payload(returned.metadata, token=token)}
            generation['seed'] = returned.seed
        generation.update(tool='mediagen', status='succeeded', inputs=refs, outputs=out_refs)
        log = {'identity': identity, 'spec_digest': spec_digest, 'assets': assets, 'generation': generation}
        persist_json(log_path, log)
    try:
        for asset in log['assets']:
            path = (workspace / asset['path']).resolve()
            path.relative_to(workspace)
            _validate_file(path)
    except (ValueError, OSError):
        raise GenerationError('persisted media missing, empty or outside workspace; restore files, never regenerate') from None
    publication, receipt_path = finalize_publication(
        workspace=workspace, log_path=log_path, assets=log['assets'], generation=log['generation'])
    return GenerationResult(tuple(workspace / ref['path'] for ref in log['generation']['outputs']),
                            log_path, receipt_path, publication)
