"""Upgrade contract tests: all providers mocked, no paid requests."""
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import mediagen as m


def args(**changes):
    values = dict(model="nano2", prompt="test", inputs=None, width=1280, height=720,
                  steps=28, seed=None, enable_web_search=False, quality="medium",
                  resolution="1K" if changes.get("model", "nano2") in m.NANO_MODELS else "720p",
                  aspect_ratio=None, duration=5, camera_fixed=False,
                  no_audio=False, end_image=None, upscale_factor=2, thinking_level=None,
                  image_model=None, allow_xai_api_key=False)
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("alias", ["nano2", "nano21"])
@pytest.mark.parametrize("mode", ["generate", "edit"])
def test_nano_endpoints(alias, mode):
    suffix = "/edit" if mode == "edit" else ""
    assert m.MODEL_MAP[alias][mode] == "google/nano-banana-2.1" + suffix
    assert alias in m.IMAGE_MODELS


@pytest.mark.parametrize("resolution", ["1K", "2K", "4K"])
@pytest.mark.parametrize("thinking", ["minimal", "medium", "high"])
def test_nano_payload(resolution, thinking):
    a = args(resolution=resolution, thinking_level=thinking, width=1000, height=733,
             image_urls=["https://example.test/input.png"])
    m.validate_args(a)
    payload = m.build_nano2_args(a, "edit")
    assert payload["resolution"] == resolution
    assert payload["thinking_level"] == thinking
    assert payload["aspect_ratio"] == "4:3"
    assert payload["image_urls"] == a.image_urls


def test_nano_explicit_defaults():
    payload = m.build_nano2_args(args(), "generate")
    assert payload["resolution"] == "1K"
    assert payload["thinking_level"] == "medium"


@pytest.mark.parametrize("model", ["gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"])
def test_gpt_payload_model(model):
    payload = m._build_codex_payload(prompt="test", size="1024x1024", quality="high", image_model=model)
    assert payload["tools"][0]["model"] == model


def test_verified_gpt_defaults():
    assert m.GPT_IMAGE_API_MODEL == "gpt-image-2.5-sunburst"
    assert m.CODEX_CHAT_MODEL == "gpt-6.1-sol"


@pytest.mark.parametrize("quality", ["xhigh", "max"])
def test_new_qualities_only_for_25(quality):
    m.validate_args(args(model="gptimage2", image_model="gpt-image-2.5-sunburst", quality=quality))
    with pytest.raises(SystemExit):
        m.validate_args(args(model="gptimage2", image_model="gpt-image-2", quality=quality))


@pytest.mark.parametrize("changes", [dict(model="flux2", thinking_level="high"),
    dict(model="gptimage2", thinking_level="minimal"), dict(model="flux2", resolution="2K"),
    dict(image_model="gpt-image-2"), dict(thinking_level="low"), dict(resolution="8K")])
def test_reject_incompatible_options(changes):
    with pytest.raises(SystemExit):
        m.validate_args(args(**changes))


@pytest.mark.parametrize("provider", ["xai", "", "unknown", None])
def test_helper_api_key_cannot_silently_fallback(monkeypatch, provider):
    monkeypatch.setattr(m, "_try_xai_http_credentials", lambda: {"provider": provider, "api_key": "fake-key"})
    monkeypatch.setattr(m, "_try_xai_oauth_runtime_credentials", lambda: None)
    monkeypatch.setenv("XAI_API_KEY", "another-fake-key")
    assert not m.resolve_xai_credentials().get("api_key")
    assert m.resolve_xai_credentials(allow_api_key=True)["api_key"]


def test_oauth_still_preferred_when_opted_in(monkeypatch):
    monkeypatch.setattr(m, "_try_xai_http_credentials", lambda: {"provider": "xai", "api_key": "fake-key"})
    monkeypatch.setattr(m, "_try_xai_oauth_runtime_credentials", lambda: {"provider": "xai-oauth", "api_key": "fake-oauth"})
    assert m.resolve_xai_credentials(allow_api_key=True)["provider"] == "xai-oauth"


