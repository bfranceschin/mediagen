"""Offline executor contracts: real filesystem, fake generation/HTTP boundaries."""
import json
from pathlib import Path

import pytest
import media_client


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv('MEDIA_API_URL', raising=False)
    monkeypatch.delenv('MEDIA_API_TOKEN_FILE', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('unexpected real HTTP')
    monkeypatch.setattr(media_client.urllib.request, 'urlopen', forbidden)


def test_custom_persists_and_finalizes_once(tmp_path, monkeypatch):
    import generation_executor as executor
    monkeypatch.delenv('MEDIA_API_URL', raising=False)
    monkeypatch.delenv('MEDIA_API_TOKEN_FILE', raising=False)
    source = tmp_path / 'source.png'
    source.write_bytes(b'input')
    output = tmp_path / 'generated.png'
    output.write_bytes(b'output')
    spec = executor.GenerationSpec(run_id='custom-1', operation='edit', provider='local-test',
        model='actual-model', endpoint='actual-endpoint', prompt='test', seed=0,
        params={'api_key': 'SECRET', 'nested': {'steps': 4}},
        inputs=(executor.LocalInput(source, 'edit_source', 'image'),))
    calls = []
    def generate(request):
        calls.append(request)
        assert request.inputs[0].path != source
        assert request.inputs[0].path.read_bytes() == b'input'
        return (executor.LocalOutput(output, 'image'),)
    result = executor.execute_generation(spec, generate, workspace=tmp_path / 'workspace')
    assert len(calls) == 1
    assert result.outputs[0].read_bytes() == b'output'
    assert result.publication['status'] == 'disabled'
    log = json.loads(result.log_path.read_text())
    assert log['generation']['seed'] == 0
    assert log['generation']['provider'] == 'local-test'
    assert log['generation']['params']['endpoint'] == 'actual-endpoint'
    assert 'SECRET' not in result.log_path.read_text()
    again = executor.execute_generation(spec, generate, workspace=tmp_path / 'workspace')
    assert len(calls) == 1
    assert again.outputs == result.outputs


@pytest.mark.parametrize('change', ['run_id', 'seed', 'role', 'kind', 'path', 'operation'])
def test_invalid_spec_has_no_side_effects(tmp_path, change):
    import generation_executor as executor
    from dataclasses import replace
    source = tmp_path / 'input.png'
    source.write_bytes(b'input')
    spec = executor.GenerationSpec('valid', 'edit', 'test', 'model', 'endpoint', 'prompt',
        inputs=(executor.LocalInput(source, 'edit_source', 'image'),))
    if change == 'run_id':
        spec = replace(spec, run_id='../escape')
    elif change == 'seed':
        spec = replace(spec, seed=True)
    elif change == 'operation':
        spec = replace(spec, operation='generate')
    else:
        item = spec.inputs[0]
        item = replace(item, **{change: {'role': 'invented', 'kind': 'audio', 'path': tmp_path}[change]})
        spec = replace(spec, inputs=(item,))
    calls = []
    with pytest.raises(ValueError):
        executor.execute_generation(spec, lambda _: calls.append(1), workspace=tmp_path / 'workspace')
    assert calls == []
    assert not (tmp_path / 'workspace').exists()


@pytest.mark.parametrize('bad', ['empty', 'kind', 'missing', 'directory', 'url', 'dict'])
def test_malformed_output_never_publishes_or_regenerates(tmp_path, monkeypatch, bad):
    import generation_executor as executor
    source = tmp_path / 'out.png'
    source.write_bytes(b'output')
    output = {
        'empty': (), 'kind': (executor.LocalOutput(source, 'audio'),),
        'missing': (executor.LocalOutput(tmp_path / 'missing', 'image'),),
        'directory': (executor.LocalOutput(tmp_path, 'image'),),
        'url': (executor.LocalOutput('https://example.test/signed?token=SECRET', 'image'),),
        'dict': ({'path': source, 'kind': 'image'},),
    }[bad]
    calls, publications = [], []
    monkeypatch.setattr(executor, 'finalize_publication', lambda **kw: publications.append(kw))
    spec = executor.GenerationSpec('bad-output', 'generate', 'test', 'model', 'endpoint', 'p')
    def generate(_):
        calls.append(1)
        return output
    with pytest.raises(executor.GenerationError):
        executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    with pytest.raises(executor.GenerationError, match='uncertain'):
        executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    assert calls == [1]
    assert publications == []
    assert not (tmp_path / 'ws' / 'images').exists()


def test_provider_failure_is_durable_uncertain_and_sanitized(tmp_path, monkeypatch):
    import generation_executor as executor
    calls, publications = [], []
    monkeypatch.setattr(executor, 'finalize_publication', lambda **kw: publications.append(kw))
    spec = executor.GenerationSpec('provider-error', 'generate', 'test', 'model', 'endpoint', 'p')
    def generate(_):
        calls.append(1)
        raise TimeoutError('Authorization: Bearer PROVIDER_SECRET')
    for _ in range(2):
        with pytest.raises(executor.GenerationError):
            executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    assert calls == [1]
    assert publications == []
    persisted = ''.join(p.read_text() for p in (tmp_path / 'ws' / 'logs').glob('*.json'))
    assert 'PROVIDER_SECRET' not in persisted
    assert 'provider_uncertain' in persisted


@pytest.mark.parametrize('recover_from_receipt', [False, True])
def test_outage_resume_with_removed_source_symlink(tmp_path, monkeypatch, recover_from_receipt):
    import generation_executor as executor
    import io
    import urllib.error
    from dataclasses import replace
    token = tmp_path / 'token'
    token.write_text('SYNTHETIC_TOKEN')
    monkeypatch.setenv('MEDIA_API_URL', 'https://media.test')
    monkeypatch.setenv('MEDIA_API_TOKEN_FILE', str(token))
    first = tmp_path / 'a' / 'same.png'
    second = tmp_path / 'b' / 'same.png'
    first.parent.mkdir(); second.parent.mkdir()
    source_target = tmp_path / 'original.png'
    source_target.write_bytes(b'first')
    first.symlink_to(source_target)
    second.write_bytes(b'second')
    video = tmp_path / 'clip.mp4'; video.write_bytes(b'video')
    spec = executor.GenerationSpec('resume', 'edit', 'custom', 'real-model', 'real-endpoint', 'preserved',
        seed=0, params={'steps': 12, 'nested': {'authorization': 'SECRET',
        'url': 'https://cdn.test/file?X-Amz-Signature=SIGNED_SECRET'}},
        inputs=(executor.LocalInput(first, 'edit_source', 'image'), executor.LocalInput(second, 'edit_source', 'image')))
    calls, requests = [], []
    down = [True]
    class Response(io.BytesIO):
        status = 201
    def http(req, timeout=None):
        requests.append(req)
        if down[0] and len(requests) == 2:
            raise urllib.error.URLError('offline SYNTHETIC_TOKEN')
        if req.full_url.endswith('/api/media'):
            return Response(json.dumps({'id': 'asset-' + str(len(requests))}).encode())
        return Response(b'{"id": "run-id"}')
    monkeypatch.setattr(media_client.urllib.request, 'urlopen', http)
    def generate(_):
        calls.append(1)
        return (executor.LocalOutput(first, 'image'), executor.LocalOutput(video, 'video'))
    workspace = tmp_path / 'ws'
    pending = executor.execute_generation(spec, generate, workspace=workspace)
    assert pending.publication['status'] == 'pending'
    receipt = json.loads(pending.receipt_path.read_text())
    assert receipt['assets'][0]['media_item_id'] == 'asset-1'
    assert receipt['generation']['seed'] == 0
    assert receipt['generation']['params']['steps'] == 12
    assert [a['kind'] for a in receipt['assets']] == ['image', 'image', 'image', 'video']
    assert receipt['assets'][0]['path'] != receipt['assets'][1]['path']
    for secret in ('SIGNED_SECRET', 'SYNTHETIC_TOKEN', '"SECRET"'):
        assert secret not in pending.receipt_path.read_text()
        assert secret not in pending.log_path.read_text()
    first.unlink(); source_target.unlink(); second.unlink(); video.unlink()
    if recover_from_receipt:
        pending.log_path.unlink()  # receipt + durable intent remain authoritative recovery evidence
    down[0] = False
    completed = executor.execute_generation(spec, generate, workspace=workspace)
    assert calls == [1]
    assert completed.outputs[0].read_bytes() == b'first'
    assert completed.outputs[1].read_bytes() == b'video'
    assert completed.publication['status'] == 'completed'
    assert completed.publication['generation_run_id'] == 'run-id'
    assert completed.publication['attempts'] == 2
    assert completed.publication['assets'][0]['media_item_id'] == 'asset-1'
    assert (workspace / completed.publication['assets'][0]['path']).read_bytes() == b'first'
    # failed upload keeps its key; successful input is not uploaded again
    assert requests[1].get_header('Idempotency-key') == requests[2].get_header('Idempotency-key')
    before = len(requests)
    executor.execute_generation(spec, generate, workspace=workspace)
    assert len(requests) == before
    original = completed.receipt_path.read_text()
    with pytest.raises(media_client.ReceiptConflictError):
        executor.execute_generation(replace(spec, prompt='different'), generate, workspace=workspace)
    with pytest.raises(media_client.ReceiptConflictError):
        executor.execute_generation(replace(spec, inputs=(
            replace(spec.inputs[0], path=source_target), spec.inputs[1])), generate, workspace=workspace)
    assert completed.receipt_path.read_text() == original
    assert calls == [1]


def test_config_error_is_recoverable_and_token_is_removed_before_disk(tmp_path, monkeypatch):
    import generation_executor as executor
    token = tmp_path / 'token'; token.write_text('CONFIG_SECRET')
    monkeypatch.setenv('MEDIA_API_TOKEN_FILE', str(token))  # missing URL is configuration error
    output = tmp_path / 'out.png'; output.write_bytes(b'output')
    spec = executor.GenerationSpec('config', 'generate', 'local', 'model', 'endpoint',
        'ordinary prompt Authorization: Bearer CONFIG_SECRET', params={'steps': 2})
    calls = []
    def generate(_):
        calls.append(1)
        return (executor.LocalOutput(output, 'image'),)
    result = executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    assert result.publication['status'] == 'config_error'
    assert result.receipt_path.is_file()
    for path in (tmp_path / 'ws' / 'logs').glob('*.json'):
        assert 'CONFIG_SECRET' not in path.read_text()
    assert 'CONFIG_SECRET' not in result.receipt_path.read_text()
    import io
    class Response(io.BytesIO):
        status = 201
    monkeypatch.setenv('MEDIA_API_URL', 'https://media.test')
    monkeypatch.setattr(media_client.urllib.request, 'urlopen',
                        lambda *a, **k: Response(b'{"id": "recovered"}'))
    recovered = executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    assert recovered.publication['status'] == 'completed'
    assert calls == [1]


def test_configured_token_is_removed_from_executor_log_before_http(tmp_path, monkeypatch):
    import generation_executor as executor
    import urllib.error
    token = tmp_path / 'token'; token.write_text('CONFIGURED_TOKEN')
    monkeypatch.setenv('MEDIA_API_TOKEN_FILE', str(token))
    monkeypatch.setenv('MEDIA_API_URL', 'https://media.test')
    output = tmp_path / 'out.png'; output.write_bytes(b'output')
    spec = executor.GenerationSpec('sanitize', 'generate', 'local', 'model', 'endpoint',
        'ordinary CONFIGURED_TOKEN prompt')
    def http(*args, **kwargs):
        for path in (tmp_path / 'ws').rglob('*.json'):
            assert 'CONFIGURED_TOKEN' not in path.read_text()
        raise urllib.error.URLError('offline')
    monkeypatch.setattr(media_client.urllib.request, 'urlopen', http)
    result = executor.execute_generation(spec, lambda _: (executor.LocalOutput(output, 'image'),), workspace=tmp_path / 'ws')
    assert 'CONFIGURED_TOKEN' not in result.log_path.read_text()
    assert 'AssertionError' not in str(result.publication)


def test_missing_persisted_output_does_not_claim_success_or_regenerate(tmp_path):
    import generation_executor as executor
    output = tmp_path / 'out.png'; output.write_bytes(b'output')
    spec = executor.GenerationSpec('missing', 'generate', 'local', 'model', 'endpoint', 'p')
    calls = []
    def generate(_):
        calls.append(1)
        return (executor.LocalOutput(output, 'image'),)
    result = executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    result.outputs[0].unlink()
    with pytest.raises(executor.GenerationError, match='persisted'):
        executor.execute_generation(spec, generate, workspace=tmp_path / 'ws')
    assert calls == [1]


@pytest.mark.parametrize('folder', ['logs', 'external', 'images'])
def test_workspace_symlink_cannot_redirect_persistence(tmp_path, folder):
    import generation_executor as executor
    outside = tmp_path / 'outside'; outside.mkdir()
    workspace = tmp_path / 'ws'; workspace.mkdir()
    (workspace / folder).symlink_to(outside, target_is_directory=True)
    source = tmp_path / 'source.png'; source.write_bytes(b'source')
    spec = executor.GenerationSpec('symlink', 'edit', 'local', 'model', 'endpoint', 'p',
        inputs=(executor.LocalInput(source, 'edit_source', 'image'),))
    with pytest.raises(ValueError, match='workspace'):
        executor.execute_generation(spec, lambda _: (executor.LocalOutput(source, 'image'),), workspace=workspace)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('position', [0, 1])
def test_input_destination_escape_is_rejected_before_claim_and_can_retry(tmp_path, position):
    import generation_executor as executor
    source = tmp_path / 'source.png'
    source.write_bytes(b'source')
    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'untouched')
    workspace = tmp_path / 'ws'
    run_id = 'input-link'
    input_dir = workspace / 'external' / run_id
    input_dir.mkdir(parents=True)
    destination = input_dir / f'{position}-source.png'
    destination.symlink_to(outside)
    spec = executor.GenerationSpec(run_id, 'edit', 'local', 'model', 'endpoint', 'p',
        inputs=(executor.LocalInput(source, 'edit_source', 'image'),) * 2)
    calls = []
    def generate(request):
        calls.append(request)
        assert all(item.path.read_bytes() == b'source' for item in request.inputs)
        return (executor.LocalOutput(source, 'image'),)

    with pytest.raises(ValueError, match='workspace'):
        executor.execute_generation(spec, generate, workspace=workspace)
    assert calls == []
    assert not (workspace / 'logs' / f'{run_id}.intent.json').exists()
    assert not (workspace / 'logs').exists()
    assert list(input_dir.iterdir()) == [destination]
    assert outside.read_bytes() == b'untouched'

    destination.unlink()
    result = executor.execute_generation(spec, generate, workspace=workspace)
    assert len(calls) == 1
    assert result.outputs[0].read_bytes() == b'source'
    assert result.publication['status'] == 'disabled'
    again = executor.execute_generation(spec, generate, workspace=workspace)
    assert again.outputs == result.outputs
    assert len(calls) == 1


