#!/usr/bin/env python3
"""media_backfill.py — Parse mediagen logs and plan Media API backfill (G1).

Dry-run by default. Never prints tokens, signed URLs, or full secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from media_client import (
    asset_idempotency_key,
    load_config,
    post_generation_run,
    run_idempotency_key,
    upload_asset,
)

VIDEO_EXTS = (".mp4", ".webm", ".mov")


@dataclass
class BackfillPlan:
    assets: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def _resolve_output_rel(filename: str) -> str:
    name = Path(str(filename)).name
    if name.lower().endswith(VIDEO_EXTS):
        return f"videos/raw/{name}"
    return f"images/raw/{name}"


def _provider_for_endpoint(endpoint: str) -> str:
    if "openai-codex" in endpoint or endpoint.startswith("openai"):
        return "openai-codex"
    if "x.ai" in endpoint or endpoint.startswith("xai") or "grok-imagine" in endpoint:
        return "xai"
    return "fal"


def _model_key_from_endpoint(endpoint: str) -> str:
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


def _operation_for_mode(mode: str) -> Optional[str]:
    mapping = {
        "generate": "generate",
        "edit": "edit",
        "image-to-video": "image-to-video",
        "text-to-video": "text-to-video",
    }
    return mapping.get(mode)


def _list_log_paths(workspace: Path) -> list[Path]:
    logs_dir = workspace / "logs"
    if not logs_dir.is_dir():
        return []
    return sorted(p for p in logs_dir.glob("*.json") if p.is_file())


def _confine_workspace_rel(workspace: Path, rel: str) -> Optional[str]:
    """Resolve rel under workspace; return posix rel or None if it escapes.

    Fail-closed: rejects ``..`` traversal and symlinks whose resolved target
    leaves the workspace (same idea as media_client._resolve_workspace_file).
    """
    if not rel or not isinstance(rel, str):
        return None
    workspace_resolved = Path(workspace).resolve()
    # Reject null bytes / empty segments early
    cleaned = rel.replace("\\", "/").lstrip("/")
    if not cleaned or cleaned in (".", ".."):
        return None
    try:
        file_path = (workspace_resolved / cleaned).resolve()
        confined = file_path.relative_to(workspace_resolved)
    except (ValueError, OSError, RuntimeError):
        return None
    return str(confined).replace("\\", "/")


def _normalize_input_rel(workspace: Path, raw: str) -> Optional[str]:
    """Map a log input path to a workspace-relative path confined to workspace."""
    if not raw or not isinstance(raw, str):
        return None
    workspace_resolved = workspace.resolve()
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve()
            rel = resolved.relative_to(workspace_resolved)
            return str(rel).replace("\\", "/")
        except (ValueError, OSError, RuntimeError):
            # basename-only fallback under external/ (copy_to_external pattern)
            name = candidate.name
            if not name or name in (".", ".."):
                return None
            return _confine_workspace_rel(workspace, f"external/{name}")
    # relative: strip leading ./
    text = raw.replace("\\", "/").lstrip("./")
    if not text:
        return None
    # if already external/ or images/ etc, keep — but always confine after map
    if text.startswith(("external/", "images/", "videos/")):
        return _confine_workspace_rel(workspace, text)
    # bare filename → external/<name>
    name = Path(text).name
    if not name or name in (".", ".."):
        return None
    return _confine_workspace_rel(workspace, f"external/{name}")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _kind_for_rel(rel: str) -> str:
    if rel.startswith("videos/") or rel.lower().endswith(VIDEO_EXTS):
        return "video"
    return "image"


def _clip_idempotency_key(key: str) -> str:
    """Match upload_asset: truncate to 160 so retries stay identical."""
    if len(key) > 160:
        return key[:160]
    return key


def _make_input_asset(rel: str, *, role: str, position: int) -> dict[str, Any]:
    return {
        "path": rel,
        "kind": _kind_for_rel(rel),
        "origin": "external_import",
        "ingested_via": "backfill",
        "show_in_grid": False,
        "role": role,
        "position": position,
        "idempotency_key": _clip_idempotency_key(asset_idempotency_key(rel)),
    }


def _collect_run_inputs(
    workspace: Path,
    log: dict[str, Any],
    operation: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Return (input assets, gen inputs, errors)."""
    assets: list[dict[str, Any]] = []
    gen_inputs: list[dict[str, Any]] = []
    errors: list[str] = []

    if operation == "edit":
        raw_inputs = log.get("inputs") or []
        if not isinstance(raw_inputs, list):
            errors.append("inputs is not a list")
            return assets, gen_inputs, errors
        for i, raw in enumerate(raw_inputs):
            rel = _normalize_input_rel(workspace, str(raw))
            if not rel:
                errors.append(f"input escapes workspace: {Path(str(raw)).name}")
                continue
            if not (workspace / rel).is_file():
                errors.append(f"missing input file: {rel}")
                continue
            assets.append(_make_input_asset(rel, role="edit_source", position=i))
            gen_inputs.append({"path": rel, "role": "edit_source", "position": i})
        return assets, gen_inputs, errors

    if operation == "image-to-video":
        raw_inputs = log.get("inputs") or []
        if isinstance(raw_inputs, list) and raw_inputs:
            rel = _normalize_input_rel(workspace, str(raw_inputs[0]))
            if not rel:
                errors.append(f"start_frame escapes workspace: {Path(str(raw_inputs[0])).name}")
            elif not (workspace / rel).is_file():
                errors.append(f"missing input file: {rel}")
            else:
                assets.append(_make_input_asset(rel, role="start_frame", position=0))
                gen_inputs.append({"path": rel, "role": "start_frame", "position": 0})
        end_raw = log.get("end_image")
        if end_raw:
            rel = _normalize_input_rel(workspace, str(end_raw))
            if not rel:
                errors.append(f"end_frame escapes workspace: {Path(str(end_raw)).name}")
            elif not (workspace / rel).is_file():
                errors.append(f"missing input file: {rel}")
            else:
                assets.append(_make_input_asset(rel, role="end_frame", position=1))
                gen_inputs.append({"path": rel, "role": "end_frame", "position": 1})
        return assets, gen_inputs, errors

    return assets, gen_inputs, errors


