"""Offline durability and publication contracts (Task 2)."""
import json

import pytest

import media_client as mc
import media_sync
import mediagen


def generation():
    return {"operation": "generate", "provider": "fal", "model": "flux2",
            "prompt": "keep my useful prompt", "seed": 42,
            "params": {"steps": 28, "nested": [{"api_key": "KEYSECRET", "note": "Bearer BEARERSECRET"}]},
            "provider_result": {"url": "https://example.test/a?X-Amz-Signature=SIGNEDSECRET", "width": 720},
            "outputs": [{"path": "images/raw/out.png", "position": 0}]}


def test_payload_is_durable_sanitized_before_network_and_retry_uses_it(tmp_path, monkeypatch):
    cfg = mc.MediaConfig(True, "https://media.test", "TOKENVALUE")
    def offline(*args, **kwargs):
        disk = mc.load_receipt(next((tmp_path / "receipts").glob("*.json")))
        assert disk["generation"]["prompt"] == generation()["prompt"]
        assert disk["generation"]["params"]["steps"] == 28
        raw = json.dumps(disk)
        for secret in ("KEYSECRET", "BEARERSECRET", "SIGNEDSECRET", "TOKENVALUE"):
            assert secret not in raw
        raise mc.MediaHTTPError(0, "offline")
    monkeypatch.setattr(mc, "upload_asset", offline)
    receipt = mc.sync_if_enabled(cfg, workspace=tmp_path, log_path="logs/out.json",
                                 assets=[{"path": "images/raw/out.png"}], generation=generation())
    assert receipt["status"] == "pending"
    assert receipt["last_error"] == "offline"
    assert media_sync.rebuild_generation(tmp_path, receipt) == receipt["generation"]


def test_reentry_resumes_progress_completed_noop_and_rejects_changed_payload(tmp_path, monkeypatch):
    cfg = mc.MediaConfig(True, "https://media.test", "TOKENVALUE")
    calls = []
    def upload(*args, **kwargs):
        calls.append(kwargs["asset"]["path"])
        return {"media_item_id": "media-1", "uploaded_at": "2026-01-01T00:00:00Z"}
    monkeypatch.setattr(mc, "upload_asset", upload)
    monkeypatch.setattr(mc, "post_generation_run", lambda *a, **k: (_ for _ in ()).throw(mc.MediaHTTPError(0, "offline")))
    kwargs = dict(workspace=tmp_path, log_path="logs/out.json", assets=[{"path": "images/raw/out.png"}], generation=generation())
    first = mc.sync_if_enabled(cfg, **kwargs)
    assert first["assets"][0]["media_item_id"] == "media-1"
    monkeypatch.setattr(mc, "post_generation_run", lambda *a, **k: {"generation_run_id": "run-1"})
    second = mc.sync_if_enabled(cfg, **kwargs)
    assert calls == ["images/raw/out.png"]
    assert second["attempts"] == 2
    assert second["status"] == "completed"
    assert mc.sync_if_enabled(cfg, **kwargs) == second
    changed = dict(kwargs, generation=dict(generation(), prompt="different"))
    with pytest.raises(ValueError, match="incompatible"):
        mc.sync_if_enabled(cfg, **changed)
    disk = mc.load_receipt(next((tmp_path / "receipts").glob("*.json")))
    assert disk == second


@pytest.mark.parametrize("env", [{"MEDIA_API_URL": "https://media.test"},
                                  {"MEDIA_API_TOKEN_FILE": "missing"},
                                  {"MEDIA_API_URL": ""}])
