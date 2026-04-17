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


# ── Generate mode ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestFlux2Generate:
    """Test full FLUX.2 generation pipeline — real API call (~$0.01)."""

    def test_generate_returns_valid_output(self, tmp_path):
        """Generate a tiny image and verify all outputs are created."""
        ws = tmp_path / "mediagen"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs()

        # Use smallest reasonable size to minimize cost
        result = self._run_generate(
            model="flux2",
            prompt="a single red dot on white background, minimal",
            width=640,
            height=480,
            seed=42,
        )

        # Parse stdout
        assert "FILENAME=" in result
        assert "PROMPT=" in result
        filename = result.split("FILENAME=")[1].split()[0]
        assert filename.endswith(".png")

        # Verify image file exists and has content
        img_path = mediagen.RAW_DIR / filename
        assert img_path.exists()
        assert img_path.stat().st_size > 1000  # real PNG, not empty

        # Verify .md metadata file
        base = filename.replace(".png", "")
        md_path = mediagen.IMAGES_DIR / f"{base}.md"
        assert md_path.exists()
        md_content = md_path.read_text()
        assert "a single red dot" in md_content
        assert "flux2" in md_content
        assert "42" in md_content  # seed

        # Verify JSON log
        log_path = mediagen.LOGS_DIR / f"{base}.json"
        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert log_data["mode"] == "generate"
        assert log_data["model"] == "fal-ai/flux-2"
        assert log_data["seed"] == 42

    def _run_generate(self, model, prompt, width, height, seed):
        """Run mediagen.py as a subprocess to test the full CLI."""
        import subprocess
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "mediagen.py"),
            "--model", model,
            "--prompt", prompt,
            "--width", str(width),
            "--height", str(height),
            "--seed", str(seed),
        ]
        env = os.environ.copy()
        # Override workspace dir for test isolation
        env["MEDIAGEN_TEST_WORKSPACE"] = str(mediagen.WORKSPACE)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, env=env
        )
        if result.returncode != 0:
            pytest.fail(f"mediagen.py failed: {result.stdout}\n{result.stderr}")
        return result.stdout.strip()


@pytest.mark.integration
class TestNano2Generate:
    """Test full Nano Banana 2 generation pipeline — real API call (~$0.05)."""

    def test_generate_returns_valid_output(self, tmp_path):
        ws = tmp_path / "mediagen"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs()

        import subprocess
        cmd = [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "mediagen.py"),
            "--model", "nano2",
            "--prompt", "a blue square on white background",
            "--width", str(640),
            "--height", str(480),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            pytest.fail(f"mediagen.py failed: {result.stdout}\n{result.stderr}")

        output = result.stdout.strip()
        assert "FILENAME=" in output
        filename = output.split("FILENAME=")[1].split()[0]
        assert filename.endswith(".png")

        img_path = mediagen.RAW_DIR / filename
        assert img_path.exists()
        assert img_path.stat().st_size > 1000
