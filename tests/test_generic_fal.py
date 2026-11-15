"""Synthetic local provider and byte fixtures; never genuine provider output."""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.response import addinfourl

import pytest
import mediagen
import generation_executor as executor
import fal_adapter


def cli(monkeypatch, argv):
    monkeypatch.setattr(sys, 'argv', ['mediagen.py', *argv])
    return mediagen.main()


@pytest.fixture
def fake_fal(tmp_path, monkeypatch):
    calls = []
    workspace = tmp_path / 'workspace'
    monkeypatch.setattr(mediagen, 'WORKSPACE', workspace)
    def upload(path):
        path = Path(path)
        assert path.is_relative_to(workspace / 'external')
        assert path.is_file()
        calls.append(('upload', path))
        return 'https://fal.media/files/input.png'
    def subscribe(endpoint, *, arguments):
        calls.append(('subscribe', endpoint, arguments))
        return {'images': [{'url': 'https://fal.media/files/a.png'},
                           {'url': 'https://v3.fal.media/files/b.png'}],
                'video': {'url': 'https://fal.media/files/video.mp4'}, 'seed': 0}
    monkeypatch.setitem(sys.modules, 'fal_client', SimpleNamespace(upload_file=upload, subscribe=subscribe))
    monkeypatch.setenv('FAL_KEY', 'SYNTHETIC_FAL_KEY')
    import urllib.request
    class Response(io.BytesIO):
        headers = {}
        status = 200
    def open_url(self, request, timeout):
        assert timeout > 0
        assert not request.has_header('Authorization')
        calls.append(('download', request.full_url))
        return Response(b'SYNTHETIC OUTPUT NOT REAL MEDIA')
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', open_url)
    return workspace, calls


def generic_args(source):
    return ['--model', 'fal', '--run-id', 'generic-1', '--fal-endpoint', 'example/model/edit',
            '--operation', 'edit', '--fal-kind', 'image', '--inputs', str(source),
            '--fal-args', json.dumps({'prompt': 'synthetic', 'seed': 0, 'images': [None],
                                     'custom_strength': 0.42, 'api_key': 'SYNTHETIC_SECRET'}),
            '--fal-input-map', '[{"input":0,"path":"images.0","role":"edit_source","kind":"image"}]',
            '--fal-output-map', '[{"path":"images.0.url","kind":"image"},{"path":"images.1.url","kind":"image"}]']


def test_generic_cli_one_generation_persists_inputs_outputs_and_resumes_publication(fake_fal, tmp_path, monkeypatch, capsys):
    workspace, calls = fake_fal
    source = tmp_path / 'input.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    publications = []
    def publish(**kw):
        publications.append(kw)
        assert all((workspace / item['path']).is_file() for item in kw['assets'])
        return ({'status': 'pending' if len(publications) == 1 else 'completed'}, None)
    monkeypatch.setattr(executor, 'finalize_publication', publish)
    argv = generic_args(source)
    cli(monkeypatch, argv)
    source.unlink()
    cli(monkeypatch, argv)
    assert len([c for c in calls if c[0] == 'subscribe']) == 1
    assert len(publications) == 2
    assert len(list((workspace / 'images' / 'raw').rglob('*.png'))) == 2
    log = (workspace / 'logs' / 'generic-1.json').read_text()
    assert 'SYNTHETIC_SECRET' not in log
    generation = json.loads(log)['generation']
    assert generation['seed'] == 0
    assert generation['params']['arguments']['custom_strength'] == 0.42
    assert generation['params']['endpoint'] == 'example/model/edit'
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1].startswith('FILENAME=')
    assert 'PUBLICATION=completed' in captured.err


def replace_flag(argv, flag, value):
    result = argv.copy()
    result[result.index(flag) + 1] = value
    return result


@pytest.mark.parametrize('requested', [True, False])
def test_generic_explicit_safety_checker_is_disabled_before_persistence_and_submit(fake_fal, tmp_path, monkeypatch, requested):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    arguments = {'images': [None], 'enable_safety_checker': requested}
    argv = replace_flag(generic_args(source), '--fal-args', json.dumps(arguments))
    original = sys.modules['fal_client'].subscribe
    def subscribe(endpoint, *, arguments):
        intent = json.loads((ws / 'logs/generic-1.intent.json').read_text())
        assert intent['identity']['params']['arguments']['enable_safety_checker'] is False
        assert arguments['enable_safety_checker'] is False
        return original(endpoint, arguments=arguments)
    monkeypatch.setattr(sys.modules['fal_client'], 'subscribe', subscribe)
    result = cli(monkeypatch, argv)
    log = json.loads(result.log_path.read_text())
    assert log['generation']['params']['arguments']['enable_safety_checker'] is False
    source.unlink()
    arguments['enable_safety_checker'] = False
    cli(monkeypatch, replace_flag(argv, '--fal-args', json.dumps(arguments)))
    assert len([c for c in calls if c[0] == 'subscribe']) == 1