def build_backfill_plan(workspace: Path | str) -> BackfillPlan:
    workspace = Path(workspace)
    assets: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    # path -> asset (first wins for same path within plan for outputs;
    # referenced external paths stay one asset per path key)
    asset_by_path: dict[str, dict[str, Any]] = {}
    referenced_external: set[str] = set()
    # output basename -> (out_rel, sha256) for copy reconciliation
    output_by_basename: dict[str, tuple[str, str]] = {}

    def add_asset(asset: dict[str, Any]) -> None:
        path = asset["path"]
        if path in asset_by_path:
            # merge role if incoming has role and existing doesn't
            existing = asset_by_path[path]
            if asset.get("role") and not existing.get("role"):
                existing["role"] = asset["role"]
                existing["position"] = asset.get("position", 0)
            return
        asset_by_path[path] = asset
        assets.append(asset)

    for log_path in _list_log_paths(workspace):
        try:
            with open(log_path, encoding="utf-8") as fh:
                log = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            issues.append({"log": log_path.name, "error": "unreadable JSON", "detail": type(exc).__name__})
            continue
        if not isinstance(log, dict):
            issues.append({"log": log_path.name, "error": "log is not an object"})
            continue

        filename = log.get("filename")
        if not filename:
            issues.append({"log": log_path.name, "error": "missing filename"})
            continue

        mode = log.get("mode")
        if not isinstance(mode, str):
            issues.append({"log": log_path.name, "error": "unknown mode"})
            continue
        operation = _operation_for_mode(mode)
        if operation is None:
            issues.append({"log": log_path.name, "error": "unknown mode", "mode": mode})
            continue

        endpoint = str(log.get("model") or "")
        provider = _provider_for_endpoint(endpoint)
        model_key = _model_key_from_endpoint(endpoint)

        out_rel = _resolve_output_rel(str(filename))
        confined_out = _confine_workspace_rel(workspace, out_rel)
        if confined_out is None:
            issues.append(
                {
                    "log": log_path.name,
                    "error": "output escapes workspace or not confined",
                    "path": out_rel,
                }
            )
            continue
        out_rel = confined_out
        out_abs = workspace / out_rel
        # Reject missing paths and non-regular files (e.g. lingering symlinks).
        if not out_abs.is_file() or out_abs.is_symlink():
            issues.append(
                {
                    "log": log_path.name,
                    "error": "missing output file" if not out_abs.is_file() else "output not a regular file",
                    "path": out_rel,
                }
            )
            continue

        in_assets, gen_inputs, in_errors = _collect_run_inputs(workspace, log, operation)
        for err in in_errors:
            issues.append({"log": log_path.name, "error": err})
        # still proceed with whatever inputs resolved

        kind = _kind_for_rel(out_rel)
        out_asset = {
            "path": out_rel,
            "kind": kind,
            "origin": "mediagen_generation",
            "ingested_via": "backfill",
            "show_in_grid": True,
            "position": 0,
            "idempotency_key": _clip_idempotency_key(asset_idempotency_key(out_rel)),
        }
        add_asset(out_asset)
        try:
            out_hash = _file_sha256(out_abs)
            output_by_basename[Path(out_rel).name] = (out_rel, out_hash)
        except OSError:
            pass

        for a in in_assets:
            add_asset(a)
            if a["path"].startswith("external/"):
                referenced_external.add(a["path"])

        # params: endpoint + non-dimension log fields that are generation params
        # Do NOT copy mime/width/height/duration into asset metadata (server owns those).
        # params_json may still carry generation settings from the log for the run.
        params: dict[str, Any] = {}
        if endpoint:
            params["endpoint"] = endpoint
        for key in ("resolution", "aspect_ratio", "audio", "camera_fixed", "seed"):
            # seed is top-level on generation; skip here
            if key == "seed":
                continue
            if key in log:
                params[key] = log[key]
        # intentionally omit width/height/duration from being treated as asset dims;
        # they may still be useful as generation params — task says upload/plan metadata
        # must not send mime/width/height/duration copied from the log for assets.
        # Keep generation params without inventing MIME; width/height/duration as gen params OK?
        # "Upload/plan metadata must not send mime/width/height/duration copied from the log."
        # So strip them from asset plan entries and from anything that looks like upload metadata.
        # Generation params historically include width/height — media_sync rebuild_generation does.
        # Safer: do not put width/height/duration in params either if task is strict.
        # Task: "MIME and dimensions come from the server, not legacy log JSON."
        # I'll keep endpoint + video flags only, not width/height/duration/mime.

        log_rel = f"logs/{log_path.name}"
        runs.append(
            {
                "log_path": log_rel,
                "idempotency_key": _clip_idempotency_key(run_idempotency_key(log_rel)),
                "operation": operation,
                "provider": provider,
                "model": model_key,
                "prompt": log.get("prompt"),
                "seed": log.get("seed"),
                "params": params,
                "status": "succeeded",
                "tool": "mediagen",
                "outputs": [{"path": out_rel, "position": 0}],
                "inputs": gen_inputs,
            }
        )

    # Post-pass: referenced external/<basename> that is a byte-identical copy of a
    # generation output (same basename + SHA-256) reuses the output item path.
    # Must run after all logs are parsed so output_by_basename is complete regardless
    # of log filename sort order (e.g. edit.json before gen.json).
    remap_external_to_output: dict[str, str] = {}
    for rel in list(referenced_external):
        if not rel.startswith("external/"):
            continue
        basename = Path(rel).name
        if basename not in output_by_basename:
            continue
        out_rel, out_hash = output_by_basename[basename]
        ext_abs = workspace / rel
        if not ext_abs.is_file():
            continue
        try:
            h = _file_sha256(ext_abs)
        except OSError:
            continue
        if h != out_hash:
            continue
        remap_external_to_output[rel] = out_rel

    if remap_external_to_output:
        for ext_rel, out_rel in remap_external_to_output.items():
            referenced_external.discard(ext_rel)
            # drop the duplicate external asset entry
            if ext_rel in asset_by_path:
                del asset_by_path[ext_rel]
            assets[:] = [a for a in assets if a["path"] != ext_rel]
            # rewrite run inputs that pointed at the external copy
            for run in runs:
                for inp in run.get("inputs") or []:
                    if inp.get("path") == ext_rel:
                        inp["path"] = out_rel
            # ensure output asset carries any input role if it was only on the external
            # (output already exists; roles on generation outputs are optional)

    # External reconciliation
    external_dir = workspace / "external"
    orphan_aliases: list[dict[str, Any]] = []
    unique_externals: list[str] = []

    # hashes of referenced inputs (for orphan alias detection)
    referenced_hashes: dict[str, set[str]] = {}  # hash -> set of paths
    for rel in referenced_external:
        p = workspace / rel
        if p.is_file():
            try:
                h = _file_sha256(p)
            except OSError:
                continue
            referenced_hashes.setdefault(h, set()).add(rel)

    if external_dir.is_dir():
        for ext_path in sorted(external_dir.iterdir()):
            # Skip non-files; is_file() follows symlinks so broken links are skipped
            # unless we still want to report escapes — check name via confine first.
            if ext_path.name.startswith("."):
                continue
            if not ext_path.is_file() and not ext_path.is_symlink():
                continue
            rel = _confine_workspace_rel(workspace, f"external/{ext_path.name}")
            if rel is None:
                issues.append(
                    {
                        "path": f"external/{ext_path.name}",
                        "error": "external path escapes workspace",
                    }
                )
                continue
            if not ext_path.is_file():
                continue
            if rel in asset_by_path or rel in referenced_external:
                continue
            try:
                # Hash the confined resolved path (symlink target must be in workspace)
                h = _file_sha256((workspace.resolve() / rel))
            except OSError as exc:
                issues.append({"path": rel, "error": f"unreadable external: {type(exc).__name__}"})
                continue

            # Reconcile as copy of output only when basename + hash match that output
            basename = Path(rel).name
            if basename in output_by_basename:
                out_rel, out_hash = output_by_basename[basename]
                if h == out_hash:
                    # reconciled alias of generation output — do not create second asset
                    continue

            # Orphan alias of a referenced input (same bytes, different name)
            if h in referenced_hashes:
                orphan_aliases.append(
                    {
                        "path": rel,
                        "kind": "orphan_alias",
                        "alias_of": sorted(referenced_hashes[h]),
                        "content_hash": h[:12],
                    }
                )
                continue

            # Unique external import
            unique_externals.append(rel)
            add_asset(
                {
                    "path": rel,
                    "kind": _kind_for_rel(rel),
                    "origin": "external_import",
                    "ingested_via": "backfill",
                    "show_in_grid": False,
                    "idempotency_key": _clip_idempotency_key(asset_idempotency_key(rel)),
                }
            )

    report = {
        "issues": issues,
        "asset_count": len(assets),
        "run_count": len(runs),
        "orphan_aliases": orphan_aliases,
        "unique_externals": unique_externals,
    }
    return BackfillPlan(assets=assets, runs=runs, report=report)


