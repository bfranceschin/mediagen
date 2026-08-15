"""Vertical TDD tests for media_backfill parser/reconciliation (G1)."""

from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path

import pytest

import media_backfill
import media_client

FIXTURES = Path(__file__).parent / "fixtures"


def _make_png(pixel: bytes = b"\xff\x00\x00") -> bytes:
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    raw = zlib.compress(b"\x00" + pixel)
    idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
    idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return header + ihdr + idat + iend


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _place_log(ws: Path, fixture_name: str, dest_name: str | None = None) -> Path:
    src = FIXTURES / fixture_name
    name = dest_name or fixture_name
    dest = ws / "logs" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    return dest


def _ensure_video_dirs(ws: Path) -> None:
    (ws / "videos" / "raw").mkdir(parents=True, exist_ok=True)


# ── 1. Resolve output path from log.filename ─────────────────────────────────


def test_resolve_output_path_image_and_video(tmp_workspace):
    """Output lands in images/raw or videos/raw from log.filename."""
    ws = tmp_workspace
    _ensure_video_dirs(ws)

    img_name = "20260815T120000Z_flux2.png"
    vid_name = "20260815T120200Z_seedance2_i2v.mp4"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _write_bytes(ws / "videos" / "raw" / vid_name, b"fake-mp4-bytes")

    _place_log(ws, "log-image-generate.json")
    _place_log(ws, "log-i2v-end-frame.json")
    # i2v needs its inputs present for a full plan later; create placeholders
    _write_bytes(ws / "external" / "start_frame.png", _make_png(b"\x00\xff\x00"))
    _write_bytes(ws / "external" / "end_frame.png", _make_png(b"\x00\x00\xff"))

    plan = media_backfill.build_backfill_plan(ws)

    out_paths = {a["path"] for a in plan.assets if not a.get("role")}
    assert f"images/raw/{img_name}" in out_paths
    assert f"videos/raw/{vid_name}" in out_paths


# ── 2. Map mode → operation/provider ─────────────────────────────────────────


