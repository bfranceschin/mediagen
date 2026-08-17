#!/usr/bin/env python3
"""media_sync.py — Retry pending Media receipts + prune local binary cache.

CLI:
  python scripts/media_sync.py retry --workspace ~/.hermes/workspace/mediagen
  python scripts/media_sync.py prune --days 7 --dry-run
  python scripts/media_sync.py prune --days 7 --apply

Prune policy (MVP-0):
  - Only remove a binary when every receipt that references it is ``completed``
    and that asset's ``uploaded_at`` is older than the cutoff.
  - Never remove ``logs/`` or ``receipts/``.
  - Never remove binaries still referenced by pending/conflict/failed receipts.
  - mediagen has no Telegram delivery ack. The default 7-day window
    (``MEDIA_CACHE_DAYS``, default 7) is the conservative stand-in so recent
    outputs remain on disk for Telegram even after R2 upload.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from media_client import (
    default_receipts_dir,
    load_config,
    load_receipt,
    sanitize_error_text,
    sync_receipt,
)

DEFAULT_WORKSPACE = Path(
    os.environ.get("MEDIAGEN_WORKSPACE", os.path.expanduser("~/.hermes/workspace/mediagen"))
)
DEFAULT_CACHE_DAYS = 7
PROTECTED_PREFIXES = ("logs/", "receipts/")
# Only regular files under these prefixes may be unlinked by prune.
PRUNEABLE_PREFIXES = ("images/", "videos/", "external/")


def default_cache_days(env: Optional[dict[str, str]] = None) -> int:
    """Return MEDIA_CACHE_DAYS (default 7) when unset or invalid."""
    src = env if env is not None else os.environ
    raw = (src.get("MEDIA_CACHE_DAYS") or "").strip()
    if not raw:
        return DEFAULT_CACHE_DAYS
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_CACHE_DAYS
    if days < 0:
        return DEFAULT_CACHE_DAYS
    return days


def _list_receipt_paths(workspace: Path) -> list[Path]:
    receipts_dir = default_receipts_dir(workspace)
    if not receipts_dir.is_dir():
        return []
    return sorted(receipts_dir.glob("*.json"))


def _parse_iso_utc(value: str | None) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _provider_for_endpoint(endpoint: str) -> str:
    if "openai-codex" in endpoint or endpoint.startswith("openai"):
        return "openai-codex"
    if "x.ai" in endpoint or endpoint.startswith("xai") or "grok-imagine" in endpoint:
        return "xai"
    return "fal"


def _model_key_from_endpoint(endpoint: str) -> str:
    """Best-effort short model key; fall back to endpoint string."""
    mapping = {
        "fal-ai/flux-2": "flux2",
        "fal-ai/flux-2/edit": "flux2",
        "fal-ai/nano-banana-2": "nano2",
        "fal-ai/nano-banana-2/edit": "nano2",
        "openai-codex/gpt-image-2": "gptimage2",
        "https://api.x.ai/v1/images/generations": "grokimage2",
        "https://api.x.ai/v1/images/edits": "grokimage2",
        "https://api.x.ai/v1/videos/generations": "grokvideo",
        "fal-ai/bytedance/seedance/v1.5/pro/text-to-video": "seedance2",
        "fal-ai/bytedance/seedance/v1.5/pro/image-to-video": "seedance2",
    }
    if endpoint in mapping:
        return mapping[endpoint]
    # partial match
    for key, name in (
        ("flux-2", "flux2"),
        ("nano-banana-2", "nano2"),
        ("gpt-image", "gptimage2"),
        ("images/generations", "grokimage2"),
        ("images/edits", "grokimage2"),
        ("videos/generations", "grokvideo"),
        ("seedance", "seedance2"),
    ):
        if key in endpoint:
            return name
    return endpoint or "unknown"


def rebuild_generation(workspace: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Rebuild generation payload from receipt assets + generation log JSON."""
    if isinstance(receipt.get("generation"), dict) and receipt["generation"]:
        return dict(receipt["generation"])

    log_rel = receipt.get("log_path") or ""
    log_path = Path(workspace) / log_rel
    log: dict[str, Any] = {}
    if log_path.is_file():
        try:
            with open(log_path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                log = loaded
        except (OSError, json.JSONDecodeError):
            log = {}

    mode = log.get("mode") or "generate"
    endpoint = str(log.get("model") or "")
    if mode == "generate":
        operation = "generate"
    elif mode == "edit":
        operation = "edit"
    elif mode == "image-to-video":
        operation = "image-to-video"
    elif mode == "text-to-video":
        operation = "text-to-video"
    else:
        operation = str(mode)

    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for asset in receipt.get("assets") or []:
        path = asset.get("path")
        if not path:
            continue
        if asset.get("role"):
            entry: dict[str, Any] = {
                "path": path,
                "role": asset["role"],
                "position": int(asset.get("position") or 0),
            }
            inputs.append(entry)
        else:
            outputs.append({"path": path, "position": int(asset.get("position") or 0)})

    if not outputs:
        # fall back: last asset without role, or log filename
        filename = log.get("filename")
        if filename:
            if str(filename).endswith((".mp4", ".webm", ".mov")):
                outputs = [{"path": f"videos/raw/{filename}", "position": 0}]
            else:
                outputs = [{"path": f"images/raw/{filename}", "position": 0}]

    params: dict[str, Any] = {"endpoint": endpoint} if endpoint else {}
    for key in ("width", "height", "resolution", "duration", "aspect_ratio", "audio", "camera_fixed"):
        if key in log:
            params[key] = log[key]

    return {
        "tool": "mediagen",
        "operation": operation,
        "provider": _provider_for_endpoint(endpoint),
        "model": _model_key_from_endpoint(endpoint),
        "prompt": log.get("prompt"),
        "seed": log.get("seed"),
        "params": params,
        "status": "succeeded",
        "inputs": inputs,
        "outputs": outputs,
    }


def _sanitize_retry_error(text: str, *, cfg: Any = None) -> str:
    """Redact tokens/URLs from retry error strings before append/print."""
    token = getattr(cfg, "token", None) if cfg is not None else None
    api_url = getattr(cfg, "api_url", None) if cfg is not None else None
    # Prefer live env when cfg is disabled/missing so redaction still works.
    if not token:
        token = (os.environ.get("MEDIA_API_TOKEN") or "").strip() or None
        if not token:
            token_file = (os.environ.get("MEDIA_API_TOKEN_FILE") or "").strip()
            if token_file:
                try:
                    token = Path(token_file).expanduser().read_text(encoding="utf-8").strip() or None
                except OSError:
                    token = None
    if not api_url:
        api_url = (os.environ.get("MEDIA_API_URL") or "").strip() or None
    return sanitize_error_text(str(text), token=token, api_url=api_url)


def require_workspace(workspace: Path | str) -> Path:
    """Fail closed when workspace (receipts parent) does not exist."""
    ws = Path(workspace).expanduser()
    if not ws.exists() or not ws.is_dir():
        raise FileNotFoundError(f"workspace does not exist: {ws}")
    return ws


def cmd_retry(*, workspace: Path | str) -> dict[str, Any]:
    """Retry only receipts with status pending. completed/conflict/failed are no-ops."""
    workspace = require_workspace(workspace)
    cfg = load_config()
    receipts_dir = default_receipts_dir(workspace)

    retried = 0
    skipped = 0
    errors: list[str] = []

    if not cfg.enabled:
        # Still scan so callers see counts; nothing to upload without config.
        for path in _list_receipt_paths(workspace):
            try:
                receipt = load_receipt(path)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(_sanitize_retry_error(f"{path.name}: {exc}", cfg=cfg))
                continue
            if receipt.get("status") == "pending":
                skipped += 1  # cannot retry without config
            else:
                skipped += 1
        return {
            "retried": 0,
            "skipped": skipped,
            "errors": errors
            + (
                [
                    _sanitize_retry_error(
                        "media sync disabled (missing MEDIA_API_URL/token)", cfg=cfg
                    )
                ]
                if skipped
                else []
            ),
            "enabled": False,
        }

    for path in _list_receipt_paths(workspace):
        try:
            receipt = load_receipt(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(_sanitize_retry_error(f"{path.name}: {exc}", cfg=cfg))
            continue

        status = receipt.get("status")
        if status != "pending":
            skipped += 1
            continue

        generation = rebuild_generation(workspace, receipt)
        try:
            sync_receipt(
                cfg,
                receipt=receipt,
                workspace=workspace,
                generation=generation,
                receipts_dir=receipts_dir,
            )
            retried += 1
        except Exception as exc:  # noqa: BLE001 — keep going across receipts
            errors.append(_sanitize_retry_error(f"{path.name}: {exc}", cfg=cfg))
            retried += 1  # attempt counted even if raised unexpectedly

    return {"retried": retried, "skipped": skipped, "errors": errors, "enabled": True}


def _is_protected_rel(rel: str) -> bool:
    norm = rel.replace("\\", "/").lstrip("./")
    if not norm or norm in (".", ".."):
        return True
    if any(part in ("..",) for part in Path(norm).parts):
        return True
    return any(norm == p.rstrip("/") or norm.startswith(p) for p in PROTECTED_PREFIXES)


def _is_pruneable_media_rel(rel: str) -> bool:
    """True when relative path is under an allowed media binary prefix."""
    norm = rel.replace("\\", "/").lstrip("./")
    if not norm or _is_protected_rel(norm):
        return False
    return any(norm == p.rstrip("/") or norm.startswith(p) for p in PRUNEABLE_PREFIXES)


def _path_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_to_unlink_prune_target(workspace: Path, rel: str) -> Optional[Path]:
    """Return a regular file path safe to unlink, or None if refuse.

    Rules (fail closed):
      - refuse if the workspace-relative entry is a symlink
      - refuse if resolved path escapes workspace
      - refuse if resolved path is under workspace/logs or workspace/receipts
      - refuse unless resolved path is a regular file under images/, videos/, or external/
    """
    workspace = workspace.resolve()
    candidate = workspace / rel.replace("\\", "/").lstrip("./")

    # Refuse before following: never unlink a symlink entry.
    try:
        if candidate.is_symlink():
            return None
    except OSError:
        return None

    try:
        resolved = candidate.resolve()
    except OSError:
        return None

    if not _path_under(resolved, workspace):
        return None

    logs_dir = (workspace / "logs").resolve()
    receipts_dir = (workspace / "receipts").resolve()
    if resolved == logs_dir or _path_under(resolved, logs_dir):
        return None
    if resolved == receipts_dir or _path_under(resolved, receipts_dir):
        return None

    try:
        rel_resolved = resolved.relative_to(workspace).as_posix()
    except ValueError:
        return None
    if not _is_pruneable_media_rel(rel_resolved):
        return None

    # Unlink only a regular non-symlink file at the candidate path.
    try:
        if candidate.is_symlink() or resolved.is_symlink():
            return None
        if not candidate.is_file() or not resolved.is_file():
            return None
    except OSError:
        return None

    return candidate


def _asset_eligible_for_prune(
    *,
    receipt: dict[str, Any],
    asset: dict[str, Any],
    cutoff: datetime,
) -> bool:
    if receipt.get("status") != "completed":
        return False
    uploaded = _parse_iso_utc(asset.get("uploaded_at"))
    if uploaded is None:
        return False
    return uploaded <= cutoff


def cmd_prune(
    *,
    workspace: Path | str,
    days: int | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prune local binaries that are fully uploaded and older than the cache window.

    Shared external files are removed only when EVERY receipt that references
    the path is complete with uploaded_at older than cutoff.
    """
    workspace = require_workspace(workspace)
    if days is None:
        days = default_cache_days()
    if days < 0:
        days = default_cache_days()

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    cutoff = now_utc - timedelta(days=days)

    # path -> list of (receipt_status, eligible_bool)
    refs: dict[str, list[tuple[str, bool]]] = {}

    for path in _list_receipt_paths(workspace):
        try:
            receipt = load_receipt(path)
        except (OSError, json.JSONDecodeError):
            continue
        status = str(receipt.get("status") or "unknown")
        for asset in receipt.get("assets") or []:
            rel = str(asset.get("path") or "").replace("\\", "/").lstrip("./")
            if not rel or _is_protected_rel(rel) or not _is_pruneable_media_rel(rel):
                continue
            eligible = _asset_eligible_for_prune(receipt=receipt, asset=asset, cutoff=cutoff)
            refs.setdefault(rel, []).append((status, eligible))

    would_remove: list[str] = []
    removed: list[str] = []
    kept: list[str] = []

    for rel, entries in sorted(refs.items()):
        # Remove only when every referencing receipt marks this asset eligible
        # (completed + uploaded_at older than cutoff). Any pending/conflict/failed
        # or recent completed reference keeps the file.
        if not entries:
            continue
        if all(eligible for _status, eligible in entries):
            target = _safe_to_unlink_prune_target(workspace, rel)
            if target is None:
                kept.append(rel)
                continue
            would_remove.append(rel)
            if apply:
                try:
                    # Unlink the workspace-relative path only after safety checks.
                    # Never follow symlinks: refuse if it became a symlink.
                    if target.is_symlink() or not target.is_file():
                        kept.append(rel)
                        would_remove.pop()
                        continue
                    target.unlink()
                    removed.append(rel)
                except OSError:
                    kept.append(rel)
            # missing file: nothing to do
        else:
            kept.append(rel)

    return {
        "days": days,
        "cutoff": cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "apply": apply,
        "would_remove": would_remove,
        "removed": removed if apply else [],
        "kept": kept,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media_sync.py",
        description=(
            "Retry pending Hostkit Media receipts and prune local binary cache. "
            "No Telegram delivery ack exists; MEDIA_CACHE_DAYS (default 7) keeps "
            "recent outputs on disk after upload."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_retry = sub.add_parser("retry", help="Retry receipts with status=pending only")
    p_retry.add_argument(
        "--workspace",
        type=str,
        default=str(DEFAULT_WORKSPACE),
        help="mediagen workspace (default: ~/.hermes/workspace/mediagen)",
    )

    p_prune = sub.add_parser(
        "prune",
        help="Remove local binaries fully uploaded and older than the cache window",
    )
    p_prune.add_argument(
        "--workspace",
        type=str,
        default=str(DEFAULT_WORKSPACE),
        help="mediagen workspace (default: ~/.hermes/workspace/mediagen)",
    )
    p_prune.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"cache retention days (default: MEDIA_CACHE_DAYS or {DEFAULT_CACHE_DAYS})",
    )
    mode = p_prune.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="list candidates without deleting",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="delete eligible binaries",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "retry":
        try:
            result = cmd_retry(workspace=args.workspace)
        except FileNotFoundError as exc:
            err = _sanitize_retry_error(str(exc))
            print(json.dumps({"error": err}, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        # Sanitize again at print boundary (defense in depth).
        if result.get("errors"):
            cfg = load_config()
            result = dict(result)
            result["errors"] = [
                _sanitize_retry_error(e, cfg=cfg) for e in result["errors"]
            ]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not result.get("errors") else 1

    if args.command == "prune":
        try:
            result = cmd_prune(
                workspace=args.workspace,
                days=args.days,
                apply=bool(args.apply),
            )
        except FileNotFoundError as exc:
            err = _sanitize_retry_error(str(exc))
            print(json.dumps({"error": err}, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
