"""Small, explicit offline harness shared by pytest and Python child probes.

Not an OS sandbox: children must install this harness before importing app code.
"""
import os
import socket


# Do not retain inherited publication/auth/provider defaults in offline tests.
OFFLINE_ENV = (
    'MEDIA_API_URL', 'MEDIA_API_TOKEN_FILE', 'MEDIA_API_TOKEN',
    'MEDIA_UPLOAD_TIMEOUT_SECONDS', 'MEDIAGEN_TEST_LIVE',
    'FAL_KEY', 'XAI_API_KEY', 'XAI_BASE_URL', 'OPENAI_API_KEY',
    'MEDIAGEN_GPT_IMAGE_MODEL', 'MEDIAGEN_CODEX_CHAT_MODEL',
    'MEDIAGEN_WORKSPACE',
)


def clear_live_environment(monkeypatch):
    for name in OFFLINE_ENV:
        monkeypatch.delenv(name, raising=False)


def deny_network(*args, **kwargs):
    raise RuntimeError('network disabled by mediagen offline suite')


def install(monkeypatch):
    clear_live_environment(monkeypatch)
    # Block before DNS or OS connect/send, independently of the HTTP library.
    for name in ('create_connection', 'getaddrinfo', 'gethostbyname', 'gethostbyname_ex'):
        monkeypatch.setattr(socket, name, deny_network)
    for name in ('connect', 'connect_ex', 'sendto', 'sendmsg'):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, deny_network)