@pytest.mark.parametrize('relative,is_directory', [
    ('external', False),
    ('external/topology', False),
    ('external/topology/0-source.png', True),
    ('external/topology/1-source.png', True),
    ('logs', False),
    ('logs/topology.json', True),
    ('logs/topology.intent.json', True),
    ('receipts', False),
    ('receipt-file', True),
    ('images', False),
    ('images/raw', False),
    ('images/raw/topology', False),
    ('videos/raw/topology', False),
])
def test_invalid_destination_topology_precedes_claim_and_allows_retry(tmp_path, relative, is_directory):
    import generation_executor as executor
    workspace = tmp_path / 'ws'
    if relative == 'receipt-file':
        relative = 'receipts/' + media_client.receipt_filename(
            media_client.run_idempotency_key('logs/topology.json'))
    blocker = workspace / relative
    blocker.parent.mkdir(parents=True)
    if is_directory:
        blocker.mkdir()
    else:
        blocker.write_bytes(b'blocker')
    source = tmp_path / 'source.png'
    source.write_bytes(b'source')
    spec = executor.GenerationSpec('topology', 'edit', 'local', 'model', 'endpoint', 'p',
        inputs=(executor.LocalInput(source, 'edit_source', 'image'),) * 2)
    calls = []
    def generate(request):
        calls.append(request)
        assert all(item.path.is_file() for item in request.inputs)
        assert all(item.path.read_bytes() == b'source' for item in request.inputs)
        return (executor.LocalOutput(source, 'image'),)

    with pytest.raises(ValueError, match='persistence'):
        executor.execute_generation(spec, generate, workspace=workspace)
    assert calls == []
    intent = workspace / 'logs' / 'topology.intent.json'
    assert not intent.is_file()
    assert not (workspace / 'logs' / 'topology.json').is_file()
    if is_directory:
        assert list(blocker.iterdir()) == []
        blocker.rmdir()
    else:
        assert blocker.read_bytes() == b'blocker'
        blocker.unlink()

    result = executor.execute_generation(spec, generate, workspace=workspace)
    source.unlink()  # Resume uses persisted media, not the original input.
    again = executor.execute_generation(spec, generate, workspace=workspace)
    assert len(calls) == 1
    assert again.outputs == result.outputs
    assert again.outputs[0].read_bytes() == b'source'
    assert again.publication['status'] == 'disabled'


