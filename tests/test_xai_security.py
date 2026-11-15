"""Offline regressions for xAI download and credential trust boundaries."""
from types import SimpleNamespace
import builtins

import httpx
import pytest
import mediagen as m


@pytest.fixture
def auth_imports(monkeypatch):
    """Intercept both Hermes loaders: never touch installed auth or real profiles."""
    monkeypatch.setattr(m, "_ensure_hermes_on_path", lambda: None)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_BASE_URL", raising=False)
    original = builtins.__import__
    def install(http_result=None, oauth_result=None):
        def load(name, *args, **kwargs):
            if name in {"tools.xai_http", "hermes_cli.auth"}:
                result = http_result if name == "tools.xai_http" else oauth_result
                if isinstance(result, Exception):
                    raise result
                if name == "tools.xai_http":
                    return SimpleNamespace(resolve_xai_http_credentials=lambda: result)
                return SimpleNamespace(resolve_xai_oauth_runtime_credentials=lambda: result)
            return original(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", load)
    return install


def test_missing_http_helper_does_not_block_runtime_oauth(auth_imports):
    auth_imports(ModuleNotFoundError("not installed", name="tools.xai_http"),
                 {"provider": "xai-oauth", "access_token": "fake-oauth"})
    assert m.resolve_xai_credentials() == {
        "provider": "xai-oauth", "api_key": "fake-oauth", "base_url": "https://api.x.ai/v1"}


@pytest.mark.parametrize("loader,module,parent", [
    ("_try_xai_http_credentials", "tools.xai_http", "tools"),
    ("_try_xai_oauth_runtime_credentials", "hermes_cli.auth", "hermes_cli"),
])
@pytest.mark.parametrize("missing_parent", [False, True])
def test_missing_helper_diagnostic_is_not_broken_dependency(auth_imports, loader, module, parent, missing_parent):
    error = ModuleNotFoundError("private detail", name=parent if missing_parent else module)
    auth_imports(error, error)
    with pytest.raises(RuntimeError, match="helper unavailable") as caught:
        getattr(m, loader)()
    assert "private detail" not in str(caught.value)


@pytest.mark.parametrize("loader", ["_try_xai_http_credentials", "_try_xai_oauth_runtime_credentials"])
def test_internal_import_failure_retains_code_diagnostic(auth_imports, loader):
    error = ModuleNotFoundError("private detail", name="broken_dependency")
    auth_imports(error, error)
    with pytest.raises(RuntimeError, match="import failed.*module: broken_dependency") as caught:
        getattr(m, loader)()
    assert "private detail" not in str(caught.value)


@pytest.mark.parametrize("allow_api_key", [False, True])
def test_missing_runtime_helper_respects_shared_api_key_opt_in(auth_imports, allow_api_key):
    auth_imports({"provider": "xai", "api_key": "fake-shared-key"},
                 ModuleNotFoundError("private detail", name="hermes_cli.auth"))
    if allow_api_key:
        assert m.resolve_xai_credentials(allow_api_key=True)["api_key"] == "fake-shared-key"
    else:
        with pytest.raises(RuntimeError, match="OAuth helper unavailable"):
            m.resolve_xai_credentials()


@pytest.mark.parametrize("allow_api_key", [False, True])
def test_missing_helpers_respect_environment_api_key_opt_in(auth_imports, monkeypatch, allow_api_key):
    auth_imports(ModuleNotFoundError("private detail", name="tools.xai_http"),
                 ModuleNotFoundError("private detail", name="hermes_cli.auth"))
    monkeypatch.setenv("XAI_API_KEY", "fake-env-key")
    if allow_api_key:
        assert m.resolve_xai_credentials(allow_api_key=True) == {
            "provider": "xai", "api_key": "fake-env-key", "base_url": "https://api.x.ai/v1"}
    else:
        with pytest.raises(RuntimeError) as caught:
            m.require_xai_credentials()
        message = str(caught.value)
        assert "auth helper unavailable" in message
        assert "OAuth helper unavailable" in message
        assert "No xAI OAuth credentials" not in message
        assert "fake-env-key" not in message
        assert "private detail" not in message


def test_broken_dependency_does_not_block_valid_runtime_oauth(auth_imports):
    auth_imports(ModuleNotFoundError("private detail", name="broken_dependency"),
                 {"provider": "xai-oauth", "api_key": "fake-oauth"})
    assert m.resolve_xai_credentials()["api_key"] == "fake-oauth"


def test_import_errors_aggregate_only_after_authorized_paths_exhausted(auth_imports):
    auth_imports(ModuleNotFoundError("private detail", name="broken_dependency"),
                 ImportError("private detail", name="hermes_cli.auth"))
    with pytest.raises(RuntimeError) as caught:
        m.resolve_xai_credentials(allow_api_key=True)
    message = str(caught.value)
    assert "auth helper import failed (module: broken_dependency)" in message
    assert "OAuth helper import failed (module: hermes_cli.auth)" in message
    assert "helper unavailable" not in message
    assert "private detail" not in message


@pytest.fixture
def mock_download(monkeypatch):
    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(m, "_require_httpx", lambda: SimpleNamespace(
            Client=lambda **kw: httpx.Client(transport=transport, **kw)))
    return install


@pytest.mark.parametrize("url", [
    "https://imgen.x.ai/tmp.png", "https://vidgen.x.ai/tmp.mp4",
    "https://external.test/media", "https://api.x.ai.evil.test/media",
    "https://sub.api.x.ai/media", "https://api.x.ai:8443/media",
])
def test_external_download_has_no_credentials(url, tmp_path, mock_download):
    def handle(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"media")
    mock_download(handle)
    dest = tmp_path / "out"
    m.download_xai_media(url, dest, {"api_key": "fake-token", "base_url": url})
    assert dest.read_bytes() == b"media"


@pytest.mark.parametrize("url", [
    "http://api.x.ai/media", "http://external.test/media", "/relative",
    "https:///missing-host", "https://api.x.ai@external.test/media",
    "https://user:password@api.x.ai/media",
])
def test_invalid_download_url_rejected_before_request(url, tmp_path, mock_download, capsys):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, content=b"media")
    mock_download(handle)
    dest = tmp_path / "out"
    with pytest.raises(SystemExit):
        m.download_xai_media(url, dest, {"api_key": "fake-token"})
    assert seen == []
    assert not dest.exists()
    assert "HTTPS" in capsys.readouterr().out


