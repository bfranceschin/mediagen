"""F4: media_sync retry + 7-day prune. Mock media_client HTTP; tmp workspaces only."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import media_client
import media_sync


def _utc(days_ago: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _setup_ws(ws: Path) -> Path:
    for d in (
        ws / "images" / "raw",
        ws / "videos" / "raw",
        ws / "external",
        ws / "logs",
        ws / "receipts",
    ):
        d.mkdir(parents=True, exist_ok=True)
    return ws


def _write_bin(ws: Path, rel: str, data: bytes = b"\x89PNG\r\nfake") -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _write_log(ws: Path, name: str = "run.json", **extra) -> str:
    rel = f"logs/{name}"
    payload = {
        "filename": name.replace(".json", ".png"),
        "prompt": "p",
        "model": "fal-ai/flux-2",
        "mode": "generate",
        "seed": 1,
        "timestamp": _utc(0),
        "inputs": [],
        **extra,
    }
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return rel


def _save_receipt(ws: Path, receipt: dict) -> Path:
    rd = ws / "receipts"
    rd.mkdir(parents=True, exist_ok=True)
    return media_client.save_receipt(receipt, rd)


def _pending_receipt(ws: Path, *, log_name: str, assets: list[dict], generation: dict | None = None) -> dict:
    log_path = _write_log(ws, log_name)
    clean: list[dict] = []
    for raw in assets:
        a = {k: v for k, v in raw.items() if not k.startswith("_")}
        data = raw.get("_data", b"\x89PNG\r\nfake")
        _write_bin(ws, a["path"], data)
        clean.append(a)
    receipt = media_client.create_receipt(
        workspace=ws,
        log_path=log_path,
        assets=clean,
        receipts_dir=ws / "receipts",
    )
    if generation is not None:
        receipt["generation"] = generation
        media_client.save_receipt(receipt, ws / "receipts")
    return receipt


def _completed_receipt(
    ws: Path,
    *,
    log_name: str,
    assets: list[dict],
    uploaded_days_ago: float,
) -> dict:
    log_path = _write_log(ws, log_name)
    out_assets = []
    for i, raw in enumerate(assets):
        a = {k: v for k, v in raw.items() if not k.startswith("_")}
        data = raw.get("_data", b"\x89PNG\r\nfake")
        _write_bin(ws, a["path"], data)
        out_assets.append(
            {
                **a,
                "idempotency_key": a.get("idempotency_key")
                or media_client.asset_idempotency_key(a["path"]),
                "media_item_id": a.get("media_item_id") or f"med_{i:021d}"[:25],
                "uploaded_at": a.get("uploaded_at") or _utc(uploaded_days_ago),
            }
        )
    receipt = {
        "schema_version": 1,
        "run_key": media_client.run_idempotency_key(log_path),
        "log_path": log_path,
        "status": "completed",
        "attempts": 1,
        "last_error": None,
        "assets": out_assets,
        "generation_run_id": "run_abcdefghijklmnopqrstu",
        "completed_at": _utc(uploaded_days_ago),
    }
    _save_receipt(ws, receipt)
    return receipt


class TestRetryPendingOnly:
    def test_retry_only_calls_sync_for_pending(self, tmp_path, monkeypatch):
        ws = _setup_ws(tmp_path / "ws")
        token = tmp_path / "token"
        token.write_text("tok\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", "https://media.example.test")
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))

        pending = _pending_receipt(
            ws,
            log_name="pending.json",
            assets=[{"path": "images/raw/pending.png", "kind": "image"}],
            generation={
                "tool": "mediagen",
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "prompt": "p",
                "params": {"endpoint": "fal-ai/flux-2"},
                "status": "succeeded",
                "inputs": [],
                "outputs": [{"path": "images/raw/pending.png", "position": 0}],
            },
        )
        completed = _completed_receipt(
            ws,
            log_name="done.json",
            assets=[{"path": "images/raw/done.png", "kind": "image"}],
            uploaded_days_ago=1,
        )

        calls: list[dict] = []

        def fake_sync(cfg, *, receipt, workspace, generation, receipts_dir=None):
            calls.append({"status": receipt["status"], "run_key": receipt["run_key"]})
            receipt = dict(receipt)
            receipt["status"] = "completed"
            receipt["attempts"] = int(receipt.get("attempts") or 0) + 1
            media_client.save_receipt(receipt, receipts_dir or (Path(workspace) / "receipts"))
            return receipt

        monkeypatch.setattr(media_client, "sync_receipt", fake_sync)
        monkeypatch.setattr(media_sync, "sync_receipt", fake_sync)

        result = media_sync.cmd_retry(workspace=ws)
        assert result["retried"] == 1
        assert result["skipped"] >= 1
        assert len(calls) == 1
        assert calls[0]["run_key"] == pending["run_key"]
        assert calls[0]["status"] == "pending"
        # completed still completed on disk
        loaded = media_client.load_receipt(
            ws / "receipts" / media_client.receipt_filename(completed["run_key"])
        )
        assert loaded["status"] == "completed"

    def test_completed_is_noop_even_with_http(self, tmp_path, monkeypatch):
        ws = _setup_ws(tmp_path / "ws")
        token = tmp_path / "token"
        token.write_text("tok\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", "https://media.example.test")
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))

        _completed_receipt(
            ws,
            log_name="only.json",
            assets=[{"path": "images/raw/only.png", "kind": "image"}],
            uploaded_days_ago=2,
        )

        http = MagicMock(side_effect=AssertionError("HTTP must not be called for completed"))
        monkeypatch.setattr(media_client.urllib.request, "urlopen", http)

        result = media_sync.cmd_retry(workspace=ws)
        assert result["retried"] == 0
        assert result["skipped"] == 1
        http.assert_not_called()

    def test_retry_rebuilds_generation_from_log_when_missing(self, tmp_path, monkeypatch):
        ws = _setup_ws(tmp_path / "ws")
        token = tmp_path / "token"
        token.write_text("tok\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", "https://media.example.test")
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))

        receipt = _pending_receipt(
            ws,
            log_name="nogen.json",
            assets=[{"path": "images/raw/nogen.png", "kind": "image"}],
            generation=None,
        )
        assert "generation" not in media_client.load_receipt(
            ws / "receipts" / media_client.receipt_filename(receipt["run_key"])
        )

        seen = {}

        def fake_sync(cfg, *, receipt, workspace, generation, receipts_dir=None):
            seen["generation"] = generation
            receipt = dict(receipt)
            receipt["status"] = "completed"
            media_client.save_receipt(receipt, receipts_dir or (Path(workspace) / "receipts"))
            return receipt

        monkeypatch.setattr(media_client, "sync_receipt", fake_sync)
        monkeypatch.setattr(media_sync, "sync_receipt", fake_sync)

        media_sync.cmd_retry(workspace=ws)
        assert seen["generation"]["operation"] == "generate"
        assert seen["generation"]["prompt"] == "p"
        assert seen["generation"]["outputs"][0]["path"] == "images/raw/nogen.png"


class TestPruneRules:
    def test_prune_removes_old_completed_binary_apply(self, tmp_path):
        ws = _setup_ws(tmp_path / "ws")
        rel = "images/raw/old.png"
        _completed_receipt(
            ws,
            log_name="old.json",
            assets=[{"path": rel, "kind": "image"}],
            uploaded_days_ago=10,
        )
        assert (ws / rel).is_file()

        result = media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert not (ws / rel).is_file()
        assert rel in result["removed"]
        # receipt preserved
        assert list((ws / "receipts").glob("*.json"))
        assert (ws / "logs" / "old.json").is_file()

    def test_prune_dry_run_does_not_remove(self, tmp_path):
        ws = _setup_ws(tmp_path / "ws")
        rel = "images/raw/old.png"
        _completed_receipt(
            ws,
            log_name="old.json",
            assets=[{"path": rel, "kind": "image"}],
            uploaded_days_ago=10,
        )
        result = media_sync.cmd_prune(workspace=ws, days=7, apply=False)
        assert (ws / rel).is_file()
        assert rel in result["would_remove"]
        assert result["removed"] == []

    def test_never_removes_logs_or_receipts_dirs(self, tmp_path):
        ws = _setup_ws(tmp_path / "ws")
        _completed_receipt(
            ws,
            log_name="x.json",
            assets=[{"path": "images/raw/x.png", "kind": "image"}],
            uploaded_days_ago=30,
        )
        media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert (ws / "logs").is_dir()
        assert (ws / "receipts").is_dir()
        assert list((ws / "logs").glob("*.json"))
        assert list((ws / "receipts").glob("*.json"))
        # must never target logs/receipts as removable asset paths
        result = media_sync.cmd_prune(workspace=ws, days=0, apply=True)
        for path in result.get("removed", []) + result.get("would_remove", []):
            assert not path.startswith("logs/")
            assert not path.startswith("receipts/")

    def test_never_removes_pending_or_conflict_binaries(self, tmp_path):
        ws = _setup_ws(tmp_path / "ws")
        pend_rel = "images/raw/pend.png"
        conf_rel = "images/raw/conf.png"
        _pending_receipt(
            ws,
            log_name="pend.json",
            assets=[{"path": pend_rel, "kind": "image"}],
        )
        conf = _pending_receipt(
            ws,
            log_name="conf.json",
            assets=[{"path": conf_rel, "kind": "image"}],
        )
        conf["status"] = "conflict"
        conf["last_error"] = "conflict"
        conf["assets"][0]["uploaded_at"] = _utc(30)
        media_client.save_receipt(conf, ws / "receipts")

        media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert (ws / pend_rel).is_file()
        assert (ws / conf_rel).is_file()

    def test_shared_external_removed_only_when_every_receipt_complete_and_old(self, tmp_path):
        ws = _setup_ws(tmp_path / "ws")
        ext = "external/shared.png"
        out_a = "images/raw/a.png"
        out_b = "images/raw/b.png"

        # Receipt A: completed long ago, references shared external + output
        _completed_receipt(
            ws,
            log_name="a.json",
            assets=[
                {
                    "path": ext,
                    "kind": "image",
                    "origin": "external_import",
                    "role": "edit_source",
                    "position": 0,
                    "_data": b"shared-bytes",
                },
                {"path": out_a, "kind": "image", "_data": b"out-a"},
            ],
            uploaded_days_ago=14,
        )
        # Receipt B: still pending, same external
        _pending_receipt(
            ws,
            log_name="b.json",
            assets=[
                {
                    "path": ext,
                    "kind": "image",
                    "origin": "external_import",
                    "role": "edit_source",
                    "position": 0,
                    "_data": b"shared-bytes",
                },
                {"path": out_b, "kind": "image", "_data": b"out-b"},
            ],
        )

        media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        # shared external kept because pending receipt still references it
        assert (ws / ext).is_file()
        # completed output may be removed (old + complete)
        assert not (ws / out_a).is_file()
        # pending output kept
        assert (ws / out_b).is_file()

        # Complete B as old → external becomes eligible
        b_path = ws / "receipts" / media_client.receipt_filename(
            media_client.run_idempotency_key("logs/b.json")
        )
        b = media_client.load_receipt(b_path)
        b["status"] = "completed"
        b["completed_at"] = _utc(14)
        b["generation_run_id"] = "run_bbbbbbbbbbbbbbbbbbbbb"
        for a in b["assets"]:
            a["media_item_id"] = a.get("media_item_id") or "med_bbbbbbbbbbbbbbbbbbbbb"
            a["uploaded_at"] = _utc(14)
        media_client.save_receipt(b, ws / "receipts")

        media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert not (ws / ext).is_file()
        assert not (ws / out_b).is_file()

    def test_recent_completed_within_window_preserved(self, tmp_path):
        """7-day window is the conservative Telegram stand-in (no delivery ack)."""
        ws = _setup_ws(tmp_path / "ws")
        rel = "images/raw/recent.png"
        _completed_receipt(
            ws,
            log_name="recent.json",
            assets=[{"path": rel, "kind": "image"}],
            uploaded_days_ago=1,
        )
        media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert (ws / rel).is_file()

    def test_default_days_from_media_cache_days_env(self, tmp_path, monkeypatch):
        ws = _setup_ws(tmp_path / "ws")
        monkeypatch.delenv("MEDIA_CACHE_DAYS", raising=False)
        assert media_sync.default_cache_days() == 7
        monkeypatch.setenv("MEDIA_CACHE_DAYS", "3")
        assert media_sync.default_cache_days() == 3

        rel = "images/raw/mid.png"
        _completed_receipt(
            ws,
            log_name="mid.json",
            assets=[{"path": rel, "kind": "image"}],
            uploaded_days_ago=5,
        )
        # default from env=3 → 5 days old is past cutoff
        media_sync.cmd_prune(workspace=ws, days=None, apply=True)
        assert not (ws / rel).is_file()


class TestPruneSymlinkProtection:
    def test_prune_refuses_symlink_into_logs(self, tmp_path):
        """In-workspace symlink to logs/ must not delete the log target."""
        ws = _setup_ws(tmp_path / "ws")
        log_rel = "logs/precious.json"
        log_path = ws / log_rel
        log_path.write_text('{"keep": true}', encoding="utf-8")

        link_rel = "images/raw/trap.png"
        # Write receipt against a real binary first, then swap in the trap symlink.
        _completed_receipt(
            ws,
            log_name="trap.json",
            assets=[{"path": link_rel, "kind": "image"}],
            uploaded_days_ago=30,
        )
        link_path = ws / link_rel
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        # Restore pristine log content in case setup touched anything else.
        log_path.write_text('{"keep": true}', encoding="utf-8")
        link_path.symlink_to(log_path)
        assert link_path.is_symlink()
        assert log_path.is_file()

        result = media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert log_path.is_file()
        assert log_path.read_text(encoding="utf-8") == '{"keep": true}'
        # Symlink itself must not be unlinked either (refuse symlinks).
        assert link_path.is_symlink()
        assert link_rel not in result.get("removed", [])
        assert link_rel not in result.get("would_remove", [])

    def test_prune_refuses_symlink_outside_workspace(self, tmp_path):
        """Symlink pointing outside workspace must keep the external target."""
        ws = _setup_ws(tmp_path / "ws")
        outside = tmp_path / "outside_secret.bin"
        outside.write_bytes(b"do-not-delete")

        link_rel = "images/raw/escape.png"
        _completed_receipt(
            ws,
            log_name="escape.json",
            assets=[{"path": link_rel, "kind": "image"}],
            uploaded_days_ago=30,
        )
        link_path = ws / link_rel
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        outside.write_bytes(b"do-not-delete")
        link_path.symlink_to(outside)

        result = media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert outside.is_file()
        assert outside.read_bytes() == b"do-not-delete"
        assert link_path.is_symlink()
        assert link_rel not in result.get("removed", [])
        assert link_rel not in result.get("would_remove", [])

    def test_prune_refuses_symlink_into_receipts(self, tmp_path):
        ws = _setup_ws(tmp_path / "ws")
        # Seed a completed receipt first so receipts/ has a real file.
        _completed_receipt(
            ws,
            log_name="seed.json",
            assets=[{"path": "images/raw/seed.png", "kind": "image"}],
            uploaded_days_ago=30,
        )
        receipt_files = list((ws / "receipts").glob("*.json"))
        assert receipt_files
        target = receipt_files[0]
        before = target.read_text(encoding="utf-8")

        link_rel = "videos/raw/trap.mp4"
        _completed_receipt(
            ws,
            log_name="trap-r.json",
            assets=[{"path": link_rel, "kind": "video"}],
            uploaded_days_ago=30,
        )
        link_path = ws / link_rel
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        # Ensure seed receipt content was not clobbered during second write.
        target.write_text(before, encoding="utf-8")
        link_path.symlink_to(target)

        media_sync.cmd_prune(workspace=ws, days=7, apply=True)
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == before
        assert link_path.is_symlink()


class TestRetryErrorSanitization:
    def test_retry_errors_redact_token_and_url(self, tmp_path, monkeypatch):
        ws = _setup_ws(tmp_path / "ws")
        secret = "super-secret-media-token-xyz"
        api_url = "https://media.example.test/v1"
        token = tmp_path / "token"
        token.write_text(secret + "\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", api_url)
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))

        _pending_receipt(
            ws,
            log_name="leak.json",
            assets=[{"path": "images/raw/leak.png", "kind": "image"}],
            generation={
                "tool": "mediagen",
                "operation": "generate",
                "provider": "fal",
                "model": "flux2",
                "prompt": "p",
                "params": {"endpoint": "fal-ai/flux-2"},
                "status": "succeeded",
                "inputs": [],
                "outputs": [{"path": "images/raw/leak.png", "position": 0}],
            },
        )

        def boom(cfg, *, receipt, workspace, generation, receipts_dir=None):
            raise RuntimeError(
                f"upload failed Authorization: Bearer {secret} via {api_url}/assets"
                f" signed=https://cdn.example/x?token={secret}&sig=abc"
            )

        monkeypatch.setattr(media_client, "sync_receipt", boom)
        monkeypatch.setattr(media_sync, "sync_receipt", boom)

        result = media_sync.cmd_retry(workspace=ws)
        assert result["errors"]
        blob = "\n".join(result["errors"])
        assert secret not in blob
        assert api_url not in blob
        assert "Bearer [redacted]" in blob or "[redacted-token]" in blob
        # CLI path also sanitizes printed JSON
        rc = media_sync.main(["retry", "--workspace", str(ws)])
        assert rc != 0


class TestCLI:
    def test_cli_retry_and_prune_args(self, tmp_path, monkeypatch, capsys):
        ws = _setup_ws(tmp_path / "ws")
        token = tmp_path / "token"
        token.write_text("tok\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", "https://media.example.test")
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))

        _completed_receipt(
            ws,
            log_name="cli.json",
            assets=[{"path": "images/raw/cli.png", "kind": "image"}],
            uploaded_days_ago=20,
        )

        rc = media_sync.main(["retry", "--workspace", str(ws)])
        assert rc == 0

        rc = media_sync.main(["prune", "--workspace", str(ws), "--days", "7", "--dry-run"])
        assert rc == 0
        assert (ws / "images" / "raw" / "cli.png").is_file()

        rc = media_sync.main(["prune", "--workspace", str(ws), "--days", "7", "--apply"])
        assert rc == 0
        assert not (ws / "images" / "raw" / "cli.png").is_file()

    def test_cli_missing_workspace_exits_nonzero(self, tmp_path, capsys):
        missing = tmp_path / "does-not-exist"
        assert not missing.exists()

        rc = media_sync.main(["retry", "--workspace", str(missing)])
        assert rc != 0

        rc = media_sync.main(
            ["prune", "--workspace", str(missing), "--days", "7", "--dry-run"]
        )
        assert rc != 0