@pytest.mark.parametrize('kind', ['image', 'video'])
def test_callback_created_output_directory_is_not_copied_into_or_retried(tmp_path, kind):
    import generation_executor as executor
    workspace = tmp_path / 'ws'
    source = tmp_path / 'output.bin'
    source.write_bytes(b'output')
    spec = executor.GenerationSpec('output-type', 'generate', 'local', 'model', 'endpoint', 'p')
    destination = workspace / ('images' if kind == 'image' else 'videos') / 'raw' / spec.run_id / '0-output.bin'
    calls = []
    def generate(_):
        calls.append(1)
        destination.mkdir(parents=True)
        return (executor.LocalOutput(source, kind),)

    with pytest.raises(ValueError, match='persistence'):
        executor.execute_generation(spec, generate, workspace=workspace)
    assert list(destination.iterdir()) == []
    intent = workspace / 'logs' / 'output-type.intent.json'
    original_intent = intent.read_bytes()
    destination.rmdir()
    with pytest.raises(executor.GenerationError, match='uncertain'):
        executor.execute_generation(spec, generate, workspace=workspace)
    assert calls == [1]
    assert intent.read_bytes() == original_intent


def test_existing_regular_input_destination_is_replaced_before_callback(tmp_path):
    import generation_executor as executor
    workspace = tmp_path / 'ws'
    source = tmp_path / 'source.png'
    source.write_bytes(b'new input')
    destination = workspace / 'external' / 'regular' / '0-source.png'
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b'old input')
    spec = executor.GenerationSpec('regular', 'edit', 'local', 'model', 'endpoint', 'p',
        inputs=(executor.LocalInput(source, 'edit_source', 'image'),))
    def generate(request):
        assert request.inputs[0].path == destination
        assert destination.read_bytes() == b'new input'
        return (executor.LocalOutput(source, 'image'),)
    result = executor.execute_generation(spec, generate, workspace=workspace)
    assert result.outputs[0].read_bytes() == b'new input'


