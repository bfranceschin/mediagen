"""Integration tests for mediagen — calls real fal.ai API (costs money).

Run with: pytest tests/test_integration.py -v

These tests are SKIPPED by default unless --run-integration flag is passed.
This prevents accidental API charges during normal test runs.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import mediagen


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: calls real fal.ai API (costs money, requires FAL_KEY)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --run-integration is passed."""
    if not config.getoption("--run-integration", default=False):
        skip_marker = pytest.mark.skip(reason="needs --run-integration flag to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_marker)


# ── Image Generate mode ──────────────────────────────────────────────────────

@pytest.mark.integration
class TestFlux2Generate:
    """Test full FLUX.2 generation pipeline — real API call (~$0.01)."""

    def test_generate_returns_valid_output(self, tmp_path):
        """Generate a tiny image and verify all outputs are created."""
        ws = tmp_path / "mediagen"
        self._setup_workspace(ws)

        result = self._run_script([
            "--model", "flux2",
            "--prompt", "a single red dot on white background, minimal",
            "--width", "640", "--height", "480",
            "--seed", "42",
        ], ws)

        self._assert_image_outputs(result, ws, model="flux2", mode="generate", seed=42)

    def _setup_workspace(self, ws):
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_DIR = ws / "videos"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs(media_type="image")

    def _run_script(self, args, ws):
        """Run mediagen.py as a subprocess to test the full CLI."""
        import subprocess
        cmd = [sys.executable, str(Path(__file__).parent.parent / "scripts" / "mediagen.py")] + args
        env = os.environ.copy()
        env["MEDIAGEN_WORKSPACE"] = str(ws)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        if result.returncode != 0:
            pytest.fail(f"mediagen.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
        return result.stdout.strip()

    def _assert_image_outputs(self, output, ws, model, mode, seed=None):
        """Verify image generation outputs."""
        assert "FILENAME=" in output
        assert "PROMPT=" in output
        filename = output.split("FILENAME=")[1].split()[0]
        assert filename.endswith(".png")

        # Verify image file
        img_path = ws / "images" / "raw" / filename
        assert img_path.exists()
        assert img_path.stat().st_size > 1000

        # Verify .md metadata
        base = filename.replace(".png", "")
        md_path = ws / "images" / f"{base}.md"
        assert md_path.exists()
        md_content = md_path.read_text()
        assert model in md_content
        if seed is not None:
            assert str(seed) in md_content

        # Verify JSON log
        log_path = ws / "logs" / f"{base}.json"
        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert log_data["mode"] == mode


@pytest.mark.integration
class TestNano2Generate:
    """Test full Nano Banana 2 generation pipeline — real API call (~$0.05)."""

    def test_generate_returns_valid_output(self, tmp_path):
        ws = tmp_path / "mediagen"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_DIR = ws / "videos"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs(media_type="image")

        import subprocess
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "mediagen.py"),
            "--model", "nano2",
            "--prompt", "a blue square on white background",
            "--width", "640", "--height", "480",
        ]
        env = os.environ.copy()
        env["MEDIAGEN_WORKSPACE"] = str(ws)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        if result.returncode != 0:
            pytest.fail(f"mediagen.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")

        output = result.stdout.strip()
        assert "FILENAME=" in output
        filename = output.split("FILENAME=")[1].split()[0]
        assert filename.endswith(".png")

        img_path = ws / "images" / "raw" / filename
        assert img_path.exists()
        assert img_path.stat().st_size > 1000


# ── Video Generate mode ──────────────────────────────────────────────────────

@pytest.mark.integration
class TestSeedance2TextToVideo:
    """Test full Seedance text-to-video pipeline — real API call (~$0.10-0.26)."""

    def test_text_to_video_returns_valid_output(self, tmp_path):
        ws = tmp_path / "mediagen"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_DIR = ws / "videos"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs(media_type="video")

        import subprocess
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "mediagen.py"),
            "--model", "seedance2",
            "--prompt", "a red ball bouncing once on white background",
            "--resolution", "480p",
            "--duration", "4",
            "--no-audio",
            "--seed", "42",
        ]
        env = os.environ.copy()
        env["MEDIAGEN_WORKSPACE"] = str(ws)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=360, env=env)
        if result.returncode != 0:
            pytest.fail(f"mediagen.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")

        output = result.stdout.strip()
        assert "FILENAME=" in output
        filename = output.split("FILENAME=")[1].split()[0]
        assert filename.endswith(".mp4")
        assert "_i2v" not in filename  # text-to-video, no i2v suffix

        # Verify video file
        vid_path = ws / "videos" / "raw" / filename
        assert vid_path.exists()
        assert vid_path.stat().st_size > 1000

        # Verify .md metadata
        base = filename.replace(".mp4", "")
        md_path = ws / "videos" / f"{base}.md"
        assert md_path.exists()
        md_content = md_path.read_text()
        assert "seedance" in md_content
        assert "480p" in md_content
        assert "4s" in md_content

        # Verify JSON log
        log_path = ws / "logs" / f"{base}.json"
        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert log_data["mode"] == "text-to-video"
        assert log_data["audio"] is False
        assert log_data["duration"] == 4


@pytest.mark.integration
class TestSeedance2ImageToVideo:
    """Test full Seedance image-to-video pipeline — real API call (~$0.10-0.26)."""

    def test_image_to_video_returns_valid_output(self, tmp_path):
        ws = tmp_path / "mediagen"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_DIR = ws / "videos"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs(media_type="image")
        mediagen.ensure_dirs(media_type="video")

        # First generate a source image
        import subprocess
        img_cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "mediagen.py"),
            "--model", "flux2",
            "--prompt", "a red ball on white background, still life",
            "--width", "640", "--height", "480",
            "--seed", "99",
        ]
        env = os.environ.copy()
        env["MEDIAGEN_WORKSPACE"] = str(ws)
        img_result = subprocess.run(img_cmd, capture_output=True, text=True, timeout=180, env=env)
        if img_result.returncode != 0:
            pytest.fail(f"Image generation failed:\n{img_result.stdout}\n{img_result.stderr}")

        img_filename = img_result.stdout.strip().split("FILENAME=")[1].split()[0]
        img_path = ws / "images" / "raw" / img_filename
        assert img_path.exists()

        # Now use that image as input for image-to-video
        vid_cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "mediagen.py"),
            "--model", "seedance2",
            "--prompt", "the ball bounces once",
            "--inputs", str(img_path),
            "--resolution", "480p",
            "--duration", "4",
            "--no-audio",
        ]
        vid_result = subprocess.run(vid_cmd, capture_output=True, text=True, timeout=360, env=env)
        if vid_result.returncode != 0:
            pytest.fail(f"Video generation failed:\nstdout: {vid_result.stdout}\nstderr: {vid_result.stderr}")

        output = vid_result.stdout.strip()
        assert "FILENAME=" in output
        filename = output.split("FILENAME=")[1].split()[0]
        assert filename.endswith(".mp4")
        assert "_i2v" in filename  # image-to-video has i2v suffix

        # Verify video file
        vid_path = ws / "videos" / "raw" / filename
        assert vid_path.exists()
        assert vid_path.stat().st_size > 1000

        # Verify JSON log
        base = filename.replace(".mp4", "")
        log_path = ws / "logs" / f"{base}.json"
        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert log_data["mode"] == "image-to-video"
