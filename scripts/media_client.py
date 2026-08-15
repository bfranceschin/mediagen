"""Hostkit Media API client + durable local receipts for mediagen.

stdlib-only HTTP (urllib). Never persist bearer tokens, credentials, provider
secrets, or signed URLs into receipts or logs.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.request import Request


DEFAULT_RECEIPTS_DIR_NAME = "receipts"
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 180
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MediaConfig:
    enabled: bool
    api_url: Optional[str] = None
    token: Optional[str] = None
    timeout_seconds: int = DEFAULT_UPLOAD_TIMEOUT_SECONDS
    receipts_dir: Optional[Path] = None


def load_config(env: Optional[Mapping[str, str]] = None) -> MediaConfig:
    """Load Media sync config from environment. Missing pieces disable sync."""
    env = env if env is not None else os.environ
    api_url = (env.get("MEDIA_API_URL") or "").strip().rstrip("/")
    token_file = (env.get("MEDIA_API_TOKEN_FILE") or "").strip()
    timeout_raw = (env.get("MEDIA_UPLOAD_TIMEOUT_SECONDS") or "").strip()
    try:
        timeout_seconds = int(timeout_raw) if timeout_raw else DEFAULT_UPLOAD_TIMEOUT_SECONDS
    except ValueError:
        timeout_seconds = DEFAULT_UPLOAD_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        timeout_seconds = DEFAULT_UPLOAD_TIMEOUT_SECONDS

    if not api_url or not token_file:
        return MediaConfig(enabled=False, timeout_seconds=timeout_seconds)

    path = Path(os.path.expanduser(token_file))
    if not path.is_file():
        return MediaConfig(enabled=False, api_url=api_url, timeout_seconds=timeout_seconds)

    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return MediaConfig(enabled=False, api_url=api_url, timeout_seconds=timeout_seconds)

    if not token:
        return MediaConfig(enabled=False, api_url=api_url, timeout_seconds=timeout_seconds)

    return MediaConfig(
        enabled=True,
        api_url=api_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )


def asset_idempotency_key(rel_path: str) -> str:
    return f"mediagen:asset:{rel_path}"


def run_idempotency_key(log_path: str) -> str:
    return f"mediagen:run:{log_path}"


def receipt_filename(run_key: str) -> str:
    """Stable on-disk name for a run key (filesystem-safe)."""
    safe = run_key.replace(":", "__").replace("/", "__")
    return f"{safe}.json"


def default_receipts_dir(workspace: Path | str) -> Path:
    return Path(workspace) / DEFAULT_RECEIPTS_DIR_NAME


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def save_receipt(receipt: dict[str, Any], receipts_dir: Path | str) -> Path:
    """Write receipt atomically (tempfile + rename). Never stores secrets."""
    receipts_dir = Path(receipts_dir)
    path = receipts_dir / receipt_filename(receipt["run_key"])
    payload = json.loads(json.dumps(receipt))
    _atomic_write_json(path, payload)
    return path


def load_receipt(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def create_receipt(
    *,
    workspace: Path | str,
    log_path: str,
    assets: list[dict[str, Any]],
    receipts_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Create and persist a pending receipt for a generation run."""
    workspace = Path(workspace)
    receipts_dir = Path(receipts_dir) if receipts_dir is not None else default_receipts_dir(workspace)
    run_key = run_idempotency_key(log_path)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_key": run_key,
        "log_path": log_path,
        "status": "pending",
        "attempts": 0,
        "last_error": None,
        "assets": [
            {
                "path": a["path"],
                "idempotency_key": a.get("idempotency_key") or asset_idempotency_key(a["path"]),
                "media_item_id": None,
                "uploaded_at": None,
                **({"kind": a["kind"]} if "kind" in a else {}),
                **({"role": a["role"]} if "role" in a else {}),
                **({"position": a["position"]} if "position" in a else {}),
                **({"show_in_grid": a["show_in_grid"]} if "show_in_grid" in a else {}),
                **({"origin": a["origin"]} if "origin" in a else {}),
            }
            for a in assets
        ],
        "generation_run_id": None,
        "completed_at": None,
    }
    save_receipt(receipt, receipts_dir)
    return receipt


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def sanitize_multipart_filename(filename: str) -> str:
    """Basename only; strip quotes, CRLF, and path separators for Content-Disposition."""
    name = Path(str(filename).replace("\\", "/")).name
    name = name.replace('"', "").replace("'", "")
    name = name.replace("\r", "").replace("\n", "")
    name = name.replace("/", "").replace("\\", "")
    name = name.strip() or "upload.bin"
    return name


