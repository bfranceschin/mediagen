"""Wan CLI contract using a synthetic local image and fake fal/HTTP only."""
import json
from pathlib import Path

import pytest
from PIL import Image
from test_generic_fal import fake_fal, cli


def wan_args(source, model='wan26flash'):
    return ['--model', model, '--run-id', 'wan-1', '--inputs', str(source), '--prompt', 'synthetic motion']


@pytest.mark.parametrize('model', ['wan26flash', 'wan2.6flash', 'wan'])
def test_wan_cli_exact_flash_schema_and_resume(fake_fal, tmp_path, monkeypatch, capsys, model):
    ws, calls = fake_fal
    source = tmp_path / 'frame.png'
    Image.new('RGB', (320, 240)).save(source)
    argv = wan_args(source, model)
    cli(monkeypatch, argv)
    source.unlink()
    cli(monkeypatch, argv)
    submits = [c for c in calls if c[0] == 'subscribe']
    assert len(submits) == 1
    assert submits[0][1] == 'wan/v2.6/image-to-video/flash'
    assert submits[0][2] == {'prompt':'synthetic motion', 'image_url':'https://fal.media/files/input.png',
        'duration':'5', 'resolution':'720p', 'negative_prompt':'', 'enable_prompt_expansion':True,
        'multi_shots':False, 'enable_safety_checker':False, 'generate_audio':True}
    log = json.loads((ws / 'logs/wan-1.json').read_text())
    assert log['generation']['model'] == 'wan26flash'
    assert log['generation']['seed'] == 0
    assert log['generation']['operation'] == 'image-to-video'
    assert log['generation']['params']['arguments']['enable_safety_checker'] is False
    assert len(list((ws / 'videos/raw').rglob('*.mp4'))) == 1
    assert capsys.readouterr().out.splitlines()[-1].endswith('SEED=0')


@pytest.mark.parametrize('extra', [
    ['--duration','4'], ['--duration','6'], ['--resolution','480p'],
    ['--prompt','x' * 1501], ['--negative-prompt','x' * 501],
    ['--multi-shots','--no-prompt-expansion'],
    ['--end-image','unused.png'], ['--camera-fixed'], ['--aspect-ratio','16:9'],
    ['--fal-args','{}'], ['--inputs'], ['--prompt',''],
])
def test_wan_rejects_invalid_controls_before_upload(fake_fal, tmp_path, monkeypatch, extra):
    ws, calls = fake_fal
    source = tmp_path / 'frame.png'
    Image.new('RGB', (320, 240)).save(source)
    with pytest.raises(SystemExit):
        cli(monkeypatch, wan_args(source) + extra)
    assert calls == []
    assert not list(ws.rglob('*.intent.json'))


@pytest.mark.parametrize('size', [(239,240), (240,239), (7681,240), (240,7681)])
def test_wan_validates_start_frame_dimensions_before_upload(fake_fal, tmp_path, monkeypatch, size):
    ws, calls = fake_fal
    source = tmp_path / 'frame.png'
    Image.new('RGB', size).save(source)
    with pytest.raises(SystemExit):
        cli(monkeypatch, wan_args(source))
    assert calls == []
    assert not list((ws / 'videos').rglob('*.mp4'))


@pytest.mark.parametrize('duration', ['5','10','15'])
def test_wan_explicit_schema_controls(fake_fal, tmp_path, monkeypatch, duration):
    ws, calls = fake_fal
    source = tmp_path / 'frame.png'
    Image.new('RGB', (240,240)).save(source)
    cli(monkeypatch, wan_args(source) + ['--duration',duration, '--resolution','1080p',
        '--negative-prompt','avoid flicker', '--no-prompt-expansion', '--no-audio', '--seed','0'])
    payload = [c[2] for c in calls if c[0] == 'subscribe'][0]
    assert payload['duration'] == duration
    assert payload['resolution'] == '1080p'
    assert payload['negative_prompt'] == 'avoid flicker'
    assert payload['enable_prompt_expansion'] is False
    assert payload['multi_shots'] is False
    assert payload['generate_audio'] is False
    assert payload['enable_safety_checker'] is False
    assert payload['seed'] == 0


def test_wan_pending_recovery_ignores_replaced_original(fake_fal, tmp_path, monkeypatch):
    import io
    import urllib.request
    import urllib.error
    ws, calls = fake_fal
    token = tmp_path / 'token'
    token.write_text('SYNTHETIC_MEDIA_TOKEN')
    monkeypatch.setenv('MEDIA_API_URL', 'https://media.test')
    monkeypatch.setenv('MEDIA_API_TOKEN_FILE', str(token))
    requests = []
    class Response(io.BytesIO):
        status = 201
    def http(req, timeout):
        requests.append(req)
        if len(requests) == 2:
            raise urllib.error.URLError('synthetic outage')
        return Response(json.dumps({'id': 'synthetic-' + str(len(requests))}).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', http)
    source = tmp_path / 'frame.png'
    Image.new('RGB', (320, 240)).save(source)
    original = source.read_bytes()
    argv = wan_args(source)
    first = cli(monkeypatch, argv)
    assert first.publication['status'] == 'pending'
    receipt = json.loads(first.receipt_path.read_text())
    assert receipt['attempts'] == 1
    assert receipt['assets'][0]['media_item_id'] == 'synthetic-1'
    log = first.log_path.read_bytes()
    persisted = ws / json.loads(log)['generation']['inputs'][0]['path']
    assert persisted.read_bytes() == original
    source.write_bytes(b'INVALID REPLACEMENT')
    second = cli(monkeypatch, argv)
    assert second.publication['status'] == 'completed'
    final = json.loads(second.receipt_path.read_text())
    assert final['attempts'] == 2
    assert final['assets'][0]['media_item_id'] == 'synthetic-1'
    assert requests[1].get_header('Idempotency-key') == requests[2].get_header('Idempotency-key')
    assert second.log_path.read_bytes() == log
    assert persisted.read_bytes() == original
    assert len([c for c in calls if c[0] == 'subscribe']) == 1
    assert len([c for c in calls if c[0] == 'upload']) == 1


def test_wan_multishots_with_expansion(fake_fal, tmp_path, monkeypatch):
    _, calls = fake_fal
    source = tmp_path / 'frame.png'
    Image.new('RGB', (240,240)).save(source)
    cli(monkeypatch, wan_args(source) + ['--multi-shots'])
    payload = [c[2] for c in calls if c[0] == 'subscribe'][0]
    assert payload['multi_shots'] is True
    assert payload['enable_prompt_expansion'] is True
