"""F3: mediagen hooks media_client after persist without breaking Telegram contract.

No live Media/fal. Mock media_client / HTTP only.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import media_client
import mediagen


def _png_bytes() -> bytes:
    # Minimal valid-ish PNG header + payload (not decoded by mediagen)
    return b"\x89PNG\r\n\x1a\nfake-png-bytes"


def _setup_workspace(ws: Path) -> None:
    mediagen.WORKSPACE = ws
    mediagen.IMAGES_DIR = ws / "images"
    mediagen.RAW_DIR = ws / "images" / "raw"
    mediagen.VIDEOS_DIR = ws / "videos"
    mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
    mediagen.EXTERNAL_DIR = ws / "external"
    mediagen.LOGS_DIR = ws / "logs"
    for d in (
        mediagen.RAW_DIR,
        mediagen.VIDEOS_RAW_DIR,
        mediagen.EXTERNAL_DIR,
        mediagen.LOGS_DIR,
        mediagen.IMAGES_DIR,
        mediagen.VIDEOS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def _image_args(**overrides):
    defaults = {
        "prompt": "a test prompt",
        "width": 1280,
        "height": 720,
        "model": "flux2",
        "seed": 42,
        "quality": "medium",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestWorkspaceRelpath:
    def test_relative_inside_workspace(self, tmp_path):
        _setup_workspace(tmp_path)
        p = tmp_path / "images" / "raw" / "out.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_png_bytes())
        assert mediagen.workspace_relpath(p) == "images/raw/out.png"

    def test_already_relative(self, tmp_path):
        _setup_workspace(tmp_path)
        assert mediagen.workspace_relpath("logs/foo.json") == "logs/foo.json"


class TestBuildImageMediaPayload:
    def test_edit_multi_input_roles_by_position(self, tmp_path):
        _setup_workspace(tmp_path)
        in0 = tmp_path / "external" / "a.png"
        in1 = tmp_path / "external" / "b.png"
        in0.write_bytes(_png_bytes())
        in1.write_bytes(_png_bytes() + b"2")
        out = tmp_path / "images" / "raw" / "out.png"
        out.write_bytes(_png_bytes())

        assets, generation = mediagen.build_media_sync_payload(
            kind="image",
            mode="edit",
            model="flux2",
            endpoint="fal-ai/flux-2/edit",
            prompt="edit me",
            seed=7,
            output_path=out,
            input_md_entries=[
                {"path": str(in0), "original": "/tmp/a.png"},
                {"path": str(in1), "original": "/tmp/b.png"},
            ],
            end_md_entry=None,
            params={"endpoint": "fal-ai/flux-2/edit", "width": 1280, "height": 720},
        )

        assert generation["operation"] == "edit"
        assert generation["provider"] == "fal"
        assert generation["model"] == "flux2"
        assert generation["inputs"] == [
            {"path": "external/a.png", "role": "edit_source", "position": 0},
            {"path": "external/b.png", "role": "edit_source", "position": 1},
        ]
        assert generation["outputs"] == [{"path": "images/raw/out.png", "position": 0}]

        # Assets include inputs + output; never markdown
        paths = [a["path"] for a in assets]
        assert paths == ["external/a.png", "external/b.png", "images/raw/out.png"]
        assert all(not p.endswith(".md") for p in paths)
        assert assets[0]["role"] == "edit_source" and assets[0]["position"] == 0
        assert assets[1]["role"] == "edit_source" and assets[1]["position"] == 1
        assert assets[0]["origin"] == "external_import"
        assert assets[0]["show_in_grid"] is False
        assert assets[-1]["kind"] == "image"
        assert assets[-1].get("origin", "mediagen_generation") == "mediagen_generation"

    def test_generate_has_no_inputs(self, tmp_path):
        _setup_workspace(tmp_path)
        out = tmp_path / "images" / "raw" / "gen.png"
        out.write_bytes(_png_bytes())
        assets, generation = mediagen.build_media_sync_payload(
            kind="image",
            mode="generate",
            model="nano2",
            endpoint="fal-ai/nano-banana-2",
            prompt="hello",
            seed=None,
            output_path=out,
            input_md_entries=[],
            end_md_entry=None,
            params={"endpoint": "fal-ai/nano-banana-2"},
        )
        assert generation["operation"] == "generate"
        assert generation["inputs"] == []
        assert len(assets) == 1
        assert assets[0]["path"] == "images/raw/gen.png"


class TestBuildVideoMediaPayload:
    def test_i2v_start_and_end_frame_roles(self, tmp_path):
        _setup_workspace(tmp_path)
        start = tmp_path / "external" / "start.png"
        end = tmp_path / "external" / "end.png"
        start.write_bytes(_png_bytes())
        end.write_bytes(_png_bytes() + b"e")
        out = tmp_path / "videos" / "raw" / "clip.mp4"
        out.write_bytes(b"fake-mp4")

        assets, generation = mediagen.build_media_sync_payload(
            kind="video",
            mode="image-to-video",
            model="seedance2",
            endpoint="fal-ai/bytedance/seedance/v1.5/pro/image-to-video",
            prompt="move",
            seed=99,
            output_path=out,
            input_md_entries=[{"path": str(start), "original": "/tmp/start.png"}],
            end_md_entry={"path": str(end), "original": "/tmp/end.png"},
            params={"endpoint": "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"},
        )

        assert generation["operation"] == "image-to-video"
        assert generation["inputs"] == [
            {"path": "external/start.png", "role": "start_frame", "position": 0},
            {"path": "external/end.png", "role": "end_frame", "position": 1},
        ]
        assert generation["outputs"] == [{"path": "videos/raw/clip.mp4", "position": 0}]
        roles = [(a["path"], a.get("role")) for a in assets if a.get("role")]
        assert ("external/start.png", "start_frame") in roles
        assert ("external/end.png", "end_frame") in roles
        assert assets[-1]["kind"] == "video"
        assert all(not a["path"].endswith(".md") for a in assets)

    def test_text_to_video_no_inputs(self, tmp_path):
        _setup_workspace(tmp_path)
        out = tmp_path / "videos" / "raw" / "t2v.mp4"
        out.write_bytes(b"fake-mp4")
        assets, generation = mediagen.build_media_sync_payload(
            kind="video",
            mode="text-to-video",
            model="seedance2",
            endpoint="fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
            prompt="ball",
            seed=1,
            output_path=out,
            input_md_entries=[],
            end_md_entry=None,
            params={"endpoint": "fal-ai/bytedance/seedance/v1.5/pro/text-to-video"},
        )
        assert generation["operation"] == "text-to-video"
        assert generation["inputs"] == []
        assert [a["path"] for a in assets] == ["videos/raw/t2v.mp4"]


class TestFinalizeAfterPersist:
    def test_media_api_down_preserves_file_log_receipt_stdout_and_no_raise(
        self, tmp_path, monkeypatch, capsys
    ):
        _setup_workspace(tmp_path)
        token = tmp_path / "token"
        token.write_text("test-bearer-token\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", "https://media.example.test")
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))
        monkeypatch.setenv("MEDIA_UPLOAD_TIMEOUT_SECONDS", "3")

        # Simulate Media API down (network error)
        def boom(req, timeout=None):
            raise media_client.urllib.error.URLError("Connection refused")

        monkeypatch.setattr(media_client.urllib.request, "urlopen", boom)

        image_path = mediagen.RAW_DIR / "20260815_120000_flux2.png"
        image_path.write_bytes(_png_bytes())
        args = _image_args()

        meta = mediagen._write_image_artifacts(
            image_path=image_path,
            base_name="20260815_120000_flux2",
            image_filename="20260815_120000_flux2.png",
            args=args,
            mode="generate",
            endpoint="fal-ai/flux-2",
            seed_display=42,
            size_str="1280x720",
            input_md_entries=[],
            log_extra={"fal_response": {"seed": 42}},
        )
        # Writer must NOT print FILENAME yet — finalize does
        assert "FILENAME=" not in capsys.readouterr().out

        mediagen.finalize_generation_with_media_sync(meta)
        out = capsys.readouterr().out.strip().splitlines()
        assert out[-1] == "FILENAME=20260815_120000_flux2.png PROMPT=a test prompt SEED=42"

        # File + log intact
        assert image_path.is_file()
        log_path = mediagen.LOGS_DIR / "20260815_120000_flux2.json"
        assert log_path.is_file()
        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert log["filename"] == "20260815_120000_flux2.png"

        # Receipt created (pending) despite API down
        receipts_dir = tmp_path / "receipts"
        assert receipts_dir.is_dir()
        receipt_files = list(receipts_dir.glob("*.json"))
        assert len(receipt_files) == 1
        receipt = json.loads(receipt_files[0].read_text(encoding="utf-8"))
        assert receipt["status"] == "pending"
        assert receipt["log_path"] == "logs/20260815_120000_flux2.json"
        assert any(a["path"] == "images/raw/20260815_120000_flux2.png" for a in receipt["assets"])
        # Never store token
        assert "test-bearer-token" not in json.dumps(receipt)

        # Markdown may exist but is not a Media asset
        md_path = mediagen.IMAGES_DIR / "20260815_120000_flux2.md"
        assert md_path.is_file()
        assert all(not a["path"].endswith(".md") for a in receipt["assets"])

    def test_missing_config_is_noop_still_prints_filename(self, tmp_path, monkeypatch, capsys):
        _setup_workspace(tmp_path)
        monkeypatch.delenv("MEDIA_API_URL", raising=False)
        monkeypatch.delenv("MEDIA_API_TOKEN_FILE", raising=False)

        image_path = mediagen.RAW_DIR / "out.png"
        image_path.write_bytes(_png_bytes())
        meta = mediagen._write_image_artifacts(
            image_path=image_path,
            base_name="out",
            image_filename="out.png",
            args=_image_args(prompt="p"),
            mode="generate",
            endpoint="fal-ai/flux-2",
            seed_display="random",
            size_str="1280x720",
            input_md_entries=[],
            log_extra={},
        )
        mediagen.finalize_generation_with_media_sync(meta)
        line = capsys.readouterr().out.strip().splitlines()[-1]
        assert line == "FILENAME=out.png PROMPT=p SEED=random"
        assert not (tmp_path / "receipts").exists()

    def test_sync_exception_does_not_change_success_path(self, tmp_path, monkeypatch, capsys):
        _setup_workspace(tmp_path)
        token = tmp_path / "token"
        token.write_text("tok\n", encoding="utf-8")
        monkeypatch.setenv("MEDIA_API_URL", "https://media.example.test")
        monkeypatch.setenv("MEDIA_API_TOKEN_FILE", str(token))

        def explode(*_a, **_k):
            raise RuntimeError("unexpected media client crash")

        monkeypatch.setattr(mediagen, "sync_if_enabled", explode)

        image_path = mediagen.RAW_DIR / "x.png"
        image_path.write_bytes(_png_bytes())
        meta = mediagen._write_image_artifacts(
            image_path=image_path,
            base_name="x",
            image_filename="x.png",
            args=_image_args(prompt="ok"),
            mode="generate",
            endpoint="fal-ai/flux-2",
            seed_display=1,
            size_str="1x1",
            input_md_entries=[],
            log_extra={},
        )
        # Must not raise
        mediagen.finalize_generation_with_media_sync(meta)
        assert capsys.readouterr().out.strip().splitlines()[-1] == (
            "FILENAME=x.png PROMPT=ok SEED=1"
        )
        assert image_path.is_file()

    def test_video_writer_then_finalize_contract(self, tmp_path, monkeypatch, capsys):
        _setup_workspace(tmp_path)
        monkeypatch.delenv("MEDIA_API_URL", raising=False)
        monkeypatch.delenv("MEDIA_API_TOKEN_FILE", raising=False)

        video_path = mediagen.VIDEOS_RAW_DIR / "clip.mp4"
        video_path.write_bytes(b"mp4")
        args = SimpleNamespace(
            prompt="go",
            model="seedance2",
            seed=None,
            resolution="720p",
            duration=5,
            aspect_ratio="16:9",
            no_audio=False,
            camera_fixed=False,
        )
        meta = mediagen._write_video_artifacts(
            video_path=video_path,
            base_name="clip",
            video_filename="clip.mp4",
            args=args,
            mode="text-to-video",
            endpoint="fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
            returned_seed=None,
            input_md_entries=[],
            end_md_entry=None,
            result={"video": {"url": "https://example.test/v.mp4"}},
        )
        assert "FILENAME=" not in capsys.readouterr().out
        mediagen.finalize_generation_with_media_sync(meta)
        assert capsys.readouterr().out.strip().splitlines()[-1] == (
            "FILENAME=clip.mp4 PROMPT=go SEED=random"
        )
        assert (mediagen.LOGS_DIR / "clip.json").is_file()
        assert (mediagen.VIDEOS_DIR / "clip.md").is_file()

    def test_provider_failure_does_not_upload(self, tmp_path, monkeypatch):
        """Generation/provider failure must not upload a fake asset."""
        _setup_workspace(tmp_path)
        calls = []

        def track_sync(*_a, **_k):
            calls.append(True)
            return None

        monkeypatch.setattr(mediagen, "sync_if_enabled", track_sync)
        monkeypatch.setattr(mediagen, "load_config", lambda: MagicMock(enabled=True))

        # Simulate fal failure path: run_image_fal exits before finalize
        fal = MagicMock()
        fal.subscribe.side_effect = RuntimeError("provider down")
        monkeypatch.setattr(mediagen, "require_fal_client", lambda: fal)

        args = SimpleNamespace(
            prompt="x",
            model="flux2",
            inputs=None,
            width=1280,
            height=720,
            steps=28,
            seed=None,
            enable_web_search=False,
        )
        with pytest.raises(SystemExit) as ei:
            mediagen.run_image_fal(args)
        assert ei.value.code == 1
        assert calls == []