def test_import_safe_subprocess_inherits_profile_and_resumes(tmp_path):
    import os
    import subprocess
    import sys
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    environment = dict(os.environ)
    environment['HERMES_HOME'] = str(tmp_path / 'active-profile')
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    code = """
import os, sys, socket
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).parent / 'tests'))
import pytest
from offline_guard import install
child_guard = pytest.MonkeyPatch()
install(child_guard)  # Python children do not inherit parent monkeypatches.
# Invalid port makes the missing-guard RED safe without contacting any server.
try:
    with socket.socket() as client:
        client.connect(('127.0.0.1', -1))
except RuntimeError as exc:
    assert 'offline suite' in str(exc)
else:
    raise AssertionError('child network guard missing')
sys.path.insert(0, sys.argv[1])
from generation_executor import GenerationSpec, LocalOutput, execute_generation
assert os.environ['HERMES_HOME'] == sys.argv[3]
root = Path(sys.argv[2])
source = root / 'generated.png'
source.write_bytes(b'local renderer output')
calls = []
def generate(request):
    calls.append(1)
    return (LocalOutput(source, 'image'),)
spec = GenerationSpec('subprocess', 'generate', 'local', 'renderer', 'local:renderer', 'p', seed=0)
a = execute_generation(spec, generate, workspace=root / 'ws')
b = execute_generation(spec, generate, workspace=root / 'ws')
assert calls == [1] and a.outputs == b.outputs
assert a.publication['status'] == 'disabled'
print('profile-preserved; callback=1; publication=disabled')
"""
    result = subprocess.run([sys.executable, '-c', code, str(scripts), str(tmp_path), environment['HERMES_HOME']],
        cwd=tmp_path, env=environment, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'profile-preserved; callback=1; publication=disabled'
    assert not (tmp_path / 'active-profile').exists()
