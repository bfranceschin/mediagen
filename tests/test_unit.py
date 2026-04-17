"""Unit tests for mediagen pure functions — no API calls, no cost, fast."""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import mediagen


# ── width_height_to_aspect_ratio ──────────────────────────────────────────────

class TestAspectRatio:
    def test_standard_16_9(self):
        assert mediagen.width_height_to_aspect_ratio(1280, 720) == "16:9"

    def test_standard_4_3(self):
        assert mediagen.width_height_to_aspect_ratio(1024, 768) == "4:3"

    def test_square(self):
        assert mediagen.width_height_to_aspect_ratio(512, 512) == "1:1"

    def test_ultrawide(self):
        assert mediagen.width_height_to_aspect_ratio(2560, 1080) == "64:27"

    def test_nano2_common_sizes(self):
        """Verify common sizes used in the skill."""
        assert mediagen.width_height_to_aspect_ratio(1920, 1080) == "16:9"
        assert mediagen.width_height_to_aspect_ratio(1080, 1920) == "9:16"


# ── build_flux2_args ─────────────────────────────────────────────────────────

class TestBuildFlux2Args:
    def _make_args(self, **overrides):
        defaults = {
            "prompt": "test prompt",
            "width": 1280,
            "height": 720,
            "steps": 28,
            "seed": None,
            "enable_web_search": False,
            "image_urls": [],
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_generate_mode_basic(self):
        args = self._make_args()
        result = mediagen.build_flux2_args(args, "generate")
        assert result["prompt"] == "test prompt"
        assert result["image_size"] == {"width": 1280, "height": 720}
        assert result["num_inference_steps"] == 28
        assert result["num_images"] == 1
        assert result["output_format"] == "png"
        assert result["enable_safety_checker"] is False
        assert "image_urls" not in result

    def test_generate_mode_with_seed(self):
        args = self._make_args(seed=42)
        result = mediagen.build_flux2_args(args, "generate")
        assert result["seed"] == 42

    def test_generate_mode_no_seed(self):
        args = self._make_args(seed=None)
        result = mediagen.build_flux2_args(args, "generate")
        assert "seed" not in result

    def test_edit_mode_includes_image_urls(self):
        args = self._make_args(image_urls=["https://example.com/img.png"])
        result = mediagen.build_flux2_args(args, "edit")
        assert result["image_urls"] == ["https://example.com/img.png"]

    def test_custom_dimensions(self):
        args = self._make_args(width=1920, height=1080, steps=40)
        result = mediagen.build_flux2_args(args, "generate")
        assert result["image_size"] == {"width": 1920, "height": 1080}
        assert result["num_inference_steps"] == 40


# ── build_nano2_args ─────────────────────────────────────────────────────────

class TestBuildNano2Args:
    def _make_args(self, **overrides):
        defaults = {
            "prompt": "nano test",
            "width": 1280,
            "height": 720,
            "seed": None,
            "enable_web_search": False,
            "image_urls": [],
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_generate_mode_basic(self):
        args = self._make_args()
        result = mediagen.build_nano2_args(args, "generate")
        assert result["prompt"] == "nano test"
        assert result["aspect_ratio"] == "16:9"
        assert result["num_images"] == 1
        assert result["output_format"] == "png"
        assert result["safety_tolerance"] == "6"
        assert "enable_web_search" not in result

    def test_web_search_enabled(self):
        args = self._make_args(enable_web_search=True)
        result = mediagen.build_nano2_args(args, "generate")
        assert result["enable_web_search"] is True

    def test_web_search_disabled_by_default(self):
        args = self._make_args(enable_web_search=False)
        result = mediagen.build_nano2_args(args, "generate")
        assert "enable_web_search" not in result

    def test_edit_mode_includes_image_urls(self):
        args = self._make_args(image_urls=["https://example.com/a.png", "https://example.com/b.png"])
        result = mediagen.build_nano2_args(args, "edit")
        assert result["image_urls"] == ["https://example.com/a.png", "https://example.com/b.png"]

    def test_seed_included_when_provided(self):
        args = self._make_args(seed=99)
        result = mediagen.build_nano2_args(args, "generate")
        assert result["seed"] == 99

    def test_seed_absent_when_none(self):
        args = self._make_args(seed=None)
        result = mediagen.build_nano2_args(args, "generate")
        assert "seed" not in result


# ── copy_to_external ──────────────────────────────────────────────────────────

class TestCopyToExternal:
    def test_copies_file_to_external(self, tmp_workspace, sample_image):
        """copy_to_external should copy the file to the external/ dir."""
        mediagen.EXTERNAL_DIR = tmp_workspace / "external"
        result = mediagen.copy_to_external(str(sample_image))
        assert result == tmp_workspace / "external" / "test_input.png"
        assert result.exists()
        assert result.read_bytes() == sample_image.read_bytes()

    def test_raises_on_missing_file(self, tmp_workspace):
        """copy_to_external should exit if file doesn't exist."""
        mediagen.EXTERNAL_DIR = tmp_workspace / "external"
        import pytest
        with pytest.raises(SystemExit):
            mediagen.copy_to_external("/nonexistent/path.png")

    def test_same_file_not_duplicated(self, tmp_workspace, sample_image):
        """If the file is already in external/, don't copy again."""
        mediagen.EXTERNAL_DIR = tmp_workspace / "external"
        # First copy
        result1 = mediagen.copy_to_external(str(sample_image))
        # Second copy of same dest — should not error
        result2 = mediagen.copy_to_external(str(result1))
        assert result2 == result1


# ── ensure_dirs ───────────────────────────────────────────────────────────────

class TestEnsureDirs:
    def test_creates_directories(self, tmp_path):
        """ensure_dirs should create all required workspace dirs."""
        ws = tmp_path / "test_workspace"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"

        mediagen.ensure_dirs()

        assert (ws / "images" / "raw").is_dir()
        assert (ws / "external").is_dir()
        assert (ws / "logs").is_dir()

    def test_idempotent(self, tmp_path):
        """ensure_dirs should not fail if dirs already exist."""
        ws = tmp_path / "test_workspace2"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"

        mediagen.ensure_dirs()
        mediagen.ensure_dirs()  # second call — no error

        assert (ws / "images" / "raw").is_dir()