@pytest.mark.parametrize("pipeline", ["run_image_xai", "run_video_xai"])
def test_no_generation_when_only_api_key_available(monkeypatch, pipeline, capsys):
    monkeypatch.setattr(m, "ensure_dirs", lambda **kw: None)
    monkeypatch.setattr(m, "_try_xai_http_credentials", lambda: {"provider": "xai", "api_key": "fake-key"})
    monkeypatch.setattr(m, "_try_xai_oauth_runtime_credentials", lambda: None)
    post = Mock()
    monkeypatch.setattr(m, "_xai_post_json", post)
    with pytest.raises(SystemExit):
        getattr(m, pipeline)(args(model="grokimage2"))
    post.assert_not_called()
    assert "--allow-xai-api-key" in capsys.readouterr().out


def test_gpt_log_and_sync_actual_selection(monkeypatch, tmp_path, capsys):
    for name, path in dict(WORKSPACE=tmp_path, IMAGES_DIR=tmp_path/"images", RAW_DIR=tmp_path/"images/raw",
                           EXTERNAL_DIR=tmp_path/"external", LOGS_DIR=tmp_path/"logs").items():
        monkeypatch.setattr(m, name, path)
    monkeypatch.setattr(m, "load_config", lambda: None)
    def collect(**kw):
        assert kw["image_model"] == "gpt-image-2.5-flare"
        kw["response_metadata"].update(served_image_model="reported-image-model", served_chat_model="reported-chat")
        return base64.b64encode(b"mock-image").decode()
    monkeypatch.setattr(m, "collect_codex_image_b64", collect)
    m.run_image_codex(args(model="gptimage2", image_model="gpt-image-2.5-flare"))
    log = json.loads(next((tmp_path/"logs").glob("*.json")).read_text())
    assert log["model"] == "openai-codex/gpt-image-2.5-flare"
    assert log["api_model"] == "gpt-image-2.5-flare"
    assert log["served_image_model"] == "reported-image-model"
    assert capsys.readouterr().out.splitlines()[-1].startswith("FILENAME=")


@pytest.mark.parametrize("alias", ["nano2", "nano21"])
@pytest.mark.parametrize("resolution", ["1K", "2K", "4K"])
def test_nano_cli_dispatch(monkeypatch, alias, resolution):
    import sys
    monkeypatch.setattr(sys, "argv", ["mediagen", "--model", alias, "--prompt", "test",
        "--resolution", resolution, "--thinking-level", "high"])
    calls = []
    monkeypatch.setattr(m, "run_image", calls.append)
    m.main()
    assert calls[0].model == alias
    assert calls[0].resolution == resolution
    assert calls[0].thinking_level == "high"


@pytest.mark.parametrize("alias", ["nano2", "nano21"])
@pytest.mark.parametrize("resolution", ["720p", "480p", "1080p", "1440p", "2160p"])
def test_nano_cli_invalid_resolution_never_dispatches(monkeypatch, capsys, alias, resolution):
    import sys
    monkeypatch.setattr(sys, "argv", ["mediagen", "--model", alias, "--prompt", "test",
                                     "--resolution", resolution])
    dispatch = Mock()
    monkeypatch.setattr(m, "run_image", dispatch)
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code == 1
    dispatch.assert_not_called()
    assert "--resolution for nano2/nano21 must be 1K, 2K or 4K" in capsys.readouterr().out


@pytest.mark.parametrize("model", ["nano2", "nano21", "flux2", "gptimage2", "grokimage2",
                                  "seedance2", "grokvideo", "seedvr", "upscale"])
def test_cli_model_specific_resolution_defaults(monkeypatch, model):
    import sys
    argv = ["mediagen", "--model", model, "--prompt", "test"]
    if model in {"seedvr", "upscale"}:
        argv += ["--inputs", "mock-input.png"]
    monkeypatch.setattr(sys, "argv", argv)
    dispatch = Mock()
    monkeypatch.setattr(m, "run_image", dispatch)
    monkeypatch.setattr(m, "run_video", dispatch)
    m.main()
    dispatch.assert_called_once()
    parsed = dispatch.call_args.args[0]
    assert parsed.resolution == ("1K" if model in {"nano2", "nano21"} else "720p")
    if model in {"seedvr", "upscale"}:
        parsed.image_urls = ["https://example.test/mock-input.png"]
        payload = m.build_seedvr_args(parsed)
        assert payload["upscale_mode"] == "factor"
        assert payload["upscale_factor"] == 2