def test_generic_does_not_inject_or_guess_nested_safety_controls(fake_fal, tmp_path, monkeypatch):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    arguments = {'images': [None], 'custom': {'enable_safety_checker': True},
                 'safety_tolerance': 'custom-value'}
    cli(monkeypatch, replace_flag(generic_args(source), '--fal-args', json.dumps(arguments)))
    payload = next(c[2] for c in calls if c[0] == 'subscribe')
    assert 'enable_safety_checker' not in payload
    assert payload['custom'] == arguments['custom']
    assert payload['safety_tolerance'] == 'custom-value'
    logged = json.loads((ws / 'logs/generic-1.json').read_text())['generation']['params']['arguments']
    assert 'enable_safety_checker' not in logged
    assert logged == arguments


def test_generic_rejects_input_binding_that_would_overwrite_safety_control(fake_fal, tmp_path, monkeypatch):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    argv = replace_flag(generic_args(source), '--fal-args', '{"enable_safety_checker":true}')
    argv = replace_flag(argv, '--fal-input-map', json.dumps([
        {'input': 0, 'path': 'enable_safety_checker', 'role': 'edit_source', 'kind': 'image'}]))
    with pytest.raises(SystemExit):
        cli(monkeypatch, argv)
    assert calls == []
    assert not list(ws.rglob('*.intent.json'))


def test_generic_preserves_complete_long_prompt(fake_fal, tmp_path, monkeypatch):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    prompt = 'ordinary text ' * 200
    argv = replace_flag(generic_args(source), '--fal-args', json.dumps({'images':[None], 'prompt':prompt}))
    cli(monkeypatch, argv)
    log = json.loads((ws / 'logs/generic-1.json').read_text())
    assert log['generation']['prompt'] == prompt
    assert calls[1][2]['prompt'] == prompt


@pytest.mark.parametrize('flag,value', [
    ('--fal-input-map','[{"input":0,"path":"images.0","role":"start_frame","kind":"image"}]'),
    ('--fal-input-map','[{"input":0,"path":"images.9","role":"edit_source","kind":"image"}]'),
    ('--fal-output-map','[{"path":"images[0].url","kind":"image"}]'),
    ('--fal-output-map','[{"path":"images.0.url","kind":"video"}]'),
    ('--fal-endpoint','https://example.invalid/model'),
    ('--fal-args','{"images":[null],"seed":false}'),
    ('--fal-args','{"images":[null],"x":NaN}'),
    ('--fal-args','{"images":[null],"x":1,"x":2}'),
    ('--run-id','../escape'),
])
def test_invalid_config_precedes_any_upload(fake_fal, tmp_path, monkeypatch, flag, value):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    with pytest.raises(SystemExit):
        cli(monkeypatch, replace_flag(generic_args(source), flag, value))
    assert calls == []
    assert not list(ws.rglob('*.intent.json'))


@pytest.mark.parametrize('extra', [['--duration','5'], ['--end-image','anything'], ['--no-audio']])
def test_generic_rejects_ignored_builtin_controls(fake_fal, tmp_path, monkeypatch, extra):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    with pytest.raises(SystemExit):
        cli(monkeypatch, generic_args(source) + extra)
    assert calls == []


def test_provider_seed_and_sanitized_result_reach_shared_publication(fake_fal, tmp_path, monkeypatch, capsys):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'
    source.write_bytes(b'SYNTHETIC INPUT')
    def subscribe(endpoint, *, arguments):
        calls.append(('subscribe', endpoint, arguments))
        return {'images':[{'url':'https://fal.media/files/a.png?token=SYNTHETIC_SIGNED_SECRET'}],
                'seed': 0, 'actual_prompt':'expanded synthetic', 'api_key':'SYNTHETIC_RESULT_SECRET'}
    monkeypatch.setattr(sys.modules['fal_client'], 'subscribe', subscribe)
    argv = replace_flag(generic_args(source), '--fal-output-map', '[{"path":"images.0.url","kind":"image"}]')
    argv = replace_flag(argv, '--fal-args', '{"images":[null],"prompt":"synthetic","seed":42}')
    published = []
    def publish(**kw):
        published.append(kw['generation'])
        return {'status':'completed'}, None
    monkeypatch.setattr(executor, 'finalize_publication', publish)
    cli(monkeypatch, argv)
    assert published[0]['seed'] == 0
    assert published[0]['params']['arguments']['seed'] == 42
    assert published[0]['params']['provider_result']['actual_prompt'] == 'expanded synthetic'
    text = (ws / 'logs/generic-1.json').read_text()
    assert 'SYNTHETIC_SIGNED_SECRET' not in text
    assert 'SYNTHETIC_RESULT_SECRET' not in text
    source.unlink()
    cli(monkeypatch, argv)
    assert len([c for c in calls if c[0] == 'subscribe']) == 1
    assert published[1]['seed'] == 0
    assert capsys.readouterr().out.splitlines()[-1].endswith('SEED=0')