def test_intended_broken_config_persists_recoverable_payload(tmp_path, monkeypatch, env):
    cfg = mc.load_config(env)
    assert cfg.publication_status == "config_error"
    receipt = mc.sync_if_enabled(cfg, workspace=tmp_path, log_path="logs/out.json",
                                 assets=[{"path": "images/raw/out.png"}], generation=generation())
    assert receipt["status"] == "config_error"
    assert receipt["attempts"] == 0
    assert receipt["generation"]["prompt"] == generation()["prompt"]
    assert receipt["last_error"]
    monkeypatch.setattr(media_sync, "load_config", lambda: mc.MediaConfig(True, "https://media.test", "TOKENVALUE"))
    monkeypatch.setattr(mc, "upload_asset", lambda *a, **k: {"media_item_id": "mid", "uploaded_at": "now"})
    monkeypatch.setattr(mc, "post_generation_run", lambda *a, **k: {"generation_run_id": "rid"})
    assert media_sync.cmd_retry(workspace=tmp_path)["retried"] == 1
    assert mc.load_receipt(next((tmp_path / "receipts").glob("*.json")))["status"] == "completed"


@pytest.mark.parametrize("url", [
    "not-a-url", "ftp://media.test", "https://user:PASS@media.test",
    "https://media.test/#fragment", "https://media.test/?token=URLSECRET",
    "https://", "https://media.test:bad", "https://media.test/\nheader",
    "http://public.example.test",
])
def test_invalid_api_url_is_config_error_before_http_and_receipt_can_retry(tmp_path, monkeypatch, url):
    import io

    token_file = tmp_path / "token"
    token_file.write_text("TOKENVALUE")
    env = {"MEDIA_API_URL": url, "MEDIA_API_TOKEN_FILE": str(token_file)}
    monkeypatch.setenv("MEDIA_API_URL", url)
    monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token_file))
    calls = []
    class MockResponse(io.BytesIO):
        status = 201

    def mock_http(request, **kwargs):
        calls.append(request.full_url)
        return MockResponse(b'{"id":"offline-id"}')
    monkeypatch.setattr(mc.urllib.request, "urlopen", mock_http)
    cfg = mc.load_config(env)
    assert cfg.publication_status == "config_error"
    receipt = mc.sync_if_enabled(cfg, workspace=tmp_path, log_path="logs/out.json",
                                assets=[{"path": "images/raw/out.png"}], generation=generation())
    assert receipt["status"] == "config_error"
    assert receipt["attempts"] == 0
    assert calls == []
    assert "URLSECRET" not in json.dumps(receipt)
    asset = tmp_path / "images/raw/out.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"offline fixture")
    monkeypatch.setenv("MEDIA_API_URL", "http://localhost:8000")
    report = media_sync.cmd_retry(workspace=tmp_path)
    assert report == {"retried": 1, "skipped": 0, "errors": [], "enabled": True}
    assert len(calls) == 2
    assert mc.load_receipt(next((tmp_path / "receipts").glob("*.json")))["status"] == "completed"