def _sanitize_report(plan: BackfillPlan, workspace: Path) -> dict[str, Any]:
    """Build a report free of prompts, tokens, signed URLs, absolute paths."""
    ws = str(workspace.resolve())
    issues_out = []
    for issue in plan.report.get("issues") or []:
        clean = {k: v for k, v in issue.items() if k != "prompt"}
        # never absolute paths
        for key in ("path", "detail", "error"):
            if key in clean and isinstance(clean[key], str):
                clean[key] = clean[key].replace(ws, "[workspace]")
        issues_out.append(clean)
    return {
        "asset_count": plan.report.get("asset_count", len(plan.assets)),
        "run_count": plan.report.get("run_count", len(plan.runs)),
        "assets": [
            {
                "path": a["path"],
                "origin": a.get("origin"),
                "ingested_via": a.get("ingested_via"),
                "show_in_grid": a.get("show_in_grid"),
                "kind": a.get("kind"),
                "role": a.get("role"),
                "position": a.get("position"),
                "idempotency_key": a.get("idempotency_key"),
            }
            for a in plan.assets
        ],
        "runs": [
            {
                "log_path": r["log_path"],
                "operation": r.get("operation"),
                "provider": r.get("provider"),
                "model": r.get("model"),
                "idempotency_key": r.get("idempotency_key"),
                "input_count": len(r.get("inputs") or []),
                "output_count": len(r.get("outputs") or []),
                "params_endpoint": (r.get("params") or {}).get("endpoint"),
            }
            for r in plan.runs
        ],
        "issues": issues_out,
        "orphan_aliases": plan.report.get("orphan_aliases") or [],
        "unique_externals": plan.report.get("unique_externals") or [],
    }