@pytest.mark.parametrize("model,quality", [("gpt-image-2", "high"), ("gpt-image-2.5-flare", "max"), ("gpt-image-2.5-sunburst", "xhigh")])
def test_gpt_cli_dispatch(monkeypatch, model, quality):
    import sys
    monkeypatch.setattr(sys, "argv", ["mediagen", "--model", "gptimage2", "--prompt", "test",
        "--image-model", model, "--quality", quality])
    calls = []
    monkeypatch.setattr(m, "run_image", calls.append)
    m.main()
    assert calls[0].image_model == model
    assert calls[0].quality == quality


@pytest.mark.parametrize("alias", ["grokimage2", "grokvideo"])
def test_xai_cli_opt_in_dispatch(monkeypatch, alias):
    import sys
    monkeypatch.setattr(sys, "argv", ["mediagen", "--model", alias, "--prompt", "test", "--allow-xai-api-key"])
    calls = []
    monkeypatch.setattr(m, "run_image", calls.append)
    monkeypatch.setattr(m, "run_video", calls.append)
    m.main()
    assert calls[0].allow_xai_api_key is True


def test_gpt_env_default_validated_and_selector_wins(monkeypatch):
    monkeypatch.setattr(m, "GPT_IMAGE_API_MODEL", "invalid-env-model")
    with pytest.raises(SystemExit):
        m.validate_args(args(model="gptimage2"))
    assert m.resolve_gpt_image_model(args(image_model="gpt-image-2")) == "gpt-image-2"


def test_codex_stream_selection_and_metadata(monkeypatch):
    import httpx
    import sys
    from types import ModuleType
    monkeypatch.setattr(m, "_read_codex_access_token", lambda: "fake-test-token")
    monkeypatch.setattr(m, "_codex_headers", lambda token: {})
    events = [dict(type="response.completed", response=dict(model="served-chat", output=[
        dict(type="image_generation_call", model="served-image", result="bW9jaw==")]))]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *exc): pass
        def raise_for_status(self): pass
        def iter_lines(self):
            for event in events:
                yield "data: " + json.dumps(event)
                yield ""
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *exc): pass
        def stream(self, method, url, json):
            assert json["tools"][0]["model"] == "gpt-image-2.5-flare"
            return Response()
    monkeypatch.setattr(httpx, "Client", Client)
    metadata = {}
    assert m.collect_codex_image_b64(prompt="test", size="1024x1024", quality="high",
        image_model="gpt-image-2.5-flare", response_metadata=metadata) == "bW9jaw=="
    assert metadata == dict(served_chat_model="served-chat", served_image_model="served-image")


def test_runtime_helper_provenance_not_relabeled(monkeypatch):
    import sys
    from types import ModuleType
    auth = ModuleType("hermes_cli.auth")
    auth.resolve_xai_oauth_runtime_credentials = lambda: dict(provider="xai", api_key="fake-key")
    monkeypatch.setitem(sys.modules, "hermes_cli.auth", auth)
    monkeypatch.setattr(m, "_ensure_hermes_on_path", lambda: None)
    assert m._try_xai_oauth_runtime_credentials() is None


def test_response_model_metadata_not_inferred():
    metadata = {}
    m._capture_codex_response_metadata({"type": "response.completed", "response": {
        "model": "chat-served", "output": [{"type": "image_generation_call", "model": "image-served"}]}}, metadata)
    assert metadata == {"served_chat_model": "chat-served", "served_image_model": "image-served"}
    absent = {}
    m._capture_codex_response_metadata({"type": "image_generation_call", "result": "abc"}, absent)
    assert absent == {}
