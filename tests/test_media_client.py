"""Unit tests for media_client — mock HTTP boundary, no live Media API."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import media_client


class TestMissingConfigDisablesSync:
    def test_missing_media_api_url_disables_sync_without_error(self, tmp_path):
        env = {
            "MEDIA_API_TOKEN_FILE": str(tmp_path / "token"),
        }
        (tmp_path / "token").write_text("secret-token\n", encoding="utf-8")
        cfg = media_client.load_config(env)
        assert cfg.enabled is False
        assert cfg.token is None

        result = media_client.sync_if_enabled(
            cfg,
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": "images/raw/example.png", "kind": "image"}],
            generation={"operation": "generate", "provider": "fal", "model": "flux2"},
        )
        assert result is None

    def test_missing_token_file_disables_sync_without_error(self, tmp_path):
        env = {
            "MEDIA_API_URL": "https://media.example.test",
            "MEDIA_API_TOKEN_FILE": str(tmp_path / "missing-token"),
        }
        cfg = media_client.load_config(env)
        assert cfg.enabled is False
        assert cfg.token is None
        assert media_client.sync_if_enabled(
            cfg,
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[],
            generation={},
        ) is None


class TestTokenFromFileNeverPersisted:
    def test_token_read_from_file_and_absent_from_receipt(self, tmp_path):
        token_path = tmp_path / "token"
        secret = "super-secret-bearer-token-xyz"
        token_path.write_text(secret + "\n", encoding="utf-8")
        env = {
            "MEDIA_API_URL": "https://media.example.test",
            "MEDIA_API_TOKEN_FILE": str(token_path),
        }
        cfg = media_client.load_config(env)
        assert cfg.enabled is True
        assert cfg.token == secret

        receipts_dir = tmp_path / "receipts"
        asset_rel = "images/raw/example.png"
        asset_abs = tmp_path / asset_rel
        asset_abs.parent.mkdir(parents=True)
        asset_abs.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        # No HTTP: create receipt only path used by callers before sync
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": asset_rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )
        raw = json.dumps(receipt)
        assert secret not in raw
        assert "Bearer" not in raw
        assert "Authorization" not in raw

        # Re-open from disk and assert again
        loaded = media_client.load_receipt(receipts_dir / media_client.receipt_filename(receipt["run_key"]))
        assert secret not in json.dumps(loaded)
        assert cfg.token == secret  # still only in memory config


class TestAtomicReceipt:
    def test_receipt_created_atomically_and_reopened(self, tmp_path, monkeypatch):
        receipts_dir = tmp_path / "receipts"
        log_path = "logs/example.json"
        asset_path = "images/raw/example.png"

        # Spy on os.replace to prove atomic rename path is used
        real_replace = os.replace
        replace_calls = []

        def spy_replace(src, dst):
            replace_calls.append((str(src), str(dst)))
            return real_replace(src, dst)

        monkeypatch.setattr(media_client.os, "replace", spy_replace)

        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path=log_path,
            assets=[{"path": asset_path, "kind": "image"}],
            receipts_dir=receipts_dir,
        )

        assert receipt["schema_version"] == 1
        assert receipt["run_key"] == "mediagen:run:logs/example.json"
        assert receipt["log_path"] == log_path
        assert receipt["status"] == "pending"
        assert receipt["attempts"] == 0
        assert receipt["last_error"] is None
        assert receipt["generation_run_id"] is None
        assert receipt["completed_at"] is None
        assert len(receipt["assets"]) == 1
        assert receipt["assets"][0]["path"] == asset_path
        assert receipt["assets"][0]["idempotency_key"] == "mediagen:asset:images/raw/example.png"
        assert receipt["assets"][0]["media_item_id"] is None
        assert receipt["assets"][0]["uploaded_at"] is None

        disk_path = receipts_dir / media_client.receipt_filename(receipt["run_key"])
        assert disk_path.is_file()
        assert replace_calls, "expected atomic rename via os.replace"
        assert any(c[1] == str(disk_path) for c in replace_calls)

        reopened = media_client.load_receipt(disk_path)
        assert reopened == json.loads(disk_path.read_text(encoding="utf-8"))
        assert reopened["run_key"] == receipt["run_key"]
        assert reopened["assets"][0]["media_item_id"] is None


class TestUploadMultipart:
    def test_upload_asset_sends_multipart_idempotency_and_bearer(self, tmp_path, monkeypatch):
        secret = "tok-upload-123"
        token_path = tmp_path / "token"
        token_path.write_text(secret, encoding="utf-8")
        cfg = media_client.load_config(
            {
                "MEDIA_API_URL": "https://media.example.test",
                "MEDIA_API_TOKEN_FILE": str(token_path),
            }
        )

        asset_rel = "images/raw/example.png"
        asset_abs = tmp_path / asset_rel
        asset_abs.parent.mkdir(parents=True)
        asset_bytes = b"\x89PNG\r\n\x1a\n" + b"payload-bytes"
        asset_abs.write_bytes(asset_bytes)

        captured = {}

        class FakeResponse:
            def __init__(self):
                self.status = 201
                self.headers = {"Content-Type": "application/json"}

            def read(self):
                return json.dumps({"id": "med_abcdefghijklmnopqrstu"}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["headers"] = {k: v for k, v in req.header_items()}
            captured["body"] = req.data
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(media_client.urllib.request, "urlopen", fake_urlopen)

        result = media_client.upload_asset(
            cfg,
            workspace=tmp_path,
            asset={
                "path": asset_rel,
                "kind": "image",
                "idempotency_key": "mediagen:asset:images/raw/example.png",
            },
        )

        assert result["media_item_id"] == "med_abcdefghijklmnopqrstu"
        assert captured["method"] == "POST"
        assert captured["url"] == "https://media.example.test/api/media"
        headers_l = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers_l["authorization"] == f"Bearer {secret}"
        assert headers_l["idempotency-key"] == "mediagen:asset:images/raw/example.png"
        assert headers_l["idempotency-key"]  # non-empty
        assert len(headers_l["idempotency-key"]) <= 160
        ctype = headers_l["content-type"]
        assert ctype.startswith("multipart/form-data; boundary=")
        body = captured["body"]
        assert isinstance(body, (bytes, bytearray))
        assert b'name="metadata"' in body
        assert b'name="file"' in body
        assert asset_bytes in body
        # metadata JSON includes required fields
        meta_start = body.find(b'name="metadata"')
        assert meta_start != -1
        # extract JSON object after headers of that part
        part = body[meta_start:]
        json_start = part.find(b"{")
        json_end = part.find(b"}", json_start) + 1
        metadata = json.loads(part[json_start:json_end].decode("utf-8"))
        assert metadata["kind"] == "image"
        assert metadata["origin"] == "mediagen_generation"
        assert metadata["ingested_via"] == "live_mediagen"
        assert metadata["show_in_grid"] is True

    def test_http_json_sends_non_default_user_agent(self, tmp_path, monkeypatch):
        secret = "tok-upload-123"
        token_path = tmp_path / "token"
        token_path.write_text(secret, encoding="utf-8")
        cfg = media_client.load_config(
            {
                "MEDIA_API_URL": "https://media.example.test",
                "MEDIA_API_TOKEN_FILE": str(token_path),
            }
        )

        asset_rel = "images/raw/example.png"
        asset_abs = tmp_path / asset_rel
        asset_abs.parent.mkdir(parents=True)
        asset_bytes = b"\x89PNG\r\n\x1a\n" + b"payload-bytes"
        asset_abs.write_bytes(asset_bytes)

        captured = {}

        class FakeResponse:
            def __init__(self):
                self.status = 201
                self.headers = {"Content-Type": "application/json"}

            def read(self):
                return json.dumps({"id": "med_abcdefghijklmnopqrstu"}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            captured["headers"] = {k: v for k, v in req.header_items()}
            return FakeResponse()

        monkeypatch.setattr(media_client.urllib.request, "urlopen", fake_urlopen)

        media_client.upload_asset(
            cfg,
            workspace=tmp_path,
            asset={
                "path": asset_rel,
                "kind": "image",
                "idempotency_key": "mediagen:asset:images/raw/example.png",
            },
        )

        headers_l = {k.lower(): v for k, v in captured["headers"].items()}
        assert "user-agent" in headers_l
        assert headers_l["user-agent"] == "hermes-mediagen/1.0"
        assert not headers_l["user-agent"].lower().startswith("python-urllib")


# ── helpers for sync-level tests ──────────────────────────────────────────────

def _cfg(tmp_path, secret="test-token-secret"):
    token_path = tmp_path / "token"
    token_path.write_text(secret, encoding="utf-8")
    return media_client.load_config(
        {
            "MEDIA_API_URL": "https://media.example.test",
            "MEDIA_API_TOKEN_FILE": str(token_path),
            "MEDIA_UPLOAD_TIMEOUT_SECONDS": "30",
        }
    ), secret


def _write_asset(workspace, rel="images/raw/example.png", data=b"\x89PNG\r\n\x1a\nfakeimg"):
    path = workspace / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


class _FakeHTTPResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _install_urlopen(monkeypatch, handler):
    """handler(req, timeout) -> FakeHTTPResponse | raises HTTPError/URLError/TimeoutError"""

    def fake_urlopen(req, timeout=None):
        return handler(req, timeout)

    monkeypatch.setattr(media_client.urllib.request, "urlopen", fake_urlopen)


class TestUploadStatusCodes:
    def test_http_200_and_201_save_media_item_id_on_asset(self, tmp_path, monkeypatch):
        cfg, _secret = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path)
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )

        calls = {"n": 0}

        def handler(req, timeout):
            calls["n"] += 1
            url = req.full_url
            if url.endswith("/api/media"):
                # first call 201, second (if any) 200
                status = 201 if calls["n"] == 1 else 200
                return _FakeHTTPResponse(status, {"id": "med_abcdefghijklmnopqrstu"})
            if url.endswith("/api/generation-runs"):
                return _FakeHTTPResponse(201, {"id": "run_abcdefghijklmnopqrstu"})
            raise AssertionError(f"unexpected url {url}")

        _install_urlopen(monkeypatch, handler)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "tool": "mediagen",
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "prompt": "a cat",
                "params": {},
                "status": "succeeded",
                "inputs": [],
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated["assets"][0]["media_item_id"] == "med_abcdefghijklmnopqrstu"
        assert updated["assets"][0]["uploaded_at"] is not None
        # persisted
        loaded = media_client.load_receipt(receipts_dir / media_client.receipt_filename(receipt["run_key"]))
        assert loaded["assets"][0]["media_item_id"] == "med_abcdefghijklmnopqrstu"


class TestConflict409:
    def test_http_409_marks_conflict_and_preserves_binary(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path, data=b"\x89PNG\r\n\x1a\nKEEPME")
        asset_abs = tmp_path / rel
        before = asset_abs.read_bytes()
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )

        def raising_urlopen(req, timeout=None):
            err = media_client.urllib.error.HTTPError(
                req.full_url, 409, "Conflict", hdrs=None, fp=None
            )
            err.read = lambda: b'{"error":{"code":"idempotency_conflict","message":"conflict"}}'
            raise err

        monkeypatch.setattr(media_client.urllib.request, "urlopen", raising_urlopen)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "params": {},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated["status"] == "conflict"
        assert updated["assets"][0]["media_item_id"] is None
        assert asset_abs.is_file()
        assert asset_abs.read_bytes() == before
        assert before == b"\x89PNG\r\n\x1a\nKEEPME"


class TestTransientErrors:
    def test_timeout_increments_attempts_keeps_pending(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path)
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )
        assert receipt["attempts"] == 0

        def raising_urlopen(req, timeout=None):
            raise TimeoutError("timed out")

        monkeypatch.setattr(media_client.urllib.request, "urlopen", raising_urlopen)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "params": {},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated["status"] == "pending"
        assert updated["attempts"] == 1
        assert updated["assets"][0]["media_item_id"] is None
        assert updated["last_error"]

        # second attempt
        updated2 = media_client.sync_receipt(
            cfg,
            receipt=updated,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "params": {},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated2["attempts"] == 2
        assert updated2["status"] == "pending"

    def test_5xx_increments_attempts_keeps_pending(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path)
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )

        def raising_urlopen(req, timeout=None):
            err = media_client.urllib.error.HTTPError(
                req.full_url, 503, "Service Unavailable", hdrs=None, fp=None
            )
            err.read = lambda: b'{"error":{"message":"upstream down"}}'
            raise err

        monkeypatch.setattr(media_client.urllib.request, "urlopen", raising_urlopen)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "params": {},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated["status"] == "pending"
        assert updated["attempts"] == 1
        assert (tmp_path / rel).is_file()


class TestGenerationRunOrdering:
    def test_generation_run_posted_only_after_all_asset_ids(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        out_rel = _write_asset(tmp_path, "images/raw/out.png")
        in_rel = _write_asset(tmp_path, "external/in.png", data=b"\x89PNG\r\n\x1a\nin")
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/edit.json",
            assets=[
                {"path": in_rel, "kind": "image", "origin": "external_import", "show_in_grid": False, "role": "edit_source", "position": 0},
                {"path": out_rel, "kind": "image", "role": "output", "position": 0},
            ],
            receipts_dir=receipts_dir,
        )

        events = []
        ids = {"n": 0}

        def handler(req, timeout):
            url = req.full_url
            if url.endswith("/api/media"):
                ids["n"] += 1
                mid = f"med_{'a' * 20}{ids['n']}"
                events.append(("media", mid, req.data is not None))
                # Fail second asset first time around? No — upload both then run
                return _FakeHTTPResponse(201, {"id": mid})
            if url.endswith("/api/generation-runs"):
                body = json.loads(req.data.decode("utf-8"))
                events.append(("run", body))
                # Assert both media ids present
                assert len(body["inputs"]) == 1
                assert len(body["outputs"]) == 1
                assert body["inputs"][0]["media_item_id"].startswith("med_")
                assert body["outputs"][0]["media_item_id"].startswith("med_")
                assert body["inputs"][0]["media_item_id"] != body["outputs"][0]["media_item_id"]
                return _FakeHTTPResponse(201, {"id": "run_abcdefghijklmnopqrstu"})
            raise AssertionError(url)

        _install_urlopen(monkeypatch, handler)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "edit",
                "provider": "fal",
                "model": "nano2",
                "prompt": "edit me",
                "params": {},
                "inputs": [{"path": in_rel, "role": "edit_source", "position": 0}],
                "outputs": [{"path": out_rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert [e[0] for e in events] == ["media", "media", "run"]
        assert updated["status"] == "completed"
        assert all(a["media_item_id"] for a in updated["assets"])

    def test_does_not_post_run_when_asset_still_pending(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path)
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )
        events = []

        def raising_urlopen(req, timeout=None):
            events.append(req.full_url)
            raise TimeoutError("timed out")

        monkeypatch.setattr(media_client.urllib.request, "urlopen", raising_urlopen)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "params": {},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated["status"] == "pending"
        assert all("/api/generation-runs" not in u for u in events)
        assert any("/api/media" in u for u in events)


class TestSuccessCompleted:
    def test_success_marks_receipt_completed_with_generation_run_id(self, tmp_path, monkeypatch):
        cfg, secret = _cfg(tmp_path)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path)
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )

        def handler(req, timeout):
            if req.full_url.endswith("/api/media"):
                return _FakeHTTPResponse(201, {"id": "med_abcdefghijklmnopqrstu"})
            if req.full_url.endswith("/api/generation-runs"):
                return _FakeHTTPResponse(201, {"id": "run_abcdefghijklmnopqrstu"})
            raise AssertionError(req.full_url)

        _install_urlopen(monkeypatch, handler)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "prompt": "ok",
                "params": {"width": 1280},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        assert updated["status"] == "completed"
        assert updated["generation_run_id"] == "run_abcdefghijklmnopqrstu"
        assert updated["completed_at"] is not None
        assert updated["last_error"] is None
        disk = media_client.load_receipt(receipts_dir / media_client.receipt_filename(receipt["run_key"]))
        assert disk["status"] == "completed"
        assert secret not in json.dumps(disk)


class TestErrorSanitization:
    def test_errors_sanitize_url_token_and_sensitive_body(self, tmp_path, monkeypatch):
        secret = "super-secret-bearer-ABC"
        cfg, _ = _cfg(tmp_path, secret=secret)
        receipts_dir = tmp_path / "receipts"
        rel = _write_asset(tmp_path)
        receipt = media_client.create_receipt(
            workspace=tmp_path,
            log_path="logs/example.json",
            assets=[{"path": rel, "kind": "image"}],
            receipts_dir=receipts_dir,
        )

        leaky = (
            f'Bearer {secret} failed at https://media.example.test/api/media '
            f'https://r2.example/object?X-Amz-Signature=deadbeef '
            f'{{"authorization":"{secret}","provider_body":"raw"}}'
        )

        def raising_urlopen(req, timeout=None):
            err = media_client.urllib.error.HTTPError(
                req.full_url, 500, "boom", hdrs=None, fp=None
            )
            err.read = lambda: leaky.encode("utf-8")
            raise err

        monkeypatch.setattr(media_client.urllib.request, "urlopen", raising_urlopen)

        updated = media_client.sync_receipt(
            cfg,
            receipt=receipt,
            workspace=tmp_path,
            generation={
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "params": {},
                "outputs": [{"path": rel, "position": 0}],
            },
            receipts_dir=receipts_dir,
        )
        err = updated["last_error"] or ""
        blob = json.dumps(updated)
        assert secret not in err
        assert secret not in blob
        assert "Bearer super-secret" not in err
        assert "X-Amz-Signature" not in err
        assert "X-Amz-Signature" not in blob
        assert "https://media.example.test" not in err
        # sanitize function unit checks
        cleaned = media_client.sanitize_error_text(
            leaky, token=secret, api_url="https://media.example.test"
        )
        assert secret not in cleaned
        assert "X-Amz-Signature" not in cleaned
        assert "Bearer [redacted]" in cleaned or "[redacted-token]" in cleaned

    def test_sanitize_error_text_redacts_azure_and_common_secret_params(self):
        samples = [
            (
                "https://acct.blob.core.windows.net/c/b?sv=2021-08-06&sig=SuperSecretSigValue==",
                "sig=",
            ),
            ("retry?token=abc123xyz&x=1", "token=abc123xyz"),
            ('config api_key=sk-live-abcdef password=nope', "api_key=sk-live-abcdef"),
            ("Azure SharedKey Key=ABCDEF123456 Signature=deadbeef==", "Key=ABCDEF123456"),
            ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ]
        for text, must_not_appear in samples:
            cleaned = media_client.sanitize_error_text(text)
            assert must_not_appear not in cleaned, f"leaked in {text!r} -> {cleaned!r}"
            assert "redacted" in cleaned.lower() or "[media" in cleaned.lower()

    def test_media_http_error_body_is_sanitized_or_omitted(self, tmp_path, monkeypatch):
        secret = "body-secret-token-XYZ"
        cfg, _ = _cfg(tmp_path, secret=secret)
        rel = _write_asset(tmp_path)
        leaky = (
            f"Bearer {secret} https://r2.example/o?X-Amz-Signature=deadbeef "
            f"sig=azureSecret&api_key=sk-1 Authorization: Basic dXNlcjpwYXNz"
        ).encode("utf-8")

        def raising_urlopen(req, timeout=None):
            err = media_client.urllib.error.HTTPError(
                req.full_url, 500, "boom", hdrs=None, fp=None
            )
            err.read = lambda: leaky
            raise err

        monkeypatch.setattr(media_client.urllib.request, "urlopen", raising_urlopen)

        with pytest.raises(media_client.MediaHTTPError) as ei:
            media_client.upload_asset(
                cfg,
                workspace=tmp_path,
                asset={"path": rel, "kind": "image"},
            )
        exc = ei.value
        assert secret not in exc.message
        if exc.body is None:
            return
        body_text = (
            exc.body.decode("utf-8", errors="replace")
            if isinstance(exc.body, (bytes, bytearray))
            else str(exc.body)
        )
        assert secret not in body_text
        assert "X-Amz-Signature=deadbeef" not in body_text
        assert "azureSecret" not in body_text
        assert "sk-1" not in body_text
        assert "dXNlcjpwYXNz" not in body_text


class TestWorkspacePathConfinement:
    def test_upload_rejects_absolute_path_outside_workspace(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        outside = tmp_path.parent / "outside-secret.bin"
        outside.write_bytes(b"TOPSECRET")
        called = {"n": 0}

        def boom(req, timeout=None):
            called["n"] += 1
            raise AssertionError("HTTP must not run for escaped path")

        monkeypatch.setattr(media_client.urllib.request, "urlopen", boom)

        with pytest.raises((ValueError, OSError, media_client.MediaHTTPError, RuntimeError)):
            media_client.upload_asset(
                cfg,
                workspace=tmp_path,
                asset={"path": str(outside), "kind": "image"},
            )
        assert called["n"] == 0
        assert outside.read_bytes() == b"TOPSECRET"

    def test_upload_rejects_parent_dir_escape(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "secret.bin"
        outside.write_bytes(b"ESCAPE-ME")
        called = {"n": 0}

        def boom(req, timeout=None):
            called["n"] += 1
            raise AssertionError("HTTP must not run for path escape")

        monkeypatch.setattr(media_client.urllib.request, "urlopen", boom)

        with pytest.raises((ValueError, OSError, media_client.MediaHTTPError, RuntimeError)):
            media_client.upload_asset(
                cfg,
                workspace=workspace,
                asset={"path": "../secret.bin", "kind": "image"},
            )
        assert called["n"] == 0

    def test_upload_allows_normal_relative_path(self, tmp_path, monkeypatch):
        cfg, _ = _cfg(tmp_path)
        rel = _write_asset(tmp_path, "images/raw/ok.png", data=b"\x89PNG\r\n\x1a\nok")
        captured = {}

        def handler(req, timeout=None):
            captured["body"] = req.data
            return _FakeHTTPResponse(201, {"id": "med_abcdefghijklmnopqrstu"})

        _install_urlopen(monkeypatch, handler)
        result = media_client.upload_asset(
            cfg,
            workspace=tmp_path,
            asset={"path": rel, "kind": "image"},
        )
        assert result["media_item_id"] == "med_abcdefghijklmnopqrstu"
        assert b"ok" in captured["body"]


class TestMultipartFilenameSanitization:
    def test_multipart_filename_strips_quotes_crlf_and_path_separators(self):
        import re

        helper = getattr(
            media_client,
            "sanitize_multipart_filename",
            getattr(media_client, "_sanitize_multipart_filename", None),
        )
        assert helper is not None, "expected sanitize_multipart_filename helper"

        raw = 'path/to\\evil"name\r\nX-Injected: yes.png'
        safe = helper(raw)
        assert '"' not in safe
        assert "\r" not in safe and "\n" not in safe
        assert "/" not in safe and "\\" not in safe

        body, _ = media_client._build_multipart(
            {},
            {"file": (safe, b"payload", "image/png")},
        )
        # Unsanitized would inject a second header line via CRLF
        assert b"X-Injected" not in body or b"filename=" in body
        disp = body.split(b"Content-Disposition:")[1].split(b"\r\n")[0]
        assert b"\n" not in disp and b"\r" not in disp
        m = re.search(br'filename="([^"]*)"', body)
        assert m is not None
        fname = m.group(1).decode("utf-8", errors="replace")
        assert fname == safe


class TestUploadTimeoutValidation:
    def test_non_positive_timeout_falls_back_to_default(self, tmp_path):
        token_path = tmp_path / "token"
        token_path.write_text("tok", encoding="utf-8")
        for bad in ("0", "-1", "-30"):
            cfg = media_client.load_config(
                {
                    "MEDIA_API_URL": "https://media.example.test",
                    "MEDIA_API_TOKEN_FILE": str(token_path),
                    "MEDIA_UPLOAD_TIMEOUT_SECONDS": bad,
                }
            )
            assert cfg.timeout_seconds == media_client.DEFAULT_UPLOAD_TIMEOUT_SECONDS

    def test_positive_timeout_is_honored(self, tmp_path):
        token_path = tmp_path / "token"
        token_path.write_text("tok", encoding="utf-8")
        cfg = media_client.load_config(
            {
                "MEDIA_API_URL": "https://media.example.test",
                "MEDIA_API_TOKEN_FILE": str(token_path),
                "MEDIA_UPLOAD_TIMEOUT_SECONDS": "45",
            }
        )
        assert cfg.timeout_seconds == 45