@pytest.mark.parametrize('url', [
    'http://fal.media/out.png', 'https://evilfal.media/out.png',
    'https://fal.media.evil.invalid/out.png', 'https://127.0.0.1/out.png',
    'https://fal.media:444/out.png', 'https://user:secret@fal.media/out.png',
    'file:///etc/passwd', 'https://fal.media/out.png#fragment',
    'https://fal.media/line\nbreak', 'https://fal.media/a b',
    'https://.fal.media/out', 'https://bad_label.fal.media/out',
])
def test_downloader_rejects_unsafe_origins_before_http(tmp_path, monkeypatch, url):
    import urllib.request
    def forbidden(*a, **k):
        pytest.fail('unsafe URL reached HTTP')
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', forbidden)
    with pytest.raises(ValueError, match='HTTPS'):
        fal_adapter.download_output(url, tmp_path / 'out')


@pytest.mark.parametrize('data,limit,error', [(b'',5,'empty'), (b'123456',5,'byte limit')])
def test_downloader_enforces_size_without_auth(tmp_path, monkeypatch, data, limit, error):
    import urllib.request
    def http(self, req, timeout):
        assert set(dict(req.header_items())) == {'Accept'}
        assert timeout == 120
        return io.BytesIO(data)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', http)
    with pytest.raises(ValueError, match=error):
        fal_adapter.download_output('https://v3.fal.media/out', tmp_path / 'out', max_bytes=limit)


def test_downloader_redirect_is_not_followed(tmp_path, monkeypatch):
    import urllib.request
    import email.message
    calls = []
    def https_open(self, req):
        calls.append(req.full_url)
        headers = email.message.Message()
        headers['Location'] = 'https://127.0.0.1/never'
        response = addinfourl(io.BytesIO(b''), headers, req.full_url, 302)
        response.msg = 'Found'
        return response
    monkeypatch.setattr(urllib.request.HTTPSHandler, 'https_open', https_open)
    with pytest.raises(ValueError, match='redirects'):
        fal_adapter.download_output('https://fal.media/out', tmp_path / 'out')
    assert calls == ['https://fal.media/out']


def test_nonstandard_root_list_video_mapping(fake_fal, monkeypatch):
    ws, calls = fake_fal
    def subscribe(endpoint, *, arguments):
        calls.append(('subscribe', endpoint, arguments))
        return [{'clip': {'link':'https://fal.media/clip.mp4'}}]
    monkeypatch.setattr(sys.modules['fal_client'], 'subscribe', subscribe)
    cli(monkeypatch, ['--model','fal','--run-id','list-1','--operation','text-to-video',
        '--fal-kind','video','--fal-endpoint','example/video','--fal-args','{"prompt":"synthetic"}',
        '--fal-output-map','[{"path":"0.clip.link","kind":"video"}]'])
    assert len(list((ws / 'videos/raw').rglob('*.mp4'))) == 1


def test_overlapping_input_mappings_fail_before_upload(fake_fal, tmp_path, monkeypatch):
    ws, calls = fake_fal
    a = tmp_path / 'a.png'; a.write_bytes(b'SYNTHETIC')
    b = tmp_path / 'b.png'; b.write_bytes(b'SYNTHETIC')
    argv = generic_args(a) + ['--inputs',str(a),str(b)]
    argv = replace_flag(argv, '--fal-input-map', json.dumps([
        {'input':0,'path':'images','role':'edit_source','kind':'image'},
        {'input':1,'path':'images.0','role':'edit_source','kind':'image'}]))
    with pytest.raises(SystemExit):
        cli(monkeypatch, argv)
    assert calls == []
    assert not list(ws.rglob('*.intent.json'))