@pytest.mark.parametrize("url", ["https://media.test/base/", "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])
def test_valid_api_urls_keep_local_http_compatibility(tmp_path, url):
    token_file = tmp_path / "token"
    token_file.write_text("TOKENVALUE")
    assert mc.load_config({"MEDIA_API_URL": url, "MEDIA_API_TOKEN_FILE": str(token_file)}).enabled


def test_unconfigured_is_disabled_without_receipt(tmp_path):
    cfg = mc.load_config({})
    assert cfg.publication_status == "disabled"
    assert mc.sync_if_enabled(cfg, workspace=tmp_path, log_path="logs/out.json", assets=[], generation={}) is None
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize("status", ["completed", "pending", "failed", "conflict", "disabled", "config_error", "import_error", "crash"])
def test_finalization_reports_publication_without_breaking_final_line(tmp_path, monkeypatch, capsys, status):
    monkeypatch.setattr(mediagen, "WORKSPACE", tmp_path)
    monkeypatch.setattr(mediagen, "build_media_sync_payload", lambda **k: ([], generation()))
    monkeypatch.setattr(mediagen, "load_config", lambda: mc.MediaConfig(True, "https://media.test", "TOKENVALUE"))
    def sync(*a, **k):
        if status == "crash":
            raise RuntimeError("Bearer TOKENVALUE https://test/a?sig=SIGNEDSECRET")
        return None if status == "disabled" else {"status": status, "last_error": "Bearer TOKENVALUE https://test/a?sig=SIGNEDSECRET"}
    monkeypatch.setattr(mediagen, "sync_if_enabled", None if status == "import_error" else sync)
    meta = dict(filename="out.png", prompt="hello", seed_display=42, kind="image", mode="generate", model="flux2", endpoint="fal-ai/flux-2", output_path=tmp_path / "images/raw/out.png", log_path=tmp_path / "logs/out.json")
    mediagen.finalize_generation_with_media_sync(meta)
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == "FILENAME=out.png PROMPT=hello SEED=42"
    expected = "config_error" if status == "import_error" else "pending" if status == "crash" else status
    assert meta["publication"]["status"] == expected
    assert f"PUBLICATION={expected}" in captured.err
    assert "TOKENVALUE" not in captured.err
    assert "SIGNEDSECRET" not in captured.err
    if status == "import_error":
        assert "media_client" in captured.err


def test_retry_reports_noncompleted_result_and_can_use_receipt_alone(tmp_path, monkeypatch):
    cfg = mc.MediaConfig(True, "https://media.test", "TOKENVALUE")
    receipt = mc.create_receipt(workspace=tmp_path, log_path="logs/out.json", assets=[{"path": "images/raw/out.png"}], generation=generation())
    monkeypatch.setattr(mc, "upload_asset", lambda *a, **k: (_ for _ in ()).throw(mc.MediaHTTPError(422, "invalid Bearer TOKENVALUE")))
    result = mc.sync_receipt(cfg, receipt=receipt, workspace=tmp_path)
    assert result["status"] == "failed"
    result["status"] = "pending"
    mc.save_receipt(result, tmp_path / "receipts")
    monkeypatch.setattr(media_sync, "load_config", lambda: cfg)
    report = media_sync.cmd_retry(workspace=tmp_path)
    assert report["retried"] == 1
    assert report["errors"]
    assert "failed" in report["errors"][0]
    assert "TOKENVALUE" not in json.dumps(report)


@pytest.mark.parametrize("value,secret", [
    ({"X-Amz-Signature": "AWSSECRET"}, "AWSSECRET"),
    ({"signed_url": "https://u:PASSSECRET@example.test/a"}, "PASSSECRET"),
    ({"nested": ["password=PASSSECRET"]}, "PASSSECRET"),
    ({"url": "https://test/a?X-Goog-Credential=GOOGSECRET"}, "GOOGSECRET"),
])
def test_recursive_sanitizer_covers_credentials_and_signed_urls(value, secret):
    assert secret not in json.dumps(mc.sanitize_payload(value))


@pytest.mark.parametrize("entrypoint", ["cmd_retry", "main"])
def test_retry_invalid_utf8_token_file_returns_controlled_config_error(tmp_path, monkeypatch, capsys, entrypoint):
    token_file = tmp_path / "token"
    token_file.write_bytes(b"\xff\xfe")
    monkeypatch.delenv("MEDIA_API_TOKEN", raising=False)
    monkeypatch.setenv("MEDIA_API_URL", "https://media.test")
    monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(mc.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    receipt = mc.create_receipt(workspace=tmp_path, log_path="logs/out.json",
                                assets=[{"path": "images/raw/out.png"}], generation=generation())
    if entrypoint == "main":
        assert media_sync.main(["retry", "--workspace", str(tmp_path)]) == 1
        report = json.loads(capsys.readouterr().out)
    else:
        report = media_sync.cmd_retry(workspace=tmp_path)
    assert report["enabled"] is False
    assert report["retried"] == 0
    assert report["skipped"] == 1
    assert "config_error" in report["errors"][0]
    assert "UnicodeDecodeError" not in json.dumps(report)
    assert mc.load_receipt(next((tmp_path / "receipts").glob("*.json"))) == receipt


@pytest.mark.parametrize("token_content", [b"", b"\xff", None])
def test_bad_token_file_is_recoverable_config_error(tmp_path, monkeypatch, token_content):
    token = tmp_path / "token"
    token.write_bytes(token_content or b"")
    if token_content is None:
        monkeypatch.setattr(mc.Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(PermissionError("not readable")))
    cfg = mc.load_config({"MEDIA_API_URL": "https://media.test", "MEDIA_API_TOKEN_FILE": str(token)})
    assert cfg.publication_status == "config_error"


def test_run_validation_failure_is_failed_not_pending(tmp_path, monkeypatch):
    cfg = mc.MediaConfig(True, "https://media.test", "TOKENVALUE")
    receipt = mc.create_receipt(workspace=tmp_path, log_path="logs/out.json", assets=[{"path": "images/raw/out.png"}], generation=generation())
    monkeypatch.setattr(mc, "upload_asset", lambda *a, **k: {"media_item_id": "mid", "uploaded_at": "now"})
    monkeypatch.setattr(mc, "post_generation_run", lambda *a, **k: (_ for _ in ()).throw(mc.MediaHTTPError(422, "invalid generation")))
    assert mc.sync_receipt(cfg, workspace=tmp_path, receipt=receipt)["status"] == "failed"


def test_incompatible_reentry_is_observed_as_conflict_without_overwriting(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mediagen, "WORKSPACE", tmp_path)
    cfg = mc.MediaConfig(True, "https://media.test", "TOKENVALUE")
    monkeypatch.setattr(mediagen, "load_config", lambda: cfg)
    receipt = mc.create_receipt(workspace=tmp_path, log_path="logs/out.json", assets=[{"path": "images/raw/out.png"}], generation=generation())
    monkeypatch.setattr(mediagen, "build_media_sync_payload", lambda **k: ([{"path": "images/raw/different.png"}], generation()))
    meta = dict(filename="out.png", prompt="hello", seed_display=42, kind="image", mode="generate", model="flux2", endpoint="fal-ai/flux-2", output_path=tmp_path / "images/raw/out.png", log_path=tmp_path / "logs/out.json")
    mediagen.finalize_generation_with_media_sync(meta)
    assert meta["publication"]["status"] == "conflict"
    assert "PUBLICATION=conflict" in capsys.readouterr().err
    assert mc.load_receipt(next((tmp_path / "receipts").glob("*.json"))) == receipt


@pytest.mark.parametrize("text", [
    "Authorization: Bearer AUTHVALUE", "{'Authorization': 'Bearer AUTHVALUE'}",
    "diagnostic JWT eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SIGNATUREVALUE",
])
def test_auth_context_and_identifiable_jwt_are_redacted(text):
    clean = mc.sanitize_error_text(text)
    assert "AUTHVALUE" not in clean
    assert "eyJhbGci" not in clean


@pytest.mark.parametrize("prompt", ["Portrait of a bearer holding flowers", "a bearer holding a token", "Bearer holding flowers"])
def test_auth_sanitizer_preserves_ordinary_words_and_tokenizer_metadata(prompt):
    payload = {"prompt": prompt, "params": {"tokenizer": "clip", "tokenizer_max_length": 77,
               "max_tokens": 1024, "token_count": 52, "input_tokens": 12}}
    assert mc.sanitize_payload(payload) == payload
    assert mc.sanitize_error_text(prompt) == prompt


def test_sanitization_preserves_useful_token_counts_and_prompt():
    payload = {"prompt": "paint a red flower", "params": {"max_tokens": 1024, "token_count": 52, "auth_token": "SECRET"}}
    clean = mc.sanitize_payload(payload)
    assert clean["prompt"] == payload["prompt"]
    assert clean["params"]["max_tokens"] == 1024
    assert clean["params"]["token_count"] == 52
    assert "SECRET" not in json.dumps(clean)


def test_legacy_reentry_with_broken_config_upgrades_payload_without_resetting_ids(tmp_path):
    receipt = mc.create_receipt(workspace=tmp_path, log_path="logs/out.json", assets=[{"path": "images/raw/out.png"}])
    receipt["assets"][0]["media_item_id"] = "existing-mid"
    receipt["attempts"] = 3
    mc.save_receipt(receipt, tmp_path / "receipts")
    result = mc.sync_if_enabled(mc.load_config({"MEDIA_API_URL": "https://media.test"}), workspace=tmp_path,
                                log_path="logs/out.json", assets=[{"path": "images/raw/out.png"}], generation=generation())
    assert result["generation"]["prompt"] == generation()["prompt"]
    assert result["assets"][0]["media_item_id"] == "existing-mid"
    assert result["attempts"] == 3
    assert result["status"] == "config_error"


@pytest.mark.parametrize("text", ["{'password': 'ERRSECRET'}", "secret='ERRSECRET'", "{'refresh_token': 'ERRSECRET'}"])
def test_error_diagnostics_redact_single_quoted_secrets(text):
    assert "ERRSECRET" not in mc.sanitize_error_text(text)


@pytest.mark.parametrize("text", [
    "client_secret=SPECSECRET", "refresh_token=SPECSECRET",
    "private_key=SPECSECRET", "Cookie: SPECSECRET", "auth_token=SPECSECRET",
    "{'private_key': 'SPECSECRET'}", "{'Cookie': 'SPECSECRET'}",
])
def test_identified_unquoted_credentials_are_redacted_in_payload_and_http_errors(tmp_path, monkeypatch, text):
    import io
    import urllib.error
    from email.message import Message

    assert "SPECSECRET" not in mc.sanitize_error_text(text)
    assert "SPECSECRET" not in json.dumps(mc.sanitize_payload({"nested": [text]}))
    cfg = mc.MediaConfig(True, "https://media.test", "TOKENVALUE")
    asset = tmp_path / "images/raw/out.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"offline fixture")
    def fail_http(*a, **k):
        raise urllib.error.HTTPError("https://media.test", 503, "offline", Message(), io.BytesIO(text.encode()))
    monkeypatch.setattr(mc.urllib.request, "urlopen", fail_http)
    result = mc.sync_if_enabled(cfg, workspace=tmp_path, log_path="logs/out.json",
                                assets=[{"path": "images/raw/out.png"}], generation=generation())
    assert result["status"] == "pending"
    assert "SPECSECRET" not in json.dumps(result)
    assert "SPECSECRET" not in next((tmp_path / "receipts").glob("*.json")).read_text()


def assert_sensitive_diagnostic_is_not_persisted(tmp_path, monkeypatch, text, secrets, retained):
    """Exercise real pre-request persistence, HTTP decoding, and pending receipt writes."""
    import io
    import urllib.error
    from email.message import Message

    asset = tmp_path / "images/raw/out.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"offline fixture")
    before_request = []

    def fail_http(*a, **k):
        path = next((tmp_path / "receipts").glob("*.json"))
        before_request.append(json.loads(path.read_text()))
        raise urllib.error.HTTPError("https://media.test", 503, "offline", Message(), io.BytesIO(text.encode()))

    monkeypatch.setattr(mc.urllib.request, "urlopen", fail_http)
    payload = generation()
    payload["provider_result"]["diagnostic"] = text
    result = mc.sync_if_enabled(mc.MediaConfig(True, "https://media.test", "TOKENVALUE"),
                                workspace=tmp_path, log_path="logs/out.json",
                                assets=[{"path": "images/raw/out.png"}], generation=payload)
    assert len(before_request) == 1
    path = next((tmp_path / "receipts").glob("*.json"))
    disk = json.loads(path.read_text())
    assert disk == result
    assert disk["status"] == "pending"
    surfaces = {"before_http": json.dumps(before_request[0]), "receipt_json": path.read_text(),
                "generation": disk["generation"]["provider_result"]["diagnostic"],
                "last_error": disk["last_error"]}
    leaks = [(name, secret) for name, surface in surfaces.items() for secret in secrets if secret in surface]
    assert leaks == []
    for surface in surfaces.values():
        for metadata in retained:
            assert metadata in surface
    assert disk["generation"]["prompt"] == payload["prompt"]


@pytest.mark.parametrize("field", [
    "credential", "private_key", "api_key", "token", "password", "secret",
    "access_key", "authorization", "cookie",
])
@pytest.mark.parametrize("style", ["unquoted", "single", "double", "json"])
def test_credential_assignment_styles_are_redacted_before_http_and_after_503(tmp_path, monkeypatch, field, style):
    secret = "REVIEW_SENTINEL_8427"
    value = f"Bearer {secret}" if field == "authorization" else secret
    if style == "json":
        text = json.dumps({field: value, "request_id": "keep-assignment-metadata"})
    else:
        quote = {"unquoted": "", "single": "'", "double": '"'}[style]
        text = f"{field}={quote}{value}{quote}\nrequest_id=keep-assignment-metadata"
    assert_sensitive_diagnostic_is_not_persisted(
        tmp_path, monkeypatch, text, [secret], ["keep-assignment-metadata"])
    assert secret not in mc.sanitize_error_text(text)


@pytest.mark.parametrize("header", ["Cookie", "Set-Cookie"])
def test_multivalue_cookie_header_is_removed_through_line_end(tmp_path, monkeypatch, header):
    text = f"{header}: a=COOKIEFIRSTSECRET; session=COOKIESECONDSECRET; Path=/; HttpOnly\nrequest_id=keep-next-line"
    assert_sensitive_diagnostic_is_not_persisted(
        tmp_path, monkeypatch, text, ["COOKIEFIRSTSECRET", "COOKIESECONDSECRET"], ["request_id=keep-next-line"])


@pytest.mark.parametrize("header", ["Cookie", "Set-Cookie"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", r"\n", r"\r\n"])
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_cookie_diagnostic_boundaries_preserve_following_metadata(tmp_path, monkeypatch, header, newline, quote):
    cookie = "a=COOKIEFIRSTSECRET; session=COOKIESECONDSECRET"
    if quote:
        text = f"{{{quote}{header}{quote}: {quote}{cookie}{quote}, 'request_id': 'keep-after-cookie'}}"
        text += newline + "next_field=keep-next-field"
    else:
        text = f"{header}: {cookie}" + newline + "next_field=keep-next-field"
    assert_sensitive_diagnostic_is_not_persisted(
        tmp_path, monkeypatch, text, ["COOKIEFIRSTSECRET", "COOKIESECONDSECRET"],
        ["keep-after-cookie", "keep-next-field"] if quote else ["keep-next-field"])


@pytest.mark.parametrize("key_kind", ["PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "ENCRYPTED PRIVATE KEY"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", r"\n", r"\r\n"])
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_multiline_pem_is_removed_without_consuming_its_following_metadata(tmp_path, monkeypatch, key_kind, newline, quote):
    pem = newline.join([f"-----BEGIN {key_kind}-----", "PEMCONTENTSSECRET", f"-----END {key_kind}-----"])
    text = f"private_key={quote}{pem}{quote}; request_id=keep-after-pem" + newline + "next_field=keep-next-field"
    assert_sensitive_diagnostic_is_not_persisted(
        tmp_path, monkeypatch, text, ["PEMCONTENTSSECRET"], ["keep-after-pem", "keep-next-field"])


@pytest.mark.parametrize("field", ["private_key", "Cookie", "Set-Cookie"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", r"\n", r"\r\n"])
@pytest.mark.parametrize("quote", ["'", '"'])
def test_quoted_multiline_credentials_stop_at_unescaped_closing_quote(tmp_path, monkeypatch, field, newline, quote):
    value = "FIRSTLINESECRET" + newline + "escaped=" + "\\" + quote + "SECONDLINESECRET"
    text = f"{field}: {quote}{value}{quote}, request_id=keep-after-quote"
    assert_sensitive_diagnostic_is_not_persisted(
        tmp_path, monkeypatch, text, ["FIRSTLINESECRET", "SECONDLINESECRET"], ["keep-after-quote"])


@pytest.mark.parametrize("text", [
    "A cookie cutter and private key symbolism in a still life",
    "Show BEGIN PRIVATE KEY as typography, without a key block",
    "-----BEGIN PUBLIC KEY-----\nPUBLIC-CONTENT\n-----END PUBLIC KEY-----",
])
def test_credential_block_sanitization_preserves_nonsecret_prose(text):
    payload = {"prompt": text, "params": {"tokenizer": "clip", "max_tokens": 1024, "token_count": 12}}
    assert mc.sanitize_payload(payload) == payload