@pytest.mark.parametrize("url", ["https://api.x.ai/media", "https://api.x.ai:443/media"])
def test_exact_api_origin_keeps_authenticated_download(url, tmp_path, mock_download):
    seen = []
    def handle(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, content=b"media")
    mock_download(handle)
    dest = tmp_path / "out"
    m.download_xai_media(url, dest, {"api_key": "fake-token"})
    assert seen == ["Bearer fake-token"]
    assert dest.read_bytes() == b"media"


@pytest.mark.parametrize("target", ["http://api.x.ai/media", "http://external.test/media",
                                  "https://user:password@external.test/media"])
def test_redirect_target_validated_before_request(target, tmp_path, mock_download):
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": target})
        return httpx.Response(200, content=b"media")
    mock_download(handle)
    dest = tmp_path / "out"
    with pytest.raises(SystemExit):
        m.download_xai_media("https://api.x.ai/start", dest, {"api_key": "fake-token"})
    assert seen == ["https://api.x.ai/start"]
    assert not dest.exists()


def test_redirects_do_not_forward_bearer_to_external_origin(tmp_path, mock_download):
    seen = []
    def handle(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        if request.url.host == "api.x.ai":
            return httpx.Response(302, headers={"location": "https://external.test/media"})
        return httpx.Response(200, content=b"media")
    mock_download(handle)
    dest = tmp_path / "out"
    m.download_xai_media("https://api.x.ai/start", dest, {"api_key": "fake-token"})
    assert seen == [("https://api.x.ai/start", "Bearer fake-token"),
                    ("https://external.test/media", None)]
    assert dest.read_bytes() == b"media"
