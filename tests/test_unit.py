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


# ── build_grokimage2_args / build_grokvideo_args ─────────────────────────────

class TestBuildGrokImage2Args:
    def _make_args(self, **overrides):
        defaults = {
            "prompt": "grok image",
            "width": 1280,
            "height": 720,
            "quality": "medium",
            "image_data_urls": [],
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_generate_maps_1280x720_and_quality(self):
        result = mediagen.build_grokimage2_args(self._make_args(), "generate")
        assert result["model"] == "grok-imagine-image-2.0"
        assert result["prompt"] == "grok image"
        assert result["aspect_ratio"] == "16:9"
        assert result["resolution"] == "1k"
        assert result["quality"] == "medium"
        assert result["response_format"] == "b64_json"
        assert "image" not in result
        assert "images" not in result

    def test_generate_2k_when_long_edge_large(self):
        result = mediagen.build_grokimage2_args(
            self._make_args(width=1920, height=1080, quality="low"), "generate"
        )
        assert result["resolution"] == "2k"
        assert result["quality"] == "low"

    def test_edit_single_image_field(self):
        args = self._make_args(image_data_urls=["data:image/png;base64,abc"])
        result = mediagen.build_grokimage2_args(args, "edit")
        assert result["image"] == {"url": "data:image/png;base64,abc", "type": "image_url"}
        assert "images" not in result

    def test_edit_multiple_images_field(self):
        args = self._make_args(
            image_data_urls=["data:image/png;base64,a", "data:image/png;base64,b"]
        )
        result = mediagen.build_grokimage2_args(args, "edit")
        assert result["images"] == [
            {"url": "data:image/png;base64,a", "type": "image_url"},
            {"url": "data:image/png;base64,b", "type": "image_url"},
        ]
        assert "image" not in result


class TestBuildGrokVideoArgs:
    def _make_args(self, **overrides):
        defaults = {
            "prompt": "grok video",
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration": 5,
            "image_data_url": None,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_text_to_video_uses_int_duration(self):
        result = mediagen.build_grokvideo_args(self._make_args(), "text-to-video")
        assert result["model"] == "grok-imagine-video-1.5"
        assert result["prompt"] == "grok video"
        assert result["aspect_ratio"] == "16:9"
        assert result["resolution"] == "720p"
        assert result["duration"] == 5
        assert isinstance(result["duration"], int)
        assert "image" not in result

    def test_image_to_video_includes_start_frame(self):
        args = self._make_args(image_data_url="data:image/png;base64,frame")
        result = mediagen.build_grokvideo_args(args, "image-to-video")
        assert result["image"] == {"url": "data:image/png;base64,frame", "type": "image_url"}


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


class TestValidateGrokArgs:
    def _make_image_args(self, **overrides):
        defaults = {
            "model": "grokimage2",
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
            "quality": "medium",
            "seed": None,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def _make_video_args(self, **overrides):
        defaults = {
            "model": "grokvideo",
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
            "quality": "medium",
            "seed": None,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_grokimage2_quality_medium_passes(self):
        mediagen.validate_args(self._make_image_args(quality="medium"))

    def test_grokimage2_quality_low_passes(self):
        mediagen.validate_args(self._make_image_args(quality="low"))

    def test_grokimage2_quality_high_fails(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(self._make_image_args(quality="high"))

    def test_grokimage2_edit_3_inputs_passes(self):
        mediagen.validate_args(self._make_image_args(inputs=["/a.png", "/b.png", "/c.png"]))

    def test_grokimage2_edit_4_inputs_fails(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(
                self._make_image_args(inputs=["/a.png", "/b.png", "/c.png", "/d.png"])
            )

    def test_grokvideo_duration_1_passes(self):
        mediagen.validate_args(self._make_video_args(duration=1))

    def test_grokvideo_duration_15_passes(self):
        mediagen.validate_args(self._make_video_args(duration=15))

    def test_grokvideo_duration_0_fails(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(self._make_video_args(duration=0))

    def test_grokvideo_duration_16_fails(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(self._make_video_args(duration=16))

    def test_grokvideo_rejects_end_image(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(
                self._make_video_args(inputs=["/start.png"], end_image="/end.png")
            )

    def test_grokvideo_rejects_camera_fixed(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(self._make_video_args(camera_fixed=True))

    def test_grokvideo_rejects_no_audio(self):
        with pytest.raises(SystemExit):
            mediagen.validate_args(self._make_video_args(no_audio=True))

    def test_grokvideo_single_input_passes(self):
        mediagen.validate_args(self._make_video_args(inputs=["/start.png"]))

    def test_seedance_duration_3_still_fails(self):
        args = self._make_video_args(model="seedance2", duration=3)
        with pytest.raises(SystemExit):
            mediagen.validate_args(args)


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
        assert mediagen.IMAGE_MODELS == {"flux2", "nano2", "gptimage2", "grokimage2"}

    def test_video_models_set(self):
        assert mediagen.VIDEO_MODELS == {"seedance2", "grokvideo"}

    def test_model_map_has_all_models(self):
        for m in mediagen.IMAGE_MODELS | mediagen.VIDEO_MODELS:
            assert m in mediagen.MODEL_MAP

    
    def test_gptimage2_endpoints(self):
        assert "generate" in mediagen.MODEL_MAP["gptimage2"]
        assert "edit" in mediagen.MODEL_MAP["gptimage2"]
        assert mediagen.MODEL_MAP["gptimage2"]["generate"] == "openai-codex/gpt-image-2"
        assert mediagen.MODEL_MAP["gptimage2"]["edit"] == "openai-codex/gpt-image-2/edit"

    def test_grokimage2_endpoints(self):
        assert mediagen.MODEL_MAP["grokimage2"]["generate"] == "https://api.x.ai/v1/images/generations"
        assert mediagen.MODEL_MAP["grokimage2"]["edit"] == "https://api.x.ai/v1/images/edits"
        assert mediagen.GROK_IMAGE_API_MODEL == "grok-imagine-image-2.0"

    def test_grokvideo_endpoints(self):
        assert mediagen.MODEL_MAP["grokvideo"]["text-to-video"] == "https://api.x.ai/v1/videos/generations"
        assert mediagen.MODEL_MAP["grokvideo"]["image-to-video"] == "https://api.x.ai/v1/videos/generations"
        assert mediagen.GROK_VIDEO_API_MODEL == "grok-imagine-video-1.5"

    def test_gpt_aspect_mapping(self):
        assert mediagen.width_height_to_gpt_aspect(1536, 1024) == "landscape"
        assert mediagen.width_height_to_gpt_aspect(1024, 1024) == "square"
        assert mediagen.width_height_to_gpt_aspect(1024, 1536) == "portrait"
        assert mediagen.width_height_to_gpt_aspect(1280, 720) == "landscape"

    def test_seedance2_endpoints(self):
        assert "text-to-video" in mediagen.MODEL_MAP["seedance2"]
        assert "image-to-video" in mediagen.MODEL_MAP["seedance2"]
        assert "fal-ai/bytedance/seedance/v1.5/pro/text-to-video" in mediagen.MODEL_MAP["seedance2"]["text-to-video"]
        assert "fal-ai/bytedance/seedance/v1.5/pro/image-to-video" in mediagen.MODEL_MAP["seedance2"]["image-to-video"]

    def test_timeouts(self):
        assert mediagen.IMAGE_TIMEOUT_SECONDS == 120
        assert mediagen.VIDEO_TIMEOUT_SECONDS == 300


# ── Grok Imagine WxH mapping ─────────────────────────────────────────────────

class TestGrokImageSizeMapping:
    def test_default_1280x720_is_16_9_1k(self):
        assert mediagen.width_height_to_grok_aspect(1280, 720) == "16:9"
        assert mediagen.width_height_to_grok_resolution(1280, 720) == "1k"

    def test_max_edge_1536_is_2k(self):
        assert mediagen.width_height_to_grok_resolution(1536, 1024) == "2k"
        assert mediagen.width_height_to_grok_resolution(1024, 1536) == "2k"

    def test_below_1536_is_1k(self):
        assert mediagen.width_height_to_grok_resolution(1535, 1024) == "1k"
        assert mediagen.width_height_to_grok_resolution(1024, 1024) == "1k"

    def test_square_and_portrait(self):
        assert mediagen.width_height_to_grok_aspect(1024, 1024) == "1:1"
        assert mediagen.width_height_to_grok_aspect(720, 1280) == "9:16"

    def test_1920x1080_is_16_9_2k(self):
        assert mediagen.width_height_to_grok_aspect(1920, 1080) == "16:9"
        assert mediagen.width_height_to_grok_resolution(1920, 1080) == "2k"


class TestXaiProviderAndParse:
    def test_provider_from_xai_endpoint_is_not_fal(self):
        assert mediagen._provider_for_endpoint("https://api.x.ai/v1/images/generations") == "xai"
        assert mediagen._provider_for_endpoint("https://api.x.ai/v1/images/edits") == "xai"
        assert mediagen._provider_for_endpoint("https://api.x.ai/v1/videos/generations") == "xai"
        assert mediagen._provider_for_endpoint("fal-ai/flux-2") == "fal"
        assert mediagen._provider_for_endpoint("openai-codex/gpt-image-2") == "openai-codex"

    def test_provider_honors_oauth_override(self):
        assert mediagen._provider_for_endpoint(
            "https://api.x.ai/v1/images/generations", auth_provider="xai-oauth"
        ) == "xai-oauth"

    def test_extract_image_url_and_b64(self):
        assert mediagen.extract_xai_image_ref({"data": [{"url": "https://imgen.x.ai/tmp.png"}]}) == (
            "url",
            "https://imgen.x.ai/tmp.png",
        )
        assert mediagen.extract_xai_image_ref({"data": [{"b64_json": "abc123"}]}) == ("b64", "abc123")
        assert mediagen.extract_xai_image_ref({"data": []}) is None

    def test_sanitize_image_log_strips_b64(self):
        cleaned = mediagen.sanitize_xai_image_log(
            {"data": [{"url": "https://imgen.x.ai/x.png", "b64_json": "AAA" * 50}]}
        )
        assert cleaned["data"][0]["b64_json"] is True
        assert cleaned["data"][0]["url"] == "https://imgen.x.ai/x.png"

    def test_video_poll_terminal_statuses(self):
        assert mediagen.xai_video_status({"status": "done"}) == "done"
        assert mediagen.xai_video_status({"status": "failed"}) == "failed"
        assert mediagen.xai_video_status({"status": "expired"}) == "expired"
        assert mediagen.xai_video_status({"status": "pending"}) == "pending"

    def test_oauth_preferred_over_api_key(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "env-key")
        monkeypatch.setattr(
            mediagen,
            "_try_xai_http_credentials",
            lambda: {"provider": "xai-oauth", "api_key": "oauth-token", "base_url": "https://api.x.ai/v1"},
        )
        creds = mediagen.resolve_xai_credentials()
        assert creds["provider"] == "xai-oauth"
        assert creds["api_key"] == "oauth-token"

    def test_fallback_to_xai_api_key(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "env-key")
        monkeypatch.setattr(mediagen, "_try_xai_http_credentials", lambda: None)
        monkeypatch.setattr(mediagen, "_try_xai_oauth_runtime_credentials", lambda: None)
        creds = mediagen.resolve_xai_credentials()
        assert creds["provider"] == "xai"
        assert creds["api_key"] == "env-key"
        assert creds["base_url"] == "https://api.x.ai/v1"

    def test_run_image_xai_downloads_temp_url(self, tmp_path, monkeypatch, sample_image):
        ws = tmp_path / "ws"
        mediagen.WORKSPACE = ws
        mediagen.IMAGES_DIR = ws / "images"
        mediagen.RAW_DIR = ws / "images" / "raw"
        mediagen.EXTERNAL_DIR = ws / "external"
        mediagen.LOGS_DIR = ws / "logs"
        mediagen.ensure_dirs(media_type="image")

        monkeypatch.setattr(
            mediagen,
            "resolve_xai_credentials",
            lambda: {"provider": "xai-oauth", "api_key": "tok", "base_url": "https://api.x.ai/v1"},
        )

        def fake_post(url, payload, creds, timeout):
            assert url == "https://api.x.ai/v1/images/generations"
            assert payload["model"] == "grok-imagine-image-2.0"
            assert payload["quality"] == "low"
            return {"data": [{"url": "https://imgen.x.ai/xai-tmp-abc.png"}]}

        saved = {}

        def fake_download(url, dest, creds=None, timeout=None):
            saved["url"] = url
            dest.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        monkeypatch.setattr(mediagen, "_xai_post_json", fake_post)
        monkeypatch.setattr(mediagen, "download_xai_media", fake_download)
        monkeypatch.setattr(mediagen, "finalize_generation_with_media_sync", lambda meta: None)

        args = MagicMock(
            prompt="tiny blue square",
            width=1280,
            height=720,
            quality="low",
            inputs=None,
            model="grokimage2",
            seed=None,
        )
        mediagen.run_image_xai(args)
        assert saved["url"] == "https://imgen.x.ai/xai-tmp-abc.png"
        pngs = list((ws / "images" / "raw").glob("*.png"))
        assert len(pngs) == 1
        assert "grokimage2_low" in pngs[0].name

    def test_poll_video_stops_on_done(self):
        calls = {"n": 0}

        def get_json(_request_id):
            calls["n"] += 1
            if calls["n"] < 3:
                return {"status": "pending"}
            return {"status": "done", "video": {"url": "https://vidgen.x.ai/clip.mp4"}}

        sleeps = []
        body = mediagen.poll_xai_video("req-1", get_json=get_json, sleeper=sleeps.append, interval=1, timeout_seconds=10)
        assert body["status"] == "done"
        assert body["video"]["url"].endswith("clip.mp4")
        assert calls["n"] == 3
        assert sleeps == [1, 1]

    def test_download_xai_media_sends_bearer(self, tmp_path, monkeypatch):
        dest = tmp_path / "out.bin"
        seen = {}

        class FakeResp:
            status_code = 200
            content = b"media-bytes"

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                seen["url"] = url
                seen["headers"] = headers
                return FakeResp()

        class FakeHttpx:
            class Client(FakeClient):
                pass

        monkeypatch.setattr(mediagen, "_require_httpx", lambda: FakeHttpx)
        mediagen.download_xai_media(
            "https://imgen.x.ai/tmp.png",
            dest,
            {"api_key": "secret-token", "provider": "xai-oauth"},
        )
        assert dest.read_bytes() == b"media-bytes"
        assert seen["headers"]["Authorization"] == "Bearer secret-token"

    def test_poll_video_stops_on_failed(self):
        body = mediagen.poll_xai_video(
            "req-2",
            get_json=lambda _rid: {"status": "failed", "error": "nope"},
            sleeper=lambda _s: None,
            interval=1,
            timeout_seconds=5,
        )
        assert body["status"] == "failed"