def _build_multipart(
    fields: dict[str, Any],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Build multipart/form-data body. files: name -> (filename, content, content_type)."""
    boundary = f"----mediagen{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        if isinstance(value, (dict, list)):
            payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
            ctype = "application/json"
        else:
            payload = str(value).encode("utf-8")
            ctype = "text/plain; charset=utf-8"
        lines.append(f"--{boundary}\r\n".encode("ascii"))
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n'.encode("utf-8"))
        lines.append(f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
        lines.append(payload)
        lines.append(b"\r\n")
    for name, (filename, content, content_type) in files.items():
        safe_name = sanitize_multipart_filename(filename)
        lines.append(f"--{boundary}\r\n".encode("ascii"))
        lines.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{safe_name}"\r\n'
            ).encode("utf-8")
        )
        lines.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        lines.append(content)
        lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("ascii"))
    body = b"".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


class MediaHTTPError(Exception):
    """HTTP error from Media API with status and sanitized message."""

    def __init__(self, status: int, message: str, *, body: bytes | str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        # Never expose raw provider bodies that may contain secrets.
        self.body = body


def sanitize_error_text(
    text: str,
    *,
    token: str | None = None,
    api_url: str | None = None,
) -> str:
    """Strip bearer tokens, signed URLs, and raw secrets from error strings."""
    if not text:
        return text
    out = text
    if token:
        out = out.replace(token, "[redacted-token]")
    out = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]+", "Bearer [redacted]", out)
    out = re.sub(
        r"(?i)authorization\s*:\s*basic\s+[A-Za-z0-9+/=\s]+",
        "Authorization: Basic [redacted]",
        out,
    )
    # Full URLs carrying AWS/Azure/query secrets
    out = re.sub(
        r"https?://[^\s\"']+(?:X-Amz-|Signature=|signature=|sig=|token=|api_key=)[^\s\"']*",
        "[redacted-signed-url]",
        out,
        flags=re.IGNORECASE,
    )
    # Bare query/form-style secret parameters (not only inside full URLs)
    out = re.sub(
        r"(?i)(?:\?|&|\s)(sig|token|api_key|access_key)=([^\s\"'&]+)",
        lambda m: f"{m.group(0)[:1]}{m.group(1)}=[redacted]",
        out,
    )
    out = re.sub(
        r"(?i)(?<![A-Za-z0-9_])(Key|Signature)=([^\s\"'&]+)",
        r"\1=[redacted]",
        out,
    )
    if api_url:
        out = out.replace(api_url, "[media-api]")
    out = re.sub(
        r'(?i)("?(?:authorization|access_key|secret|password|api_key|token)"?\s*[:=]\s*")([^"]+)(")',
        r"\1[redacted]\3",
        out,
    )
    out = re.sub(
        r"(?i)\b(api_key|token)\s*[:=]\s*([^\s\"',}]+)",
        r"\1=[redacted]",
        out,
    )
    return out


def _resolve_workspace_file(workspace: Path, rel: str) -> Path:
    """Resolve asset path and require it stays inside workspace. Fail closed."""
    workspace_resolved = Path(workspace).resolve()
    candidate = Path(rel)
    if candidate.is_absolute():
        file_path = candidate.resolve()
    else:
        file_path = (workspace_resolved / candidate).resolve()
    try:
        file_path.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(
            f"asset path escapes workspace: {rel!r}"
        ) from exc
    return file_path


def _http_json(
    cfg: MediaConfig,
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: Optional[dict[str, str]] = None,
    content_type: str | None = None,
) -> tuple[int, Any]:
    assert cfg.api_url and cfg.token
    url = f"{cfg.api_url.rstrip('/')}{path}"
    hdrs = {
        "Authorization": f"Bearer {cfg.token}",
        "Accept": "application/json",
    }
    if content_type:
        hdrs["Content-Type"] = content_type
    if headers:
        hdrs.update(headers)
    req = Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
            raw = resp.read()
            status = getattr(resp, "status", None) or resp.getcode()
            if not raw:
                return status, None
            try:
                return status, json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                sanitized = sanitize_error_text(
                    raw.decode("utf-8", errors="replace"),
                    token=cfg.token,
                    api_url=cfg.api_url,
                )
                return status, {"raw": sanitized}
    except urllib.error.HTTPError as exc:
        err_body = b""
        try:
            err_body = exc.read() if hasattr(exc, "read") else b""
        except Exception:  # noqa: BLE001 — body is best-effort for sanitization only
            err_body = b""
        raw_msg = err_body.decode("utf-8", errors="replace") if err_body else str(exc.reason)
        msg = sanitize_error_text(raw_msg, token=cfg.token, api_url=cfg.api_url)
        # Store only sanitized body (or omit) so callers never persist secrets.
        safe_body = msg.encode("utf-8") if msg else None
        raise MediaHTTPError(exc.code, msg, body=safe_body) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise MediaHTTPError(0, "timeout") from None
        msg = sanitize_error_text(str(reason), token=cfg.token, api_url=cfg.api_url)
        raise MediaHTTPError(0, f"network error: {msg}") from None
    except TimeoutError:
        raise MediaHTTPError(0, "timeout") from None


def upload_asset(
    cfg: MediaConfig,
    *,
    workspace: Path | str,
    asset: dict[str, Any],
) -> dict[str, Any]:
    """POST one asset to /api/media. Returns dict with media_item_id on success."""
    if not cfg.enabled or not cfg.api_url or not cfg.token:
        raise RuntimeError("Media sync is not enabled")

    workspace = Path(workspace)
    rel = asset["path"]
    file_path = _resolve_workspace_file(workspace, rel)
    file_bytes = file_path.read_bytes()
    filename = sanitize_multipart_filename(Path(rel).name)
    content_type = _guess_content_type(file_path)

    kind = asset.get("kind") or ("video" if rel.startswith("videos/") else "image")
    origin = asset.get("origin") or "mediagen_generation"
    ingested_via = asset.get("ingested_via") or "live_mediagen"
    show_in_grid = asset.get("show_in_grid")
    if show_in_grid is None:
        show_in_grid = origin != "external_import"

    metadata: dict[str, Any] = {
        "kind": kind,
        "origin": origin,
        "ingested_via": ingested_via,
        "show_in_grid": bool(show_in_grid),
    }
    if asset.get("source_url"):
        metadata["source_url"] = asset["source_url"]
    if asset.get("source_created_at"):
        metadata["source_created_at"] = asset["source_created_at"]

    idem = asset.get("idempotency_key") or asset_idempotency_key(rel)
    if len(idem) > 160:
        idem = idem[:160]

    body, multipart_ctype = _build_multipart(
        {"metadata": metadata},
        {"file": (filename, file_bytes, content_type)},
    )

    status, data = _http_json(
        cfg,
        method="POST",
        path="/api/media",
        body=body,
        headers={"Idempotency-Key": idem},
        content_type=multipart_ctype,
    )
    if status not in (200, 201):
        raise MediaHTTPError(status, f"unexpected status {status}")
    if not isinstance(data, dict) or "id" not in data:
        raise MediaHTTPError(status, "missing media item id in response")
    return {
        "media_item_id": data["id"],
        "status": status,
        "uploaded_at": _utc_now_iso(),
    }


def post_generation_run(
    cfg: MediaConfig,
    *,
    receipt: dict[str, Any],
    generation: dict[str, Any],
) -> dict[str, Any]:
    """POST /api/generation-runs after all asset IDs are known."""
    if not cfg.enabled or not cfg.api_url or not cfg.token:
        raise RuntimeError("Media sync is not enabled")

    by_path = {a["path"]: a for a in receipt["assets"]}

    def resolve_ref(ref: dict[str, Any]) -> dict[str, Any]:
        if "media_item_id" in ref and ref["media_item_id"]:
            mid = ref["media_item_id"]
        else:
            path = ref.get("path")
            if not path or path not in by_path or not by_path[path].get("media_item_id"):
                raise MediaHTTPError(0, f"missing media_item_id for ref {ref!r}")
            mid = by_path[path]["media_item_id"]
        out: dict[str, Any] = {"media_item_id": mid, "position": int(ref.get("position", 0))}
        if "role" in ref:
            out["role"] = ref["role"]
        return out

    inputs = [resolve_ref(i) for i in generation.get("inputs") or []]
    # outputs schema has no role
    outputs = []
    for o in generation.get("outputs") or []:
        resolved = resolve_ref(o)
        outputs.append({"media_item_id": resolved["media_item_id"], "position": resolved["position"]})

    payload: dict[str, Any] = {
        "idempotency_key": receipt["run_key"],
        "tool": generation.get("tool") or "mediagen",
        "operation": generation["operation"],
        "provider": generation["provider"],
        "model": generation["model"],
        "prompt": generation.get("prompt"),
        "seed": generation.get("seed"),
        "params": generation.get("params") if generation.get("params") is not None else {},
        "status": generation.get("status") or "succeeded",
        "inputs": inputs,
        "outputs": outputs,
    }
    if "provider_result" in generation:
        payload["provider_result"] = generation["provider_result"]
    if "cost_usd" in generation:
        payload["cost_usd"] = generation["cost_usd"]
    if "error" in generation:
        payload["error"] = generation["error"]
    if "started_at" in generation:
        payload["started_at"] = generation["started_at"]
    if "completed_at" in generation:
        payload["completed_at"] = generation["completed_at"]

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    status, data = _http_json(
        cfg,
        method="POST",
        path="/api/generation-runs",
        body=body,
        content_type="application/json",
    )
    if status not in (200, 201):
        raise MediaHTTPError(status, f"unexpected status {status}")
    if not isinstance(data, dict) or "id" not in data:
        raise MediaHTTPError(status, "missing generation run id in response")
    return {"generation_run_id": data["id"], "status": status}


def _all_assets_uploaded(receipt: dict[str, Any]) -> bool:
    assets = receipt.get("assets") or []
    if not assets:
        return False
    return all(a.get("media_item_id") for a in assets)


def sync_receipt(
    cfg: MediaConfig,
    *,
    receipt: dict[str, Any],
    workspace: Path | str,
    generation: dict[str, Any],
    receipts_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Upload pending assets then post generation run. Updates receipt on disk."""
    if not cfg.enabled:
        return receipt

    workspace = Path(workspace)
    receipts_dir = Path(receipts_dir) if receipts_dir is not None else default_receipts_dir(workspace)
    receipt = json.loads(json.dumps(receipt))  # deep copy
    receipt["attempts"] = int(receipt.get("attempts") or 0) + 1

    try:
        for asset in receipt["assets"]:
            if asset.get("media_item_id"):
                continue
            try:
                result = upload_asset(cfg, workspace=workspace, asset=asset)
            except MediaHTTPError as exc:
                if exc.status == 409:
                    receipt["status"] = "conflict"
                    receipt["last_error"] = sanitize_error_text(
                        exc.message, token=cfg.token, api_url=cfg.api_url
                    )
                    save_receipt(receipt, receipts_dir)
                    return receipt
                if exc.status == 0 or exc.status >= 500 or exc.status in (408, 429):
                    receipt["status"] = "pending"
                    receipt["last_error"] = sanitize_error_text(
                        exc.message, token=cfg.token, api_url=cfg.api_url
                    )
                    save_receipt(receipt, receipts_dir)
                    return receipt
                # Permanent client errors (except 409 handled above)
                if exc.status in (400, 401, 403, 404, 422):
                    receipt["status"] = "failed"
                    receipt["last_error"] = sanitize_error_text(
                        exc.message, token=cfg.token, api_url=cfg.api_url
                    )
                    save_receipt(receipt, receipts_dir)
                    return receipt
                # other 4xx — keep pending for retry
                receipt["status"] = "pending"
                receipt["last_error"] = sanitize_error_text(
                    exc.message, token=cfg.token, api_url=cfg.api_url
                )
                save_receipt(receipt, receipts_dir)
                return receipt

            asset["media_item_id"] = result["media_item_id"]
            asset["uploaded_at"] = result["uploaded_at"]
            save_receipt(receipt, receipts_dir)

        if not _all_assets_uploaded(receipt):
            receipt["status"] = "pending"
            save_receipt(receipt, receipts_dir)
            return receipt

        try:
            run_result = post_generation_run(cfg, receipt=receipt, generation=generation)
        except MediaHTTPError as exc:
            if exc.status == 409:
                receipt["status"] = "conflict"
            else:
                receipt["status"] = "pending"
            receipt["last_error"] = sanitize_error_text(
                exc.message, token=cfg.token, api_url=cfg.api_url
            )
            save_receipt(receipt, receipts_dir)
            return receipt

        receipt["generation_run_id"] = run_result["generation_run_id"]
        receipt["status"] = "completed"
        receipt["completed_at"] = _utc_now_iso()
        receipt["last_error"] = None
        save_receipt(receipt, receipts_dir)
        return receipt
    except Exception as exc:  # noqa: BLE001 — durable pending + sanitized error
        receipt["status"] = "pending"
        receipt["last_error"] = sanitize_error_text(
            str(exc), token=cfg.token, api_url=cfg.api_url
        )
        save_receipt(receipt, receipts_dir)
        return receipt


def sync_if_enabled(
    cfg: MediaConfig,
    *,
    workspace: Path | str,
    log_path: str,
    assets: list[dict[str, Any]],
    generation: dict[str, Any],
    receipts_dir: Path | str | None = None,
) -> Optional[dict[str, Any]]:
    """Create receipt and attempt one Media sync if configured."""
    if not cfg.enabled:
        return None
    workspace = Path(workspace)
    receipts_dir = Path(receipts_dir) if receipts_dir is not None else default_receipts_dir(workspace)
    receipt = create_receipt(
        workspace=workspace,
        log_path=log_path,
        assets=assets,
        receipts_dir=receipts_dir,
    )
    return sync_receipt(
        cfg,
        receipt=receipt,
        workspace=workspace,
        generation=generation,
        receipts_dir=receipts_dir,
    )
