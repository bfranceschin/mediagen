"""Regressions for suite-wide isolation; all credentials here are synthetic."""
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest


def test_inherited_publication_is_disabled(tmp_path, monkeypatch):
    import media_client
    from generation_executor import GenerationSpec, LocalOutput, execute_generation

    isolated = ('MEDIA_API_URL', 'MEDIA_API_TOKEN_FILE', 'MEDIA_API_TOKEN',
                'MEDIAGEN_TEST_LIVE', 'FAL_KEY', 'XAI_API_KEY', 'OPENAI_API_KEY',
                'MEDIAGEN_GPT_IMAGE_MODEL', 'MEDIAGEN_CODEX_CHAT_MODEL')
    leaked_names = [name for name in isolated if name in os.environ]
    assert leaked_names == []  # Never include environment values in failure output.
    requests = []
    def forbidden_http(*args, **kwargs):
        requests.append(1)
        raise AssertionError('unexpected publication HTTP')
    monkeypatch.setattr(media_client.urllib.request, 'urlopen', forbidden_http)
    source = tmp_path / 'output.png'
    source.write_bytes(b'local output')
    result = execute_generation(
        GenerationSpec('offline-probe', 'generate', 'local', 'model', 'local:model', 'p'),
        lambda _: (LocalOutput(source, 'image'),), workspace=tmp_path / 'workspace')
    assert result.publication['status'] == 'disabled'
    assert requests == []


def test_synthetic_inherited_environment_is_cleared(tmp_path):
    token = tmp_path / 'synthetic-token'
    token.write_text('SYNTHETIC_OFFLINE_ONLY')
    env = dict(os.environ, MEDIA_API_URL='https://publication.invalid',
               MEDIA_API_TOKEN_FILE=str(token), MEDIA_API_TOKEN='SYNTHETIC_INLINE',
               MEDIAGEN_TEST_LIVE='1', FAL_KEY='SYNTHETIC_FAL',
               XAI_API_KEY='SYNTHETIC_XAI', OPENAI_API_KEY='SYNTHETIC_OPENAI',
               MEDIAGEN_GPT_IMAGE_MODEL='synthetic-inherited-model',
               MEDIAGEN_CODEX_CHAT_MODEL='synthetic-inherited-host')
    # RED is safe too: fail before executor/HTTP when the environment leaks.
    result = subprocess.run([
        sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
        str(Path(__file__).resolve()) + '::test_inherited_publication_is_disabled',
        '--basetemp=' + str(tmp_path / 'child-pytest')],
        env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_socket_connect_is_blocked_before_network():
    # An invalid port cannot reach a server even during RED (OverflowError).
    with socket.socket() as client:
        with pytest.raises(RuntimeError, match='offline suite'):
            client.connect(('127.0.0.1', -1))