def test_real_shared_receipt_is_sealed_before_http_and_resumes(fake_fal, tmp_path, monkeypatch, capsys):
    import urllib.request
    import urllib.error
    ws, calls = fake_fal
    token = tmp_path / 'token'; token.write_text('SYNTHETIC_MEDIA_TOKEN')
    monkeypatch.setenv('MEDIA_API_URL','https://media.test')
    monkeypatch.setenv('MEDIA_API_TOKEN_FILE',str(token))
    requests = []
    class Response(io.BytesIO):
        status = 201
    def http(req, timeout):
        receipt = json.loads(next((ws / 'receipts').glob('*.json')).read_text())
        assert receipt['generation']['params']['endpoint'] == 'example/model/edit'
        assert all((ws / a['path']).is_file() for a in receipt['assets'])
        assert 'SYNTHETIC_SECRET' not in json.dumps(receipt)
        requests.append(req)
        if len(requests) == 2:
            raise urllib.error.URLError('synthetic outage')
        return Response(json.dumps({'id':'synthetic-' + str(len(requests))}).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', http)
    source = tmp_path / 'in.png'; source.write_bytes(b'SYNTHETIC INPUT')
    argv = generic_args(source)
    first = cli(monkeypatch, argv)
    assert first.publication['status'] == 'pending'
    receipt = json.loads(first.receipt_path.read_text())
    assert receipt['assets'][0]['media_item_id'] == 'synthetic-1'
    source.unlink()
    second = cli(monkeypatch, argv)
    assert second.publication['status'] == 'completed'
    assert len([c for c in calls if c[0] == 'subscribe']) == 1
    assert requests[1].get_header('Idempotency-key') == requests[2].get_header('Idempotency-key')
    assert json.loads(second.receipt_path.read_text())['attempts'] == 2
    assert capsys.readouterr().out.splitlines()[-1].startswith('FILENAME=')


@pytest.mark.parametrize('remove_intent', [False, True])
def test_pending_publication_retry_is_nonzero_without_regeneration(fake_fal, tmp_path, monkeypatch, capsys, remove_intent):
    ws, calls = fake_fal
    source = tmp_path / 'in.png'; source.write_bytes(b'SYNTHETIC INPUT')
    monkeypatch.setattr(executor, 'finalize_publication', lambda **kw: ({'status':'pending'}, None))
    argv = generic_args(source)
    cli(monkeypatch, argv)  # new generation remains locally successful
    if remove_intent:
        (ws / 'logs/generic-1.intent.json').unlink()
    with pytest.raises(SystemExit) as error:
        cli(monkeypatch, argv)
    assert error.value.code == 1
    assert len([c for c in calls if c[0] == 'subscribe']) == 1
    assert capsys.readouterr().out.splitlines()[-1].startswith('FILENAME=')


@pytest.mark.parametrize('result', [
    {'images':[]}, {'images':[{'url':'https://evil.invalid/secret?token=SYNTHETIC_URL_SECRET'}]},
    {'images':[{'url':'https://fal.media/a'},{'url':'http://fal.media/b'}]},
])
def test_invalid_output_is_uncertain_never_resubmitted(fake_fal, tmp_path, monkeypatch, result):
    ws, calls = fake_fal
    def subscribe(endpoint, *, arguments):
        calls.append(('subscribe', endpoint, arguments))
        return result
    monkeypatch.setattr(sys.modules['fal_client'], 'subscribe', subscribe)
    source = tmp_path / 'in.png'; source.write_bytes(b'SYNTHETIC INPUT')
    for _ in range(2):
        with pytest.raises(SystemExit):
            cli(monkeypatch, generic_args(source))
    assert len([c for c in calls if c[0] == 'subscribe']) == 1
    assert not [c for c in calls if c[0] == 'download']
    text = next((ws / 'logs').glob('*.intent.json')).read_text()
    assert 'SYNTHETIC_URL_SECRET' not in text


def test_builtin_rejects_adapter_recovery_flags_before_generation(monkeypatch):
    monkeypatch.setattr(mediagen, 'run_image', lambda args: pytest.fail('must not generate'))
    with pytest.raises(SystemExit):
        cli(monkeypatch, ['--model','gptimage2','--prompt','synthetic','--run-id','not-resumable'])


def test_explicit_null_provider_seed_does_not_claim_requested_seed(fake_fal, tmp_path, monkeypatch):
    ws, _ = fake_fal
    monkeypatch.setattr(sys.modules['fal_client'], 'subscribe', lambda *a, **k:
        {'images':[{'url':'https://fal.media/a'}, {'url':'https://fal.media/b'}], 'seed':None})
    source = tmp_path / 'in.png'; source.write_bytes(b'SYNTHETIC')
    cli(monkeypatch, generic_args(source))
    generation = json.loads((ws / 'logs/generic-1.json').read_text())['generation']
    assert generation['seed'] is None
    assert generation['params']['arguments']['seed'] == 0


def test_download_deadline_is_bounded_even_at_eof(tmp_path, monkeypatch):
    import urllib.request
    now = [0]
    monkeypatch.setattr(fal_adapter.time, 'monotonic', lambda: now[0])
    class Response(io.BytesIO):
        def read(self, size: int | None = -1):
            chunk = super().read(size)
            if not chunk:
                now[0] = 121
            return chunk
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', lambda *a, **k: Response(b'123'))
    with pytest.raises(TimeoutError, match='timed out'):
        fal_adapter.download_output('https://fal.media/file', tmp_path / 'out')


@pytest.mark.parametrize('phase', ['open', 'read'])
def test_download_deadline_interrupts_blocking_io(tmp_path, monkeypatch, phase):
    import signal
    import time
    import urllib.request
    completed = []
    class Response(io.BytesIO):
        def read(self, size: int | None = -1):
            time.sleep(0.15)
            completed.append('read')
            return super().read(size)
    def http(*a, **k):
        if phase == 'open':
            time.sleep(0.15)
            completed.append('open')
        return Response(b'123')
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', http)
    previous = signal.getsignal(signal.SIGALRM)
    with pytest.raises(TimeoutError, match='timed out'):
        fal_adapter.download_output('https://fal.media/file', tmp_path / 'out', timeout=0.03)
    assert completed == []
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)