def apply_backfill_plan(
    workspace: Path | str,
    plan: BackfillPlan,
    *,
    upload_fn=None,
    post_run_fn=None,
    cfg=None,
) -> dict[str, Any]:
    """Apply plan via Media API (or injected callables). Returns summary."""
    workspace = Path(workspace)
    upload_fn = upload_fn or upload_asset
    post_run_fn = post_run_fn or post_generation_run
    if cfg is None:
        cfg = load_config()

    uploaded: dict[str, str] = {}
    errors: list[str] = []

    for asset in plan.assets:
        try:
            result = upload_fn(cfg, workspace=workspace, asset=asset)
            mid = result.get("media_item_id") if isinstance(result, dict) else None
            if mid:
                uploaded[asset["path"]] = mid
        except Exception as exc:  # noqa: BLE001 — collect and continue
            errors.append(f"{asset['path']}: {type(exc).__name__}")

    runs_ok = 0
    for run in plan.runs:
        generation = {
            "tool": run.get("tool") or "mediagen",
            "operation": run["operation"],
            "provider": run["provider"],
            "model": run["model"],
            "prompt": run.get("prompt"),
            "seed": run.get("seed"),
            "params": run.get("params") or {},
            "status": run.get("status") or "succeeded",
            "inputs": run.get("inputs") or [],
            "outputs": run.get("outputs") or [],
        }
        receipt = {
            "run_key": run["idempotency_key"],
            "log_path": run["log_path"],
            "assets": [
                {
                    **a,
                    "media_item_id": uploaded.get(a["path"]),
                }
                for a in plan.assets
                if a["path"] in {i["path"] for i in (run.get("inputs") or [])}
                or a["path"] in {o["path"] for o in (run.get("outputs") or [])}
            ],
        }
        try:
            post_run_fn(cfg, receipt=receipt, generation=generation)
            runs_ok += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{run['log_path']}: {type(exc).__name__}")

    return {"uploaded": len(uploaded), "runs_ok": runs_ok, "errors": errors}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill mediagen workspace into Media API")
    parser.add_argument("--workspace", required=True, help="mediagen workspace directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="plan only; do not call Media API (default when --apply is omitted)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="upload/post using Media API (requires MEDIA_API_URL + token file)",
    )
    parser.add_argument("--report", default=None, help="write JSON report to this path")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).expanduser()
    if not workspace.is_dir():
        print(f"ERROR=workspace does not exist: {workspace}", file=sys.stderr)
        return 2

    # Safety: --apply is opt-in. --dry-run wins if both are passed.
    do_apply = bool(args.apply) and not bool(args.dry_run)

    plan = build_backfill_plan(workspace)
    report = _sanitize_report(plan, workspace)
    exit_code = 0

    if do_apply:
        cfg = load_config()
        if not getattr(cfg, "enabled", False):
            # Fail closed: never upload/post when Media is disabled.
            print("ERROR=Media API disabled or not configured", file=sys.stderr)
            report["mode"] = "apply-aborted"
            report["error"] = "media_disabled"
            exit_code = 2
        else:
            summary = apply_backfill_plan(workspace, plan, cfg=cfg)
            report["mode"] = "apply"
            report["apply"] = {
                "uploaded": summary["uploaded"],
                "runs_ok": summary["runs_ok"],
                "error_count": len(summary["errors"]),
            }
            # Total failure: every upload/run failed (or errors with zero successes).
            attempted = len(plan.assets) + len(plan.runs)
            if attempted > 0 and summary["uploaded"] == 0 and summary["runs_ok"] == 0:
                exit_code = 2
            elif summary["errors"] and summary["uploaded"] == 0 and summary["runs_ok"] == 0:
                exit_code = 2
    else:
        report["mode"] = "dry-run"

    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