def test_map_mode_to_operation_and_provider(tmp_workspace):
    """Log mode maps to generation operation; fal vs openai-codex provider."""
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    # openai-codex generate log
    openai_name = "20260815T120300Z_gptimage2.png"
    _write_bytes(ws / "images" / "raw" / openai_name, _make_png(b"\x11\x22\x33"))
    (ws / "logs" / "log-openai-generate.json").write_text(
        json.dumps(
            {
                "filename": openai_name,
                "prompt": "synthetic openai image",
                "model": "openai-codex/gpt-image-2",
                "mode": "generate",
                "seed": 1,
                "width": 1024,
                "height": 1024,
                "timestamp": "2026-08-15T12:03:00+00:00",
                "inputs": [],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    by_out = {r["outputs"][0]["path"]: r for r in plan.runs}

    fal_run = by_out[f"images/raw/{img_name}"]
    assert fal_run["operation"] == "generate"
    assert fal_run["provider"] == "fal"

    oai_run = by_out[f"images/raw/{openai_name}"]
    assert oai_run["operation"] == "generate"
    assert oai_run["provider"] == "openai-codex"


# ── 3. Normalize provider/model; keep original endpoint in params ────────────


def test_normalize_model_and_keep_endpoint_in_params(tmp_workspace):
    ws = tmp_workspace
    _ensure_video_dirs(ws)

    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    edit_name = "20260815T120100Z_nano2_edit.png"
    _write_bytes(ws / "images" / "raw" / edit_name, _make_png(b"\xaa\xbb\xcc"))
    _write_bytes(ws / "external" / "ref_a.png", _make_png(b"\x01\x02\x03"))
    _write_bytes(ws / "external" / "ref_b.png", _make_png(b"\x04\x05\x06"))
    _place_log(ws, "log-image-edit-multi.json")

    vid_name = "20260815T120200Z_seedance2_i2v.mp4"
    _write_bytes(ws / "videos" / "raw" / vid_name, b"fake-mp4")
    _write_bytes(ws / "external" / "start_frame.png", _make_png(b"\x00\xff\x00"))
    _write_bytes(ws / "external" / "end_frame.png", _make_png(b"\x00\x00\xff"))
    _place_log(ws, "log-i2v-end-frame.json")

    plan = media_backfill.build_backfill_plan(ws)
    by_out = {r["outputs"][0]["path"]: r for r in plan.runs}

    flux = by_out[f"images/raw/{img_name}"]
    assert flux["model"] == "flux2"
    assert flux["provider"] == "fal"
    assert flux["params"]["endpoint"] == "fal-ai/flux-2"

    nano = by_out[f"images/raw/{edit_name}"]
    assert nano["model"] == "nano2"
    assert nano["operation"] == "edit"
    assert nano["params"]["endpoint"] == "fal-ai/nano-banana-2/edit"

    seed = by_out[f"videos/raw/{vid_name}"]
    assert seed["model"] == "seedance2"
    assert seed["operation"] == "image-to-video"
    assert seed["params"]["endpoint"] == "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"


# ── 4. Edit inputs → edit_source by position ─────────────────────────────────


def test_edit_inputs_become_edit_source_by_position(tmp_workspace):
    ws = tmp_workspace
    edit_name = "20260815T120100Z_nano2_edit.png"
    _write_bytes(ws / "images" / "raw" / edit_name, _make_png(b"\xaa\xbb\xcc"))
    _write_bytes(ws / "external" / "ref_a.png", _make_png(b"\x01\x02\x03"))
    _write_bytes(ws / "external" / "ref_b.png", _make_png(b"\x04\x05\x06"))
    _place_log(ws, "log-image-edit-multi.json")

    plan = media_backfill.build_backfill_plan(ws)
    assert len(plan.runs) == 1
    run = plan.runs[0]
    assert run["operation"] == "edit"
    assert run["inputs"] == [
        {"path": "external/ref_a.png", "role": "edit_source", "position": 0},
        {"path": "external/ref_b.png", "role": "edit_source", "position": 1},
    ]
    roles = {(a["path"], a.get("role"), a.get("position")) for a in plan.assets if a.get("role")}
    assert ("external/ref_a.png", "edit_source", 0) in roles
    assert ("external/ref_b.png", "edit_source", 1) in roles
    for a in plan.assets:
        if a.get("role"):
            assert a["origin"] == "external_import"
            assert a["show_in_grid"] is False
            assert a["ingested_via"] == "backfill"


# ── 5. i2v first input → start_frame; end_image → end_frame ──────────────────


def test_i2v_start_and_end_frame_roles(tmp_workspace):
    ws = tmp_workspace
    _ensure_video_dirs(ws)
    vid_name = "20260815T120200Z_seedance2_i2v.mp4"
    _write_bytes(ws / "videos" / "raw" / vid_name, b"fake-mp4")
    _write_bytes(ws / "external" / "start_frame.png", _make_png(b"\x00\xff\x00"))
    _write_bytes(ws / "external" / "end_frame.png", _make_png(b"\x00\x00\xff"))
    _place_log(ws, "log-i2v-end-frame.json")

    plan = media_backfill.build_backfill_plan(ws)
    assert len(plan.runs) == 1
    run = plan.runs[0]
    assert run["operation"] == "image-to-video"
    assert run["inputs"] == [
        {"path": "external/start_frame.png", "role": "start_frame", "position": 0},
        {"path": "external/end_frame.png", "role": "end_frame", "position": 1},
    ]
    by_path = {a["path"]: a for a in plan.assets}
    assert by_path["external/start_frame.png"]["role"] == "start_frame"
    assert by_path["external/end_frame.png"]["role"] == "end_frame"
    assert by_path["external/start_frame.png"]["position"] == 0
    assert by_path["external/end_frame.png"]["position"] == 1


# ── 6. External copy of output reconciled only with basename + hash ──────────


def test_external_output_copy_reconciled_only_with_basename_and_hash(tmp_workspace):
    """Hash alone must NOT merge globally; basename+hash of output does reconcile."""
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    png = _make_png(b"\xde\xad\xbe")
    _write_bytes(ws / "images" / "raw" / img_name, png)
    # copy_to_external style: same basename under external/
    _write_bytes(ws / "external" / img_name, png)
    # different basename, same bytes — must NOT reconcile as the output
    _write_bytes(ws / "external" / "unrelated_same_bytes.png", png)
    _place_log(ws, "log-image-generate.json")

    plan = media_backfill.build_backfill_plan(ws)
    paths = {a["path"] for a in plan.assets}
    assert f"images/raw/{img_name}" in paths
    # reconciled copy: no second asset for external/<same basename>
    assert f"external/{img_name}" not in paths
    # hash-only match with different name is NOT treated as the generation output
    assert "external/unrelated_same_bytes.png" in paths
    unrelated = next(a for a in plan.assets if a["path"] == "external/unrelated_same_bytes.png")
    assert unrelated["origin"] == "external_import"
    assert unrelated["show_in_grid"] is False


def test_referenced_external_copy_of_output_reuses_output_item(tmp_workspace):
    """Referenced external/<same basename> of an output must reuse the output path.

    Logs are ordered so the edit is parsed before the generate log (edit.json < gen.json),
    ensuring remap cannot rely on seeing the output first during the parse loop.
    Hash-only match with a different basename remains a separate external_import.
    """
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    edit_out = "20260815T120100Z_nano2_edit.png"
    png = _make_png(b"\xde\xad\xbe")
    _write_bytes(ws / "images" / "raw" / img_name, png)
    # copy_to_external style: same basename under external/
    _write_bytes(ws / "external" / img_name, png)
    # different basename, same bytes — must NOT merge with the output
    _write_bytes(ws / "external" / "unrelated_same_bytes.png", png)
    _write_bytes(ws / "images" / "raw" / edit_out, _make_png(b"\xaa\xbb\xcc"))

    # edit log name sorts before gen so parse order is edit → generate
    (ws / "logs" / "edit.json").write_text(
        json.dumps(
            {
                "filename": edit_out,
                "prompt": "edit using external copy of prior output",
                "model": "fal-ai/nano-banana-2/edit",
                "mode": "edit",
                "seed": 7,
                "width": 1024,
                "height": 1024,
                "timestamp": "2026-08-15T12:01:00+00:00",
                "inputs": [f"external/{img_name}"],
            }
        ),
        encoding="utf-8",
    )
    (ws / "logs" / "gen.json").write_text(
        json.dumps(
            {
                "filename": img_name,
                "prompt": "synthetic blue cube on a table",
                "model": "fal-ai/flux-2",
                "mode": "generate",
                "seed": 42,
                "width": 1024,
                "height": 768,
                "timestamp": "2026-08-15T12:00:00+00:00",
                "inputs": [],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    paths = {a["path"] for a in plan.assets}
    out_rel = f"images/raw/{img_name}"

    assert out_rel in paths
    assert f"external/{img_name}" not in paths
    assert "external/unrelated_same_bytes.png" in paths
    unrelated = next(a for a in plan.assets if a["path"] == "external/unrelated_same_bytes.png")
    assert unrelated["origin"] == "external_import"

    edit_run = next(r for r in plan.runs if r["operation"] == "edit")
    assert edit_run["inputs"] == [
        {"path": out_rel, "role": "edit_source", "position": 0},
    ]


# ── 7. Unique external → external_import, show_in_grid=false ─────────────────


def test_unique_external_is_external_import_hidden_from_grid(tmp_workspace):
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")
    _write_bytes(ws / "external" / "solo_import.png", _make_png(b"\x12\x34\x56"))

    plan = media_backfill.build_backfill_plan(ws)
    solo = next(a for a in plan.assets if a["path"] == "external/solo_import.png")
    assert solo["origin"] == "external_import"
    assert solo["show_in_grid"] is False
    assert solo["ingested_via"] == "backfill"
    assert solo["idempotency_key"] == media_client.asset_idempotency_key("external/solo_import.png")


# ── 8. Byte-identical external aliases used by distinct logs stay distinct ───


def test_byte_identical_externals_for_distinct_logs_remain_distinct(tmp_workspace):
    ws = tmp_workspace
    shared = _make_png(b"\xab\xcd\xef")
    _write_bytes(ws / "external" / "alias_a.png", shared)
    _write_bytes(ws / "external" / "alias_b.png", shared)

    out_a = "out_a.png"
    out_b = "out_b.png"
    _write_bytes(ws / "images" / "raw" / out_a, _make_png(b"\x01\x01\x01"))
    _write_bytes(ws / "images" / "raw" / out_b, _make_png(b"\x02\x02\x02"))

    (ws / "logs" / "edit_a.json").write_text(
        json.dumps(
            {
                "filename": out_a,
                "prompt": "synthetic edit a",
                "model": "fal-ai/nano-banana-2/edit",
                "mode": "edit",
                "seed": 1,
                "timestamp": "2026-08-15T12:00:00+00:00",
                "inputs": ["external/alias_a.png"],
            }
        ),
        encoding="utf-8",
    )
    (ws / "logs" / "edit_b.json").write_text(
        json.dumps(
            {
                "filename": out_b,
                "prompt": "synthetic edit b",
                "model": "fal-ai/nano-banana-2/edit",
                "mode": "edit",
                "seed": 2,
                "timestamp": "2026-08-15T12:01:00+00:00",
                "inputs": ["external/alias_b.png"],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    paths = [a["path"] for a in plan.assets]
    assert paths.count("external/alias_a.png") == 1
    assert paths.count("external/alias_b.png") == 1
    keys = {
        a["path"]: a["idempotency_key"]
        for a in plan.assets
        if a["path"].startswith("external/")
    }
    assert keys["external/alias_a.png"] != keys["external/alias_b.png"]
    assert keys["external/alias_a.png"] == "mediagen:asset:external/alias_a.png"
    assert keys["external/alias_b.png"] == "mediagen:asset:external/alias_b.png"


# ── 9. Orphan alias of referenced input → report only ───────────────────────


def test_orphan_alias_of_referenced_input_is_report_only(tmp_workspace):
    ws = tmp_workspace
    shared = _make_png(b"\x55\x66\x77")
    _write_bytes(ws / "external" / "ref_a.png", shared)
    _write_bytes(ws / "external" / "ref_b.png", _make_png(b"\x04\x05\x06"))
    # unreferenced external that is byte-identical to ref_a
    _write_bytes(ws / "external" / "copy_of_ref_a.png", shared)

    edit_name = "20260815T120100Z_nano2_edit.png"
    _write_bytes(ws / "images" / "raw" / edit_name, _make_png(b"\xaa\xbb\xcc"))
    _place_log(ws, "log-image-edit-multi.json")

    plan = media_backfill.build_backfill_plan(ws)
    paths = {a["path"] for a in plan.assets}
    assert "external/copy_of_ref_a.png" not in paths
    orphans = plan.report.get("orphan_aliases") or []
    assert any(o.get("path") == "external/copy_of_ref_a.png" for o in orphans)
    orphan = next(o for o in orphans if o["path"] == "external/copy_of_ref_a.png")
    assert "external/ref_a.png" in orphan.get("alias_of", [])


# ── 10. Incomplete logs → report errors, no invented metadata ───────────────


def test_incomplete_logs_reported_without_inventing_metadata(tmp_workspace):
    ws = tmp_workspace
    # missing filename
    (ws / "logs" / "bad_no_filename.json").write_text(
        json.dumps({"mode": "generate", "model": "fal-ai/flux-2", "prompt": "x"}),
        encoding="utf-8",
    )
    # missing output file
    (ws / "logs" / "bad_missing_out.json").write_text(
        json.dumps(
            {
                "filename": "does_not_exist.png",
                "mode": "generate",
                "model": "fal-ai/flux-2",
                "prompt": "x",
            }
        ),
        encoding="utf-8",
    )
    # unreadable JSON
    (ws / "logs" / "bad_json.json").write_text("{not-json", encoding="utf-8")
    # unknown mode
    _write_bytes(ws / "images" / "raw" / "ok.png", _make_png())
    (ws / "logs" / "bad_mode.json").write_text(
        json.dumps(
            {
                "filename": "ok.png",
                "mode": "teleport",
                "model": "fal-ai/flux-2",
                "prompt": "x",
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    errors = {i.get("error") for i in plan.report.get("issues") or []}
    assert "missing filename" in errors
    assert "missing output file" in errors
    assert "unreadable JSON" in errors
    assert "unknown mode" in errors
    # no invented run for bad logs
    assert plan.runs == []
    # no invented assets from incomplete logs
    assert all(a["path"] != "images/raw/does_not_exist.png" for a in plan.assets)


# ── 11. No mime/width/height/duration copied from log into upload metadata ───


def test_plan_assets_do_not_copy_mime_or_dimensions_from_log(tmp_workspace):
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    plan = media_backfill.build_backfill_plan(ws)
    for a in plan.assets:
        assert "mime" not in a
        assert "mime_type" not in a
        assert "content_type" not in a
        assert "width" not in a
        assert "height" not in a
        assert "duration" not in a
    for r in plan.runs:
        params = r.get("params") or {}
        assert "mime" not in params
        assert "width" not in params
        assert "height" not in params
        assert "duration" not in params
        assert "endpoint" in params


# ── 12. --dry-run does not call the API ──────────────────────────────────────


def test_dry_run_makes_zero_api_calls(tmp_workspace, monkeypatch):
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    calls = {"upload": 0, "post": 0, "http": 0}

    def boom_upload(*a, **k):
        calls["upload"] += 1
        raise AssertionError("upload_asset should not be called in dry-run")

    def boom_post(*a, **k):
        calls["post"] += 1
        raise AssertionError("post_generation_run should not be called in dry-run")

    def boom_http(*a, **k):
        calls["http"] += 1
        raise AssertionError("HTTP should not be called in dry-run")

    monkeypatch.setattr(media_client, "upload_asset", boom_upload)
    monkeypatch.setattr(media_client, "post_generation_run", boom_post)
    monkeypatch.setattr(media_client, "_http_json", boom_http)
    monkeypatch.setattr(media_backfill, "upload_asset", boom_upload)
    monkeypatch.setattr(media_backfill, "post_generation_run", boom_post)

    report_path = ws / "report.json"
    rc = media_backfill.main(
        ["--workspace", str(ws), "--dry-run", "--report", str(report_path)]
    )
    assert rc == 0
    assert calls == {"upload": 0, "post": 0, "http": 0}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data.get("mode") == "dry-run"
    assert data["run_count"] >= 1


# ── 13. Retries use the same idempotency keys ────────────────────────────────


def test_apply_twice_uses_identical_idempotency_keys(tmp_workspace, monkeypatch):
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    plan = media_backfill.build_backfill_plan(ws)
    assert plan.runs
    expected_asset_key = media_client.asset_idempotency_key(f"images/raw/{img_name}")
    expected_run_key = media_client.run_idempotency_key("logs/log-image-generate.json")
    assert plan.assets[0]["idempotency_key"] == expected_asset_key
    assert plan.runs[0]["idempotency_key"] == expected_run_key

    seen_asset_keys: list[str] = []
    seen_run_keys: list[str] = []

    def fake_upload(cfg, *, workspace, asset):
        key = asset.get("idempotency_key") or media_client.asset_idempotency_key(asset["path"])
        seen_asset_keys.append(key)
        return {"media_item_id": f"id-{asset['path']}", "status": 201, "uploaded_at": "t"}

    def fake_post(cfg, *, receipt, generation):
        seen_run_keys.append(receipt["run_key"])
        return {"generation_run_id": "run-1", "status": 201}

    class Cfg:
        enabled = True
        api_url = "https://example.test"
        token = "x"
        timeout_seconds = 30

    media_backfill.apply_backfill_plan(
        ws, plan, upload_fn=fake_upload, post_run_fn=fake_post, cfg=Cfg()
    )
    media_backfill.apply_backfill_plan(
        ws, plan, upload_fn=fake_upload, post_run_fn=fake_post, cfg=Cfg()
    )

    assert seen_asset_keys == [expected_asset_key, expected_asset_key]
    assert seen_run_keys == [expected_run_key, expected_run_key]


# ── 14. Plan path confinement (no traversal / outside symlink) ───────────────


def test_traversal_input_is_not_plan_asset(tmp_workspace):
    """Traversal under images/ or external/ must not become a plan asset or hash outside files."""
    ws = tmp_workspace
    outside = ws.parent / "outside_secret.bin"
    outside.write_bytes(b"TOP-SECRET-OUTSIDE-BYTES")
    outside_hash = media_backfill._file_sha256(outside)

    edit_out = "edit_out.png"
    _write_bytes(ws / "images" / "raw" / edit_out, _make_png(b"\xaa\xbb\xcc"))
    # Valid sibling so the log still has a parseable output
    (ws / "logs" / "edit_traversal.json").write_text(
        json.dumps(
            {
                "filename": edit_out,
                "prompt": "should reject traversal inputs",
                "model": "fal-ai/nano-banana-2/edit",
                "mode": "edit",
                "seed": 1,
                "timestamp": "2026-08-15T12:00:00+00:00",
                "inputs": [
                    "images/raw/../../../outside_secret.bin",
                    "external/../../outside_secret.bin",
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    paths = {a["path"] for a in plan.assets}
    assert "outside_secret.bin" not in paths
    assert not any("outside_secret" in p for p in paths)
    assert not any(".." in p for p in paths)
    # Outside file must never be hashed into asset planning
    for a in plan.assets:
        abs_path = ws / a["path"]
        if abs_path.is_file():
            assert media_backfill._file_sha256(abs_path) != outside_hash or a["path"].startswith(
                ("images/", "videos/", "external/")
            )
    # Only the legitimate output should be present as an asset from this log
    assert f"images/raw/{edit_out}" in paths
    issues = plan.report.get("issues") or []
    assert issues, "traversal inputs must appear as report issues"
    issue_text = " ".join(str(i) for i in issues)
    assert "escapes" in issue_text or "missing" in issue_text or ".." in issue_text
    # No input assets added for the traversal paths
    assert not any(a.get("role") == "edit_source" for a in plan.assets)


def test_symlink_outside_workspace_rejected(tmp_workspace):
    """Symlink under external/ whose target leaves the workspace is rejected."""
    ws = tmp_workspace
    outside = ws.parent / "symlink_target_secret.png"
    outside.write_bytes(_make_png(b"\xee\xee\xee"))
    ext = ws / "external"
    ext.mkdir(parents=True, exist_ok=True)
    link = ext / "evil_link.png"
    link.symlink_to(outside)

    edit_out = "edit_symlink.png"
    _write_bytes(ws / "images" / "raw" / edit_out, _make_png(b"\x11\x22\x33"))
    (ws / "logs" / "edit_symlink.json").write_text(
        json.dumps(
            {
                "filename": edit_out,
                "prompt": "symlink escape",
                "model": "fal-ai/nano-banana-2/edit",
                "mode": "edit",
                "seed": 2,
                "timestamp": "2026-08-15T12:00:00+00:00",
                "inputs": ["external/evil_link.png"],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    paths = {a["path"] for a in plan.assets}
    assert "external/evil_link.png" not in paths
    assert not any("evil_link" in p for p in paths)
    assert not any(a.get("role") == "edit_source" for a in plan.assets)
    issues = plan.report.get("issues") or []
    assert issues
    issue_text = " ".join(str(i) for i in issues).lower()
    assert "escape" in issue_text or "symlink" in issue_text or "missing" in issue_text


def test_output_symlink_outside_workspace_rejected(tmp_workspace):
    """Generation output that is a symlink leaving the workspace must not be planned."""
    ws = tmp_workspace
    outside = ws.parent / "output_symlink_target_secret.png"
    outside.write_bytes(_make_png(b"\xde\xad\xbe"))
    outside_hash = media_backfill._file_sha256(outside)

    name = "gen_out_symlink.png"
    link = ws / "images" / "raw" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    (ws / "logs" / "gen_out_symlink.json").write_text(
        json.dumps(
            {
                "filename": name,
                "prompt": "output symlink escape",
                "model": "fal-ai/flux-2",
                "mode": "generate",
                "seed": 3,
                "timestamp": "2026-08-15T12:00:00+00:00",
                "inputs": [],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    paths = {a["path"] for a in plan.assets}
    assert f"images/raw/{name}" not in paths
    assert not any(name in p for p in paths)
    assert not any("output_symlink_target" in p for p in paths)
    # Must not create a generation run for that log
    assert not plan.runs
    assert not any(
        r.get("log_path") == "logs/gen_out_symlink.json" for r in plan.runs
    )
    issues = plan.report.get("issues") or []
    assert issues, "symlink output must appear as a report issue"
    issue_text = " ".join(str(i) for i in issues).lower()
    assert (
        "escape" in issue_text
        or "missing" in issue_text
        or "not confined" in issue_text
        or "confined" in issue_text
    )
    # Outside bytes must never be hashed into planning state via output_by_basename side effects
    for a in plan.assets:
        abs_path = ws / a["path"]
        if abs_path.is_file() and not abs_path.is_symlink():
            assert media_backfill._file_sha256(abs_path) != outside_hash


# ── 15. --apply fail-closed when Media config disabled ───────────────────────


def test_apply_fail_closed_when_media_disabled(tmp_workspace, monkeypatch):
    """--apply with Media disabled must exit non-zero and make zero upload/post calls."""
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    calls = {"upload": 0, "post": 0}

    def boom_upload(*a, **k):
        calls["upload"] += 1
        raise AssertionError("upload_asset must not run when Media disabled")

    def boom_post(*a, **k):
        calls["post"] += 1
        raise AssertionError("post_generation_run must not run when Media disabled")

    monkeypatch.setattr(media_backfill, "upload_asset", boom_upload)
    monkeypatch.setattr(media_backfill, "post_generation_run", boom_post)
    monkeypatch.delenv("MEDIA_API_URL", raising=False)
    monkeypatch.delenv("MEDIA_API_TOKEN_FILE", raising=False)

    class DisabledCfg:
        enabled = False
        api_url = None
        token = None
        timeout_seconds = 30

    monkeypatch.setattr(media_backfill, "load_config", lambda: DisabledCfg())

    report_path = ws / "report-disabled.json"
    rc = media_backfill.main(
        ["--workspace", str(ws), "--apply", "--report", str(report_path)]
    )
    assert rc == 2
    assert calls == {"upload": 0, "post": 0}
    assert report_path.is_file()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data.get("mode") == "apply-aborted"


# ── 16. Idempotency keys truncated to ≤160 (match upload_asset) ──────────────


def test_long_filename_idempotency_key_truncated_to_160(tmp_workspace):
    """Plan asset keys must match upload_asset truncation (idem[:160])."""
    ws = tmp_workspace
    long_name = ("x" * 200) + ".png"
    assert len(f"mediagen:asset:images/raw/{long_name}") > 160
    _write_bytes(ws / "images" / "raw" / long_name, _make_png(b"\x99\x88\x77"))
    (ws / "logs" / "long_name.json").write_text(
        json.dumps(
            {
                "filename": long_name,
                "prompt": "long name",
                "model": "fal-ai/flux-2",
                "mode": "generate",
                "seed": 1,
                "timestamp": "2026-08-15T12:00:00+00:00",
                "inputs": [],
            }
        ),
        encoding="utf-8",
    )

    plan = media_backfill.build_backfill_plan(ws)
    asset = next(a for a in plan.assets if a["path"].endswith(long_name))
    raw = media_client.asset_idempotency_key(asset["path"])
    expected = raw[:160]
    assert len(asset["idempotency_key"]) <= 160
    assert asset["idempotency_key"] == expected
    assert asset["idempotency_key"] == raw[:160]


# ── 17. --apply exits non-zero on total failure ──────────────────────────────


def test_apply_exits_nonzero_on_total_failure(tmp_workspace, monkeypatch):
    """If every upload/run fails under --apply, main exits non-zero."""
    ws = tmp_workspace
    img_name = "20260815T120000Z_flux2.png"
    _write_bytes(ws / "images" / "raw" / img_name, _make_png())
    _place_log(ws, "log-image-generate.json")

    def fail_upload(*a, **k):
        raise RuntimeError("upload failed")

    def fail_post(*a, **k):
        raise RuntimeError("post failed")

    class Cfg:
        enabled = True
        api_url = "https://example.test"
        token = "x"
        timeout_seconds = 30

    monkeypatch.setattr(media_backfill, "load_config", lambda: Cfg())
    monkeypatch.setattr(media_backfill, "upload_asset", fail_upload)
    monkeypatch.setattr(media_backfill, "post_generation_run", fail_post)

    report_path = ws / "report-fail.json"
    rc = media_backfill.main(
        ["--workspace", str(ws), "--apply", "--report", str(report_path)]
    )
    assert rc != 0
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data.get("mode") == "apply"
    assert data.get("apply", {}).get("uploaded", 0) == 0
    assert data.get("apply", {}).get("runs_ok", 0) == 0