@pytest.mark.parametrize('outcome', ['success', 'error', 'timeout'])
def test_download_preserves_outer_300_budget_across_outputs(tmp_path, monkeypatch, outcome):
    import signal
    import urllib.request
    now = [0.0]
    timer = [300.0, 0.0]
    armed = []
    def outer(*_):
        raise TimeoutError('outer callback expired')
    handler = [outer]
    monkeypatch.setattr(fal_adapter.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(signal, 'getsignal', lambda _: handler[0])
    def set_handler(_, value):
        old = handler[0]
        handler[0] = value
        return old
    monkeypatch.setattr(signal, 'signal', set_handler)
    monkeypatch.setattr(signal, 'getitimer', lambda _: (max(0, timer[0] - now[0]), timer[1]))
    def set_timer(_, seconds, interval=0):
        timer[:] = [now[0] + seconds if seconds else 0, interval]
        if seconds:
            armed.append(seconds)
    monkeypatch.setattr(signal, 'setitimer', set_timer)
    class Response(io.BytesIO):
        def read(self, size: int | None = -1):
            now[0] += 5
            return super().read(size)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', lambda *a, **k: Response(b'123'))
    for index in range(2):
        fal_adapter.download_output('https://fal.media/file', tmp_path / str(index))
        assert handler[0] is outer
        assert timer == [300, 0]
    assert now[0] == 20
    if outcome != 'success':
        class Failure(io.BytesIO):
            def read(self, size: int | None = -1):
                now[0] += 121 if outcome == 'timeout' else 7
                if outcome == 'error':
                    raise OSError('synthetic read failure')
                return b''
        monkeypatch.setattr(urllib.request.OpenerDirector, 'open', lambda *a, **k: Failure())
        with pytest.raises(TimeoutError if outcome == 'timeout' else OSError):
            fal_adapter.download_output('https://fal.media/file', tmp_path / 'failure')
        assert handler[0] is outer
        assert timer == [300, 0]
    assert armed[:4] == [120, 290, 120, 280]


def test_download_obeys_shorter_outer_deadline(tmp_path, monkeypatch):
    import signal
    import time
    import urllib.request
    fired = []
    completed = []
    def outer(*_):
        fired.append(True)
        raise TimeoutError('outer callback expired')
    class Response(io.BytesIO):
        def read(self, size: int | None = -1):
            time.sleep(0.15)
            completed.append(True)
            return b''
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', lambda *a, **k: Response())
    previous = signal.signal(signal.SIGALRM, outer)
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.03)
        with pytest.raises(TimeoutError, match='outer callback expired'):
            fal_adapter.download_output('https://fal.media/file', tmp_path / 'out')
        assert fired == [True]
        assert completed == []
        assert signal.getsignal(signal.SIGALRM) is outer
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_callback_scratch_is_removed_after_persistence(fake_fal, tmp_path, monkeypatch):
    original = fal_adapter.download_output
    downloads = []
    def download(url, path):
        downloads.append(path)
        return original(url, path)
    monkeypatch.setattr(fal_adapter, 'download_output', download)
    source = tmp_path / 'in.png'; source.write_bytes(b'SYNTHETIC')
    result = cli(monkeypatch, generic_args(source))
    assert downloads and all(not p.exists() for p in downloads)
    assert all(p.is_file() for p in result.outputs)
