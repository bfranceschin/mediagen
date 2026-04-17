"""Unit tests for mediagen pure functions — no API calls, no cost, fast."""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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


# ── build_seedance2_args ─────────────────────────────────────────────────────

class TestBuildSeedance2Args:
    def _make_args(self, **overrides):
        defaults = {
            "prompt": "video test",
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration": 5,
            "no_audio": False,
            "camera_fixed": False,
            "seed": None,
            "image_url": None,
            "end_image_url": None,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_text_to_video_basic(self):
        args = self._make_args()
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["prompt"] == "video test"
        assert result["aspect_ratio"] == "16:9"
        assert result["resolution"] == "720p"
        assert result["duration"] == "5"
        assert result["enable_audio"] is True
        assert result["enable_safety_checker"] is False
        assert "static_video" not in result
        assert "image_url" not in result
        assert "end_image_url" not in result
        assert "seed" not in result

    def test_no_audio_flag(self):
        args = self._make_args(no_audio=True)
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["enable_audio"] is False

    def test_camera_fixed_flag(self):
        args = self._make_args(camera_fixed=True)
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["static_video"] is True

    def test_camera_not_fixed_by_default(self):
        args = self._make_args(camera_fixed=False)
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert "static_video" not in result

    def test_seed_included_when_provided(self):
        args = self._make_args(seed=42)
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["seed"] == 42

    def test_seed_absent_when_none(self):
        args = self._make_args(seed=None)
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert "seed" not in result

    def test_image_to_video_includes_image_url(self):
        args = self._make_args(image_url="https://example.com/start.png")
        result = mediagen.build_seedance2_args(args, "image-to-video")
        assert result["image_url"] == "https://example.com/start.png"

    def test_image_to_video_with_end_image(self):
        args = self._make_args(
            image_url="https://example.com/start.png",
            end_image_url="https://example.com/end.png",
        )
        result = mediagen.build_seedance2_args(args, "image-to-video")
        assert result["image_url"] == "https://example.com/start.png"
        assert result["end_image_url"] == "https://example.com/end.png"

    def test_image_to_video_without_end_image(self):
        args = self._make_args(image_url="https://example.com/start.png", end_image_url=None)
        result = mediagen.build_seedance2_args(args, "image-to-video")
        assert "end_image_url" not in result

    def test_custom_aspect_ratio(self):
        args = self._make_args(aspect_ratio="9:16")
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["aspect_ratio"] == "9:16"

    def test_custom_resolution(self):
        args = self._make_args(resolution="1080p")
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["resolution"] == "1080p"

    def test_duration_converted_to_string(self):
        args = self._make_args(duration=10)
        result = mediagen.build_seedance2_args(args, "text-to-video")
        assert result["duration"] == "10"
        assert isinstance(result["duration"], str)


# ── validate_args ────────────────────────────────────────────────────────────

class TestValidateArgs:
    def _make_image_args(self, **overrides):
        defaults = {
            "model": "flux2",
            "width": 1280,
            "height": 720,
            "steps": 28,
            "enable_web_search": False,
            "inputs": None,
            "end_image": None,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 5,
            "camera_fixed": False,
            "no_audio": False,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def _make_video_args(self, **overrides):
        defaults = {
            "model": "seedance2",
            "width": 1280,
            "height": 720,
            "steps": 28,
            "enable_web_search": False,
            "inputs": None,
            "end_image": None,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 5,
            "camera_fixed": False,
            "no_audio": False,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_valid_image_args_pass(self):
        """Basic image args should not raise."""
        args = self._make_image_args()
        mediagen.validate_args(args)  # should not exit

    def test_valid_video_args_pass(self):
        """Basic video args should not raise."""
        args = self._make_video_args()
        mediagen.validate_args(args)  # should not exit

    def test_video_duration_too_low(self):
        """Duration < 4 should fail."""
        args = self._make_video_args(duration=3)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_video_duration_too_high(self):
        """Duration > 12 should fail."""
        args = self._make_video_args(duration=13)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_video_duration_boundary_low(self):
        """Duration = 4 should pass."""
        args = self._make_video_args(duration=4)
        mediagen.validate_args(args)  # should not exit

    def test_video_duration_boundary_high(self):
        """Duration = 12 should pass."""
        args = self._make_video_args(duration=12)
        mediagen.validate_args(args)  # should not exit

    def test_video_end_image_without_inputs(self):
        """End image without start image should fail."""
        args = self._make_video_args(end_image="/path/to/end.png", inputs=None)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_video_multiple_inputs(self):
        """Image-to-video with >1 input should fail."""
        args = self._make_video_args(inputs=["/a.png", "/b.png"])
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_video_single_input_passes(self):
        """Image-to-video with exactly 1 input should pass."""
        args = self._make_video_args(inputs=["/a.png"])
        mediagen.validate_args(args)  # should not exit

    def test_image_model_with_camera_fixed(self):
        """camera_fixed with image model should fail."""
        args = self._make_image_args(camera_fixed=True)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_image_model_with_no_audio(self):
        """no_audio with image model should fail."""
        args = self._make_image_args(no_audio=True)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_image_model_with_end_image(self):
        """end_image with image model should fail."""
        args = self._make_image_args(end_image="/path/end.png")
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_video_model_with_enable_web_search(self):
        """enable_web_search with video model should fail."""
        args = self._make_video_args(enable_web_search=True)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_image_edit_max_4_inputs(self):
        """Image edit with >4 inputs should fail."""
        args = self._make_image_args(inputs=["/a.png", "/b.png", "/c.png", "/d.png", "/e.png"])
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)

    def test_image_edit_4_inputs_passes(self):
        """Image edit with exactly 4 inputs should pass."""
        args = self._make_image_args(inputs=["/a.png", "/b.png", "/c.png", "/d.png"])
        mediagen.validate_args(args)  # should not exit


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
    def test_creates_image_directories(self, tmp_path):
        """ensure_dirs for images should create raw/ dir."""
        ws = tmp_path / "test_workspace"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"

        mediagen.ensure_dirs(media_type="image")

        assert (ws / "images" / "raw").is_dir()
        assert (ws / "external").is_dir()
        assert (ws / "logs").is_dir()
        # videos/raw should NOT be created for image mode
        assert not (ws / "videos" / "raw").exists()

    def test_creates_video_directories(self, tmp_path):
        """ensure_dirs for videos should create videos/raw/ dir."""
        ws = tmp_path / "test_workspace2"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"

        mediagen.ensure_dirs(media_type="video")

        assert (ws / "videos" / "raw").is_dir()
        assert (ws / "external").is_dir()
        assert (ws / "logs").is_dir()
        # images/raw should NOT be created for video mode
        assert not (ws / "images" / "raw").exists()

    def test_idempotent(self, tmp_path):
        """ensure_dirs should not fail if dirs already exist."""
        ws = tmp_path / "test_workspace3"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.VIDEOS_RAW_DIR = ws / "videos" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"

        mediagen.ensure_dirs(media_type="image")
        mediagen.ensure_dirs(media_type="image")  # second call — no error

        assert (ws / "images" / "raw").is_dir()


# ── Model routing ─────────────────────────────────────────────────────────────

class TestModelRouting:
    def test_image_models_set(self):
        assert mediagen.IMAGE_MODELS == {"flux2", "nano2"}

    def test_video_models_set(self):
        assert mediagen.VIDEO_MODELS == {"seedance2"}

    def test_model_map_has_all_models(self):
        for m in mediagen.IMAGE_MODELS | mediagen.VIDEO_MODELS:
            assert m in mediagen.MODEL_MAP

    def test_seedance2_endpoints(self):
        assert "text-to-video" in mediagen.MODEL_MAP["seedance2"]
        assert "image-to-video" in mediagen.MODEL_MAP["seedance2"]
        assert "fal-ai/bytedance/seedance/v1.5/pro/text-to-video" in mediagen.MODEL_MAP["seedance2"]["text-to-video"]
        assert "fal-ai/bytedance/seedance/v1.5/pro/image-to-video" in mediagen.MODEL_MAP["seedance2"]["image-to-video"]

    def test_timeouts(self):
        assert mediagen.IMAGE_TIMEOUT_SECONDS == 120
        assert mediagen.VIDEO_TIMEOUT_SECONDS == 300
