#!/usr/bin/env python3
"""mediagen.py — Image and video generation via fal.ai, ChatGPT Codex OAuth, and xAI Grok Imagine

Usage (image / fal.ai):
  python mediagen.py \
    --model <flux2|nano2> \
    --prompt "..." \
    [--inputs <path1> [<path2> ...]] \
    [--width 1280] \
    [--height 720] \
    [--steps 28] \
    [--seed 42] \
    [--enable-web-search]

Usage (image / GPT Image 2 via ChatGPT Codex OAuth):
  python mediagen.py \
    --model gptimage2 \
    --prompt "..." \
    [--inputs <path1> [<path2> ...]] \
    [--quality low|medium|high] \
    [--width 1280] [--height 720]

  Size is mapped from --width/--height to the nearest GPT Image aspect:
    landscape 1536x1024 | square 1024x1024 | portrait 1024x1536

  Auth: uses Hermes ChatGPT/Codex OAuth (hermes auth add openai-codex).
  Prefer Hermes venv Python so agent token helpers resolve:
    ~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/media/mediagen/scripts/mediagen.py ...

  If --inputs is provided → edit mode
  If --inputs is omitted   → generate mode

Usage (video):
  python mediagen.py \
    --model seedance2 \
    --prompt "..." \
    [--inputs <path>] \
    [--end-image <path>] \
    [--resolution <480p|720p|1080p>] \
    [--aspect-ratio <16:9|9:16|1:1|4:3|3:4|21:9|auto>] \
    [--duration <4..12>] \
    [--camera-fixed] \
    [--no-audio] \
    [--seed 42]

  If --inputs is provided → image-to-video mode
  If --inputs is omitted   → text-to-video mode

Output (stdout): FILENAME=<filename> PROMPT=<prompt> SEED=<seed>
Errors:          ERROR=<message> on first line, exit code 1
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from media_client import load_config as load_config
    from media_client import sync_if_enabled as sync_if_enabled
except ImportError:  # pragma: no cover — scripts/ always on path in normal installs
    load_config = None  # type: ignore[assignment]
    sync_if_enabled = None  # type: ignore[assignment]

# ── Constants ────────────────────────────────────────────────────────────────

WORKSPACE = Path(os.environ.get("MEDIAGEN_WORKSPACE", os.path.expanduser("~/.hermes/workspace/mediagen")))
IMAGES_DIR = WORKSPACE / "images"
RAW_DIR = IMAGES_DIR / "raw"
VIDEOS_DIR = WORKSPACE / "videos"
VIDEOS_RAW_DIR = VIDEOS_DIR / "raw"
EXTERNAL_DIR = WORKSPACE / "external"
LOGS_DIR = WORKSPACE / "logs"

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))).expanduser()
HERMES_AGENT_DIR = Path(
    os.environ.get("HERMES_AGENT_DIR", str(HERMES_HOME / "hermes-agent"))
).expanduser()

FAL_IMAGE_MODELS = {"flux2", "nano2"}
CODEX_IMAGE_MODELS = {"gptimage2"}
XAI_IMAGE_MODELS = {"grokimage2"}
IMAGE_MODELS = FAL_IMAGE_MODELS | CODEX_IMAGE_MODELS | XAI_IMAGE_MODELS
XAI_VIDEO_MODELS = {"grokvideo"}
VIDEO_MODELS = {"seedance2"} | XAI_VIDEO_MODELS

VALID_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "auto", "3:2", "2:3"}
SEEDANCE_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "auto"}
GROK_VIDEO_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
VALID_RESOLUTIONS = {"480p", "720p", "1080p"}
VALID_GPT_QUALITIES = {"low", "medium", "high"}
VALID_GROK_QUALITIES = {"low", "medium"}
GROK_MAX_REFERENCE_IMAGES = 3

MODEL_MAP = {
    "flux2": {
        "generate": "fal-ai/flux-2",
        "edit": "fal-ai/flux-2/edit",
    },
    "nano2": {
        "generate": "fal-ai/nano-banana-2",
        "edit": "fal-ai/nano-banana-2/edit",
    },
    "gptimage2": {
        "generate": "openai-codex/gpt-image-2",
        "edit": "openai-codex/gpt-image-2/edit",
    },
    "seedance2": {
        "text-to-video": "fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
        "image-to-video": "fal-ai/bytedance/seedance/v1.5/pro/image-to-video",
    },
    "grokimage2": {
        "generate": "https://api.x.ai/v1/images/generations",
        "edit": "https://api.x.ai/v1/images/edits",
    },
    "grokvideo": {
        "text-to-video": "https://api.x.ai/v1/videos/generations",
        "image-to-video": "https://api.x.ai/v1/videos/generations",
    },
}

IMAGE_TIMEOUT_SECONDS = 120
CODEX_IMAGE_TIMEOUT_SECONDS = 300
VIDEO_TIMEOUT_SECONDS = 300

# GPT Image 2 via Codex Responses API (mirrors Hermes openai-codex image plugin)
GPT_IMAGE_API_MODEL = "gpt-image-2"
GROK_IMAGE_API_MODEL = "grok-imagine-image-2.0"
GROK_VIDEO_API_MODEL = "grok-imagine-video-1.5"
CODEX_CHAT_MODEL = "gpt-5.5"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_INSTRUCTIONS = (
    "You are an assistant that must fulfill image generation and image editing "
    "requests by using the image_generation tool when provided."
)
GPT_SIZES = {
    "landscape": "1536x1024",
    "square": "1024x1024",
    "portrait": "1024x1536",
}
_MAX_INPUT_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_REFERENCE_IMAGES = 16
_ACCEPTED_INPUT_MIME = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_IMAGE_GENERATION_UNSUPPORTED_ERROR = (
    "Tool choice 'image_generation' not found in 'tools' parameter."
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def ensure_dirs(media_type="image"):
    """Create workspace directories if they don't exist."""
    dirs = [EXTERNAL_DIR, LOGS_DIR]
    if media_type == "image":
        dirs.append(RAW_DIR)
    elif media_type == "video":
        dirs.append(VIDEOS_RAW_DIR)
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def copy_to_external(path: str) -> Path:
    """Copy an input file to external/ if not already there. Returns the destination path."""
    src = Path(path)
    if not src.exists():
        print(f"ERROR=Input file not found: {path}")
        sys.exit(1)
    dst = EXTERNAL_DIR / src.name
    if dst.resolve() != src.resolve():
        shutil.copy2(src, dst)
    return dst


def require_fal_client():
    try:
        import fal_client  # noqa: F401
        return fal_client
    except ImportError:
        print(
            "ERROR=fal_client not installed. Use Hermes venv: "
            f"{HERMES_HOME}/hermes-agent/venv/bin/python {Path(__file__).resolve()}"
        )
        sys.exit(1)


def upload_to_fal(path: str) -> str:
    """Upload a file to fal.ai storage and return the public URL."""
    fal_client = require_fal_client()
    return fal_client.upload_file(path)


def workspace_relpath(path: Path | str) -> str:
    """Return a workspace-relative POSIX path for Media receipts/assets."""
    p = Path(path)
    if not p.is_absolute():
        return str(p).replace("\\", "/")
    try:
        return str(p.resolve().relative_to(WORKSPACE.resolve())).replace("\\", "/")
    except ValueError:
        return p.name


def _provider_for_endpoint(endpoint: str, auth_provider: Optional[str] = None) -> str:
    if auth_provider in {"xai", "xai-oauth"}:
        return auth_provider
    if "openai-codex" in endpoint or endpoint.startswith("openai"):
        return "openai-codex"
    if "x.ai" in endpoint or endpoint.startswith("xai") or "grok-imagine" in endpoint:
        return "xai"
    return "fal"


def build_media_sync_payload(
    *,
    kind: str,
    mode: str,
    model: str,
    endpoint: str,
    prompt: str,
    seed: Any,
    output_path: Path | str,
    input_md_entries: List[dict],
    end_md_entry: Optional[dict],
    params: Optional[dict] = None,
) -> Tuple[List[dict], dict]:
    """Build assets + generation payload for media_client.sync_if_enabled.

    Role mapping:
      - image edit inputs → edit_source by position
      - i2v first input → start_frame; end_image → end_frame
    Never includes legacy Markdown paths.
    """
    assets: List[dict] = []
    gen_inputs: List[dict] = []

    if kind == "image" and mode == "edit":
        for i, entry in enumerate(input_md_entries or []):
            rel = workspace_relpath(entry["path"])
            assets.append(
                {
                    "path": rel,
                    "kind": "image",
                    "origin": "external_import",
                    "show_in_grid": False,
                    "role": "edit_source",
                    "position": i,
                }
            )
            gen_inputs.append({"path": rel, "role": "edit_source", "position": i})
    elif kind == "video" and mode == "image-to-video":
        if input_md_entries:
            start_rel = workspace_relpath(input_md_entries[0]["path"])
            assets.append(
                {
                    "path": start_rel,
                    "kind": "image",
                    "origin": "external_import",
                    "show_in_grid": False,
                    "role": "start_frame",
                    "position": 0,
                }
            )
            gen_inputs.append({"path": start_rel, "role": "start_frame", "position": 0})
        if end_md_entry is not None:
            end_rel = workspace_relpath(end_md_entry["path"])
            assets.append(
                {
                    "path": end_rel,
                    "kind": "image",
                    "origin": "external_import",
                    "show_in_grid": False,
                    "role": "end_frame",
                    "position": 1,
                }
            )
            gen_inputs.append({"path": end_rel, "role": "end_frame", "position": 1})

    out_rel = workspace_relpath(output_path)
    out_kind = "video" if kind == "video" else "image"
    assets.append(
        {
            "path": out_rel,
            "kind": out_kind,
            "origin": "mediagen_generation",
            "show_in_grid": True,
            "position": 0,
        }
    )

    if mode == "edit":
        operation = "edit"
    elif mode == "generate":
        operation = "generate"
    elif mode == "image-to-video":
        operation = "image-to-video"
    elif mode == "text-to-video":
        operation = "text-to-video"
    else:
        operation = mode

    gen_params = dict(params or {})
    if "endpoint" not in gen_params:
        gen_params["endpoint"] = endpoint

    generation: dict = {
        "tool": "mediagen",
        "operation": operation,
        "provider": _provider_for_endpoint(endpoint, gen_params.get("provider") or gen_params.get("auth_provider")),
        "model": model,
        "prompt": prompt,
        "seed": seed,
        "params": gen_params,
        "status": "succeeded",
        "inputs": gen_inputs,
        "outputs": [{"path": out_rel, "position": 0}],
    }
    # Safety: never treat markdown as Media assets
    assets = [a for a in assets if not str(a.get("path", "")).endswith(".md")]
    return assets, generation


def finalize_generation_with_media_sync(meta: dict) -> None:
    """After file+log persist: receipt + one Media sync attempt, then FILENAME contract.

    Media failures never raise and never change generation success (exit 0 path).
    """
    filename = meta["filename"]
    prompt = meta["prompt"]
    seed_display = meta["seed_display"]
    try:
        if load_config is not None and sync_if_enabled is not None:
            assets, generation = build_media_sync_payload(
                kind=meta["kind"],
                mode=meta["mode"],
                model=meta["model"],
                endpoint=meta["endpoint"],
                prompt=prompt,
                seed=meta.get("seed"),
                output_path=meta["output_path"],
                input_md_entries=meta.get("input_md_entries") or [],
                end_md_entry=meta.get("end_md_entry"),
                params=meta.get("params"),
            )
            cfg = load_config()
            if cfg is not None:
                sync_if_enabled(
                    cfg,
                    workspace=WORKSPACE,
                    log_path=workspace_relpath(meta["log_path"]),
                    assets=assets,
                    generation=generation,
                )
    except Exception:
        # Media must never break Telegram/FILENAME contract or generation exit code.
        pass
    print(f"FILENAME={filename} PROMPT={prompt} SEED={seed_display}")


def download_file(url: str, dest: Path):
    """Download a file from a URL to a local path."""
    urllib.request.urlretrieve(url, str(dest))


def width_height_to_aspect_ratio(width: int, height: int) -> str:
    """Convert width/height to aspect ratio string for nano2."""
    from math import gcd
    g = gcd(width, height)
    return f"{width // g}:{height // g}"


def width_height_to_gpt_aspect(width: int, height: int) -> str:
    """Map arbitrary WxH onto GPT Image 2 fixed aspects."""
    if width <= 0 or height <= 0:
        return "landscape"
    ratio = width / height
    # Thresholds midway between 1:1 and 3:2 / 2:3
    if ratio >= 1.2:
        return "landscape"
    if ratio <= 0.833:
        return "portrait"
    return "square"


GROK_IMAGE_ASPECTS = (
    (1, 1, "1:1"),
    (16, 9, "16:9"),
    (9, 16, "9:16"),
    (4, 3, "4:3"),
    (3, 4, "3:4"),
    (3, 2, "3:2"),
    (2, 3, "2:3"),
    (2, 1, "2:1"),
    (1, 2, "1:2"),
    (19.5, 9, "19.5:9"),
    (9, 19.5, "9:19.5"),
    (20, 9, "20:9"),
    (9, 20, "9:20"),
)


def width_height_to_grok_aspect(width: int, height: int) -> str:
    """Snap WxH onto the nearest Grok Imagine image aspect_ratio."""
    if width <= 0 or height <= 0:
        return "16:9"
    target = width / height
    best_label = "16:9"
    best_err = float("inf")
    for w, h, label in GROK_IMAGE_ASPECTS:
        err = abs((w / h) - target)
        if err < best_err:
            best_err = err
            best_label = label
    return best_label


def width_height_to_grok_resolution(width: int, height: int) -> str:
    """1k unless the long edge is at least 1536 (then 2k)."""
    return "2k" if max(width, height) >= 1536 else "1k"


def build_flux2_args(args, mode: str) -> dict:
    """Build fal.ai API arguments for FLUX.2 models."""
    api_args = {
        "prompt": args.prompt,
        "image_size": {"width": args.width, "height": args.height},
        "num_inference_steps": args.steps,
        "guidance_scale": 2.5,
        "num_images": 1,
        "acceleration": "regular",
        "output_format": "png",
        "enable_safety_checker": False,  # hardcoded — most permissive
    }
    if args.seed is not None:
        api_args["seed"] = args.seed
    if mode == "edit":
        api_args["image_urls"] = args.image_urls
    return api_args


def build_nano2_args(args, mode: str) -> dict:
    """Build fal.ai API arguments for Nano Banana 2 models."""
    api_args = {
        "prompt": args.prompt,
        "aspect_ratio": width_height_to_aspect_ratio(args.width, args.height),
        "num_images": 1,
        "output_format": "png",
        "safety_tolerance": "6",  # hardcoded — most permissive
    }
    if args.seed is not None:
        api_args["seed"] = args.seed
    if args.enable_web_search:
        api_args["enable_web_search"] = True
    if mode == "edit":
        api_args["image_urls"] = args.image_urls
    return api_args


def build_seedance2_args(args, mode: str) -> dict:
    """Build fal.ai API arguments for Seedance 1.5 Pro models."""
    api_args = {
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "duration": str(args.duration),
        "enable_audio": not args.no_audio,
        "enable_safety_checker": False,  # hardcoded — most permissive
    }
    if args.camera_fixed:
        api_args["static_video"] = True
    if args.seed is not None:
        api_args["seed"] = args.seed
    if mode == "image-to-video":
        api_args["image_url"] = args.image_url
        if args.end_image_url is not None:
            api_args["end_image_url"] = args.end_image_url
    return api_args


def build_grokimage2_args(args, mode: str) -> dict:
    """Build xAI Imagine JSON body for grok-imagine-image-2.0."""
    quality = getattr(args, "quality", "medium")
    if not isinstance(quality, str):
        quality = "medium"
    api_args = {
        "model": GROK_IMAGE_API_MODEL,
        "prompt": args.prompt,
        "aspect_ratio": width_height_to_grok_aspect(args.width, args.height),
        "resolution": width_height_to_grok_resolution(args.width, args.height),
        "quality": quality,
        "response_format": "b64_json",
    }
    if mode == "edit":
        urls = list(getattr(args, "image_data_urls", None) or [])
        fields = [{"url": url, "type": "image_url"} for url in urls]
        if len(fields) == 1:
            api_args["image"] = fields[0]
        elif len(fields) > 1:
            api_args["images"] = fields
    return api_args


def build_grokvideo_args(args, mode: str) -> dict:
    """Build xAI Imagine JSON body for grok-imagine-video-1.5."""
    api_args = {
        "model": GROK_VIDEO_API_MODEL,
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "duration": int(args.duration),
    }
    if mode == "image-to-video":
        image_url = getattr(args, "image_data_url", None)
        if image_url:
            api_args["image"] = {"url": image_url, "type": "image_url"}
    return api_args


def validate_args(args):
    """Validate argument combinations and exit with error if invalid."""
    model_key = args.model
    is_video_model = model_key in VIDEO_MODELS
    is_image_model = model_key in IMAGE_MODELS
    is_codex_image = model_key in CODEX_IMAGE_MODELS
    is_fal_image = model_key in FAL_IMAGE_MODELS
    is_xai_image = model_key in XAI_IMAGE_MODELS
    is_xai_video = model_key in XAI_VIDEO_MODELS

    # MagicMock test doubles auto-create missing attrs; only honor real str quality.
    quality = getattr(args, "quality", "medium")
    if not isinstance(quality, str):
        quality = "medium"

    # Image-only args used with video model
    if is_video_model:
        if hasattr(args, "width") and (args.width != 1280 or args.height != 720):
            # width/height were explicitly changed from defaults — not valid for video
            if args.width != 1280 or args.height != 720:
                print("ERROR=--width/--height are not supported for video models. Use --aspect-ratio and --resolution instead.")
                sys.exit(1)
        if args.steps != 28:
            print("ERROR=--steps is not supported for video models.")
            sys.exit(1)
        if args.enable_web_search:
            print("ERROR=--enable-web-search is not supported for video models.")
            sys.exit(1)
        if quality != "medium":
            print("ERROR=--quality is only supported for gptimage2 and grokimage2.")
            sys.exit(1)

    # Video-only args used with image model
    if is_image_model:
        if hasattr(args, "resolution") and args.resolution != "720p":
            print("ERROR=--resolution is not supported for image models. Use --width/--height instead.")
            sys.exit(1)
        if hasattr(args, "aspect_ratio_set") and args.aspect_ratio != "16:9":
            print("ERROR=--aspect-ratio is not supported for image models. Use --width/--height instead.")
            sys.exit(1)
        if hasattr(args, "duration") and args.duration != 5:
            print("ERROR=--duration is not supported for image models.")
            sys.exit(1)
        if args.camera_fixed:
            print("ERROR=--camera-fixed is not supported for image models.")
            sys.exit(1)
        if args.no_audio:
            print("ERROR=--no-audio is not supported for image models.")
            sys.exit(1)
        if args.end_image is not None:
            print("ERROR=--end-image is not supported for image models.")
            sys.exit(1)

    # fal image-specific restrictions
    if is_fal_image:
        if quality != "medium":
            print("ERROR=--quality is only supported for gptimage2 and grokimage2.")
            sys.exit(1)

    # Codex image-specific restrictions
    if is_codex_image:
        if quality not in VALID_GPT_QUALITIES:
            print(f"ERROR=--quality must be one of {sorted(VALID_GPT_QUALITIES)}, got '{quality}'.")
            sys.exit(1)
        if args.steps != 28:
            print("ERROR=--steps is not supported for gptimage2.")
            sys.exit(1)
        if args.enable_web_search:
            print("ERROR=--enable-web-search is not supported for gptimage2.")
            sys.exit(1)
        # seed is ignored (API does not expose seed); OK if provided
        if args.inputs is not None and len(args.inputs) > _MAX_REFERENCE_IMAGES:
            print(f"ERROR=gptimage2 edit mode supports at most {_MAX_REFERENCE_IMAGES} input images.")
            sys.exit(1)

    # Grok Imagine image-specific restrictions
    if is_xai_image:
        if quality not in VALID_GROK_QUALITIES:
            print(
                "ERROR=--quality high is not supported for grokimage2. Use low or medium."
                if quality == "high"
                else f"ERROR=--quality must be one of {sorted(VALID_GROK_QUALITIES)} for grokimage2, got '{quality}'."
            )
            sys.exit(1)
        if args.steps != 28:
            print("ERROR=--steps is not supported for grokimage2.")
            sys.exit(1)
        if args.enable_web_search:
            print("ERROR=--enable-web-search is not supported for grokimage2.")
            sys.exit(1)
        if args.inputs is not None and len(args.inputs) > GROK_MAX_REFERENCE_IMAGES:
            print(
                f"ERROR=grokimage2 edit mode supports at most {GROK_MAX_REFERENCE_IMAGES} input images."
            )
            sys.exit(1)

    # Video-specific validations
    if is_video_model:
        if is_xai_video:
            if args.duration < 1 or args.duration > 15:
                print(f"ERROR=--duration must be between 1 and 15 seconds for grokvideo, got {args.duration}.")
                sys.exit(1)
            if args.end_image is not None:
                print("ERROR=--end-image is not supported for grokvideo.")
                sys.exit(1)
            if args.camera_fixed:
                print("ERROR=--camera-fixed is not supported for grokvideo.")
                sys.exit(1)
            if args.no_audio:
                print("ERROR=--no-audio is not supported for grokvideo.")
                sys.exit(1)
            if args.aspect_ratio not in GROK_VIDEO_ASPECT_RATIOS:
                print(
                    f"ERROR=--aspect-ratio must be one of {sorted(GROK_VIDEO_ASPECT_RATIOS)} for grokvideo, got '{args.aspect_ratio}'."
                )
                sys.exit(1)
        else:
            if args.duration < 4 or args.duration > 12:
                print(f"ERROR=--duration must be between 4 and 12 seconds, got {args.duration}.")
                sys.exit(1)
            if args.aspect_ratio not in SEEDANCE_ASPECT_RATIOS:
                print(
                    f"ERROR=--aspect-ratio must be one of {sorted(SEEDANCE_ASPECT_RATIOS)}, got '{args.aspect_ratio}'."
                )
                sys.exit(1)
        # Resolution
        if args.resolution not in VALID_RESOLUTIONS:
            print(f"ERROR=--resolution must be one of {VALID_RESOLUTIONS}, got '{args.resolution}'.")
            sys.exit(1)
        # Image-to-video: inputs must have exactly one image
        if args.inputs is not None:
            if len(args.inputs) != 1:
                print("ERROR=Video image-to-video requires exactly one input image (--inputs <path>).")
                sys.exit(1)
        # End image without start image (seedance only; grok already rejected end_image)
        if not is_xai_video and args.end_image is not None and args.inputs is None:
            print("ERROR=--end-image requires --inputs (start frame) to be provided.")
            sys.exit(1)

    # Image-specific validations (fal caps)
    if is_fal_image:
        if args.inputs is not None and len(args.inputs) > 4:
            print("ERROR=Image edit mode supports at most 4 input images.")
            sys.exit(1)


# ── xAI / Grok Imagine auth + parse ──────────────────────────────────────────


def extract_xai_image_ref(payload: dict) -> Optional[Tuple[str, str]]:
    """Return ('url'|'b64', value) from an Imagine images response, or None."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return None
    first = data[0] if isinstance(data[0], dict) else {}
    url = first.get("url")
    if isinstance(url, str) and url.strip():
        return ("url", url.strip())
    b64 = first.get("b64_json")
    if isinstance(b64, str) and b64.strip():
        return ("b64", b64.strip())
    return None


def sanitize_xai_image_log(payload: dict) -> dict:
    """Drop raw b64 from logs; keep url/metadata only."""
    if not isinstance(payload, dict):
        return {}
    out = dict(payload)
    data = out.get("data")
    if isinstance(data, list):
        cleaned = []
        for item in data:
            if isinstance(item, dict):
                row = {k: v for k, v in item.items() if k != "b64_json"}
                if "b64_json" in item:
                    row["b64_json"] = True
                cleaned.append(row)
            else:
                cleaned.append(item)
        out["data"] = cleaned
    return out


def xai_video_status(payload: dict) -> str:
    return str((payload or {}).get("status") or "").strip().lower()


def poll_xai_video(
    request_id: str,
    *,
    get_json,
    sleeper,
    interval: int = 5,
    timeout_seconds: int = VIDEO_TIMEOUT_SECONDS,
) -> dict:
    """Poll GET /v1/videos/{request_id} until done|failed|expired or timeout."""
    elapsed = 0
    last: dict = {}
    while elapsed < timeout_seconds:
        last = get_json(request_id) or {}
        status = xai_video_status(last)
        if status == "done" or status in {"failed", "expired", "error", "cancelled"}:
            return last
        sleeper(interval)
        elapsed += interval
    timed_out = dict(last)
    timed_out["status"] = "timeout"
    return timed_out


def _try_xai_http_credentials() -> Optional[dict]:
    """Hermes standard: OAuth pool first, then XAI_API_KEY."""
    _ensure_hermes_on_path()
    try:
        from tools.xai_http import resolve_xai_http_credentials

        creds = resolve_xai_http_credentials() or {}
    except Exception:
        return None
    api_key = str(creds.get("api_key") or "").strip()
    if not api_key:
        return None
    return {
        "provider": str(creds.get("provider") or "xai").strip() or "xai",
        "api_key": api_key,
        "base_url": str(creds.get("base_url") or "https://api.x.ai/v1").strip().rstrip("/"),
    }


def _try_xai_oauth_runtime_credentials() -> Optional[dict]:
    _ensure_hermes_on_path()
    try:
        from hermes_cli.auth import resolve_xai_oauth_runtime_credentials

        creds = resolve_xai_oauth_runtime_credentials() or {}
    except Exception:
        return None
    api_key = str(creds.get("api_key") or creds.get("access_token") or "").strip()
    if not api_key:
        return None
    return {
        "provider": "xai-oauth",
        "api_key": api_key,
        "base_url": str(creds.get("base_url") or "https://api.x.ai/v1").strip().rstrip("/"),
    }


def resolve_xai_credentials() -> dict:
    """OAuth first (Hermes helpers), then XAI_API_KEY. Always via Hermes venv."""
    for loader in (_try_xai_http_credentials, _try_xai_oauth_runtime_credentials):
        creds = loader()
        if creds and creds.get("api_key"):
            return creds
    api_key = str(os.environ.get("XAI_API_KEY") or "").strip()
    base_url = str(os.environ.get("XAI_BASE_URL") or "https://api.x.ai/v1").strip().rstrip("/")
    return {"provider": "xai", "api_key": api_key, "base_url": base_url or "https://api.x.ai/v1"}


def require_xai_credentials() -> dict:
    creds = resolve_xai_credentials()
    if not creds.get("api_key"):
        print(
            "ERROR=No xAI credentials. Run: hermes auth add xai-oauth --type oauth "
            "(or set XAI_API_KEY). Use Hermes venv Python."
        )
        sys.exit(1)
    return creds


def _require_httpx():
    try:
        import httpx
        return httpx
    except ImportError:
        print(
            "ERROR=httpx not installed. Use Hermes venv: "
            f"{HERMES_HOME}/hermes-agent/venv/bin/python {Path(__file__).resolve()}"
        )
        sys.exit(1)


def _xai_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "hermes-mediagen/grok-imagine",
    }


def _format_xai_http_error(status_code: int, body: str) -> str:
    msg = (body or "")[:500]
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("error") or msg)
        elif isinstance(err, str) and err.strip():
            msg = err.strip()
        elif payload.get("code"):
            msg = f"{payload.get('code')}: {payload.get('error') or msg}"
    hint = ""
    if status_code in {401, 403}:
        hint = " Check hermes auth add xai-oauth / XAI_API_KEY and quota."
    return f"xAI API HTTP {status_code}: {msg}{hint}"


def _xai_post_json(url: str, payload: dict, creds: dict, timeout: float) -> dict:
    httpx = _require_httpx()
    try:
        with httpx.Client(timeout=timeout) as http:
            response = http.post(url, headers=_xai_headers(creds["api_key"]), json=payload)
            if response.status_code >= 400:
                print(f"ERROR={_format_xai_http_error(response.status_code, response.text)}")
                sys.exit(1)
            return response.json()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR=xAI request failed: {exc}")
        sys.exit(1)


def _xai_get_json(url: str, creds: dict, timeout: float) -> dict:
    httpx = _require_httpx()
    try:
        with httpx.Client(timeout=timeout) as http:
            response = http.get(url, headers=_xai_headers(creds["api_key"]))
            if response.status_code >= 400:
                print(f"ERROR={_format_xai_http_error(response.status_code, response.text)}")
                sys.exit(1)
            return response.json()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR=xAI request failed: {exc}")
        sys.exit(1)


def download_xai_media(url: str, dest: Path, creds: dict, timeout: float = 120.0) -> None:
    """Download a temporary Imagine URL with the same bearer used for the API."""
    httpx = _require_httpx()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as http:
            response = http.get(url, headers=_xai_headers(creds["api_key"]))
            if response.status_code >= 400:
                print(f"ERROR={_format_xai_http_error(response.status_code, response.text)}")
                sys.exit(1)
            dest.write_bytes(response.content)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR=Could not download xAI media: {exc}")
        sys.exit(1)


def _ensure_hermes_on_path():
    agent_dir = str(HERMES_AGENT_DIR)
    if agent_dir not in sys.path and Path(agent_dir).is_dir():
        sys.path.insert(0, agent_dir)


def _read_codex_access_token() -> Optional[str]:
    """Return Hermes ChatGPT/Codex OAuth access token, or None."""
    _ensure_hermes_on_path()
    try:
        from agent.auxiliary_client import _read_codex_access_token as _reader
        token = _reader()
        if isinstance(token, str) and token.strip():
            return token.strip()
    except Exception:
        pass

    # Fallback: read auth.json pools directly
    auth_path = HERMES_HOME / "auth.json"
    try:
        data = json.loads(auth_path.read_text())
    except Exception:
        return None

    def _token_from_entry(entry: dict) -> Optional[str]:
        if not isinstance(entry, dict):
            return None
        for key in ("access_token", "token", "accessToken"):
            val = entry.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        creds = entry.get("credentials") or entry.get("auth") or entry.get("tokens")
        if isinstance(creds, dict):
            for key in ("access_token", "token", "accessToken"):
                val = creds.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        return None

    # Common shapes: {"providers": {"openai-codex": [...]}} or pooled top-level
    candidates: List[Any] = []
    if isinstance(data, dict):
        providers = data.get("providers") or data.get("credentials") or data
        if isinstance(providers, dict):
            for key in ("openai-codex", "codex", "chatgpt"):
                if key in providers:
                    candidates.append(providers[key])
        if "openai-codex" in data:
            candidates.append(data["openai-codex"])

    for cand in candidates:
        if isinstance(cand, list):
            for entry in cand:
                tok = _token_from_entry(entry) if isinstance(entry, dict) else None
                if tok:
                    return tok
        elif isinstance(cand, dict):
            tok = _token_from_entry(cand)
            if tok:
                return tok
            # nested current/active
            for nested_key in ("current", "active", "default", "oauth"):
                nested = cand.get(nested_key)
                if isinstance(nested, dict):
                    tok = _token_from_entry(nested)
                    if tok:
                        return tok
    return None


def _codex_headers(token: str) -> Dict[str, str]:
    _ensure_hermes_on_path()
    headers: Dict[str, str] = {
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        from agent.auxiliary_client import _codex_cloudflare_headers
        extra = _codex_cloudflare_headers(token) or {}
        if isinstance(extra, dict):
            headers.update({k: v for k, v in extra.items() if isinstance(v, str)})
    except Exception:
        # Minimal browser-ish headers if helper unavailable
        headers.setdefault("User-Agent", "hermes-mediagen/1.0")
        headers.setdefault("originator", "hermes-agent")
    return headers


def _sniff_image_mime(raw: bytes) -> Optional[str]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _local_image_to_data_url(path: str) -> str:
    p = Path(os.path.expanduser(path)).resolve()
    if not p.is_file():
        raise ValueError(f"Image input path does not exist: {path}")
    size = p.stat().st_size
    if size <= 0:
        raise ValueError(f"Image input path is empty: {path}")
    if size > _MAX_INPUT_IMAGE_BYTES:
        raise ValueError(f"Image input path exceeds 25MB cap: {path}")
    raw = p.read_bytes()
    mime = _sniff_image_mime(raw)
    if mime is None or mime not in _ACCEPTED_INPUT_MIME:
        raise ValueError(f"Unsupported image format: {path}")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _to_input_image_part(path: str) -> Dict[str, str]:
    return {"type": "input_image", "image_url": _local_image_to_data_url(path)}


def _build_codex_payload(
    *,
    prompt: str,
    size: str,
    quality: str,
    input_images: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    if input_images:
        content.extend(input_images)
    return {
        "model": CODEX_CHAT_MODEL,
        "store": False,
        "instructions": CODEX_INSTRUCTIONS,
        "input": [{
            "type": "message",
            "role": "user",
            "content": content,
        }],
        "tools": [{
            "type": "image_generation",
            "model": GPT_IMAGE_API_MODEL,
            "size": size,
            "quality": quality,
            "output_format": "png",
            "background": "opaque",
            "partial_images": 1,
        }],
        "tool_choice": {
            "type": "allowed_tools",
            "mode": "required",
            "tools": [{"type": "image_generation"}],
        },
        "stream": True,
    }


def _extract_image_b64(value: Any) -> Optional[str]:
    found: Optional[str] = None
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call":
            result = value.get("result")
            if isinstance(result, str) and result:
                found = result
        partial = value.get("partial_image_b64")
        if isinstance(partial, str) and partial:
            found = partial
        for child in value.values():
            nested = _extract_image_b64(child)
            if nested:
                found = nested
    elif isinstance(value, list):
        for child in value:
            nested = _extract_image_b64(child)
            if nested:
                found = nested
    return found


def _iter_sse_json(response):
    event_name: Optional[str] = None
    data_lines: List[str] = []

    def flush():
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None
        raw = "\n".join(data_lines).strip()
        event = event_name
        event_name = None
        data_lines = []
        if not raw or raw == "[DONE]":
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict) and event and "type" not in payload:
            payload["type"] = event
        return payload

    for line in response.iter_lines():
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = str(line)
        if line == "":
            payload = flush()
            if payload is not None:
                yield payload
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())

    payload = flush()
    if payload is not None:
        yield payload


def _is_image_generation_unsupported_error(status_code: int, body: str) -> bool:
    if status_code != 400:
        return False
    try:
        payload = json.loads(body)
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
    except (TypeError, ValueError):
        message = body
    return isinstance(message, str) and message.strip() == _IMAGE_GENERATION_UNSUPPORTED_ERROR


def collect_codex_image_b64(
    *,
    prompt: str,
    size: str,
    quality: str,
    input_images: Optional[List[Dict[str, str]]] = None,
) -> str:
    try:
        import httpx
    except ImportError:
        print(
            "ERROR=httpx not installed. Use Hermes venv: "
            f"{HERMES_HOME}/hermes-agent/venv/bin/python {Path(__file__).resolve()}"
        )
        sys.exit(1)

    token = _read_codex_access_token()
    if not token:
        print(
            "ERROR=No ChatGPT/Codex OAuth credentials. "
            "Run: hermes auth add openai-codex --no-browser"
        )
        sys.exit(1)

    headers = _codex_headers(token)
    payload = _build_codex_payload(
        prompt=prompt,
        size=size,
        quality=quality,
        input_images=input_images,
    )
    timeout = httpx.Timeout(
        CODEX_IMAGE_TIMEOUT_SECONDS,
        connect=30.0,
        read=CODEX_IMAGE_TIMEOUT_SECONDS,
        write=30.0,
        pool=30.0,
    )

    image_b64: Optional[str] = None
    try:
        with httpx.Client(timeout=timeout, headers=headers) as http:
            with http.stream("POST", f"{CODEX_BASE_URL}/responses", json=payload) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    exc.response.read()
                    full_body = exc.response.text
                    if _is_image_generation_unsupported_error(
                        exc.response.status_code, full_body
                    ):
                        print(
                            "ERROR=Image generation is not enabled for the current "
                            "ChatGPT/Codex account. Use flux2/nano2 (fal.ai) instead."
                        )
                        sys.exit(1)
                    body = full_body[:500]
                    print(
                        f"ERROR=Codex Responses API HTTP {exc.response.status_code}: {body}"
                    )
                    sys.exit(1)
                for event in _iter_sse_json(response):
                    found = _extract_image_b64(event)
                    if found:
                        image_b64 = found
    except Exception as e:
        print(f"ERROR=OpenAI image generation via Codex auth failed: {e}")
        sys.exit(1)

    if not image_b64:
        print("ERROR=Codex response contained no image_generation_call result")
        sys.exit(1)
    return image_b64


def _write_image_artifacts(
    *,
    image_path: Path,
    base_name: str,
    image_filename: str,
    args,
    mode: str,
    endpoint: str,
    seed_display: Any,
    size_str: str,
    input_md_entries: List[dict],
    log_extra: dict,
) -> dict:
    """Persist image markdown + JSON log. Returns metadata for Media sync + FILENAME print."""
    md_path = IMAGES_DIR / f"{base_name}.md"
    if mode == "edit":
        lines = []
        for entry in input_md_entries:
            orig = Path(entry["original"])
            if RAW_DIR.exists() and orig.parent.resolve() == RAW_DIR.resolve():
                md_base = orig.stem
                lines.append(f"- [{orig.name}](./{md_base}.md)")
            else:
                lines.append(f"- [{Path(entry['path']).name}](../external/{Path(entry['path']).name})")
        inputs_section = "\n## Inputs\n" + "\n".join(lines) + "\n"
    else:
        inputs_section = "\n## Inputs\nnone\n"

    md_content = f"""![generated](./raw/{image_filename})

# {base_name}

## Prompt
{args.prompt}

## Model
{endpoint}

## Seed
{seed_display}

## Size
{size_str}
{inputs_section}"""

    with open(md_path, "w") as f:
        f.write(md_content)

    log_path = LOGS_DIR / f"{base_name}.json"
    seed_value = None if seed_display == "n/a" else (None if seed_display == "random" else seed_display)
    # ignored:N from gptimage2 still not a real seed
    if isinstance(seed_display, str) and seed_display.startswith("ignored:"):
        seed_value = None
    log_data = {
        "filename": image_filename,
        "prompt": args.prompt,
        "model": endpoint,
        "mode": mode,
        "seed": seed_value,
        "width": args.width,
        "height": args.height,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": [str(Path(e["path"])) for e in input_md_entries] if mode == "edit" else [],
        **log_extra,
    }
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)

    model_key = getattr(args, "model", None) or "unknown"
    params: dict[str, Any] = {
        "endpoint": endpoint,
        "width": args.width,
        "height": args.height,
        "size": size_str,
    }
    if "quality" in log_extra:
        params["quality"] = log_extra["quality"]
    if "aspect" in log_extra:
        params["aspect"] = log_extra["aspect"]
    if "provider" in log_extra:
        params["provider"] = log_extra["provider"]
    if "resolution" in log_extra:
        params["resolution"] = log_extra["resolution"]

    return {
        "kind": "image",
        "filename": image_filename,
        "prompt": args.prompt,
        "seed_display": seed_display,
        "seed": seed_value,
        "log_path": log_path,
        "output_path": image_path,
        "mode": mode,
        "endpoint": endpoint,
        "model": model_key,
        "input_md_entries": input_md_entries,
        "end_md_entry": None,
        "params": params,
        "log_data": log_data,
    }


def _write_video_artifacts(
    *,
    video_path: Path,
    base_name: str,
    video_filename: str,
    args,
    mode: str,
    endpoint: str,
    returned_seed: Any,
    input_md_entries: List[dict],
    end_md_entry: Optional[dict],
    result: dict,
    log_extra: Optional[dict] = None,
) -> dict:
    """Persist video markdown + JSON log. Returns metadata for Media sync + FILENAME print."""
    md_path = VIDEOS_DIR / f"{base_name}.md"
    inputs_lines = []
    if mode == "image-to-video":
        entry = input_md_entries[0]
        orig = Path(entry["original"])
        if RAW_DIR.exists() and orig.parent.resolve() == RAW_DIR.resolve():
            md_base = orig.stem
            inputs_lines.append(f"- Start frame: [{orig.name}](../../images/{md_base}.md)")
        else:
            inputs_lines.append(
                f"- Start frame: [{Path(entry['path']).name}](../external/{Path(entry['path']).name})"
            )
        if end_md_entry:
            end_orig = Path(end_md_entry["original"])
            if RAW_DIR.exists() and end_orig.parent.resolve() == RAW_DIR.resolve():
                end_md_base = end_orig.stem
                inputs_lines.append(f"- End frame: [{end_orig.name}](../../images/{end_md_base}.md)")
            else:
                inputs_lines.append(
                    f"- End frame: [{Path(end_md_entry['path']).name}](../external/{Path(end_md_entry['path']).name})"
                )
    inputs_section = "\n## Inputs\n" + ("\n".join(inputs_lines) if inputs_lines else "none") + "\n"

    seed_display = returned_seed if returned_seed is not None else "random"
    audio_str = "no" if args.no_audio else "yes"
    camera_str = "yes" if args.camera_fixed else "no"

    md_content = f"""[Video file](./raw/{video_filename})

# {base_name}

## Prompt
{args.prompt}

## Model
{endpoint}

## Seed
{seed_display}

## Settings
Resolution: {args.resolution}
Duration: {args.duration}s
Aspect ratio: {args.aspect_ratio}
Audio: {audio_str}
Camera fixed: {camera_str}
{inputs_section}"""

    with open(md_path, "w") as f:
        f.write(md_content)

    log_path = LOGS_DIR / f"{base_name}.json"
    log_data = {
        "filename": video_filename,
        "prompt": args.prompt,
        "model": endpoint,
        "mode": mode,
        "seed": returned_seed,
        "resolution": args.resolution,
        "duration": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "audio": not args.no_audio,
        "camera_fixed": args.camera_fixed,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": [str(Path(e["path"])) for e in input_md_entries] if mode == "image-to-video" else [],
        "end_image": str(Path(end_md_entry["path"])) if end_md_entry else None,
    }
    extra = dict(log_extra or {})
    if extra.get("provider") in {"xai", "xai-oauth"}:
        log_data["xai_response"] = extra.pop("xai_response", result)
    else:
        log_data["fal_response"] = result
    log_data.update(extra)
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)

    model_key = getattr(args, "model", None) or "seedance2"
    params = {
        "endpoint": endpoint,
        "resolution": args.resolution,
        "duration": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "audio": not args.no_audio,
        "camera_fixed": args.camera_fixed,
    }
    extra = dict(log_extra or {})
    if extra.get("provider"):
        params["provider"] = extra["provider"]
    return {
        "kind": "video",
        "filename": video_filename,
        "prompt": args.prompt,
        "seed_display": seed_display,
        "seed": returned_seed,
        "log_path": log_path,
        "output_path": video_path,
        "mode": mode,
        "endpoint": endpoint,
        "model": model_key,
        "input_md_entries": input_md_entries,
        "end_md_entry": end_md_entry,
        "params": params,
        "log_data": log_data,
    }


# ── Image pipeline ──────────────────────────────────────────────────────────

def run_image_fal(args):
    """Execute fal.ai image generation/edit pipeline."""
    fal_client = require_fal_client()
    ensure_dirs(media_type="image")

    mode = "edit" if args.inputs else "generate"
    model_key = args.model
    endpoint = MODEL_MAP[model_key][mode]

    # Handle input images (edit mode)
    image_urls = []
    input_md_entries = []
    if args.inputs:
        for inp in args.inputs:
            local_copy = copy_to_external(inp)
            url = upload_to_fal(str(local_copy))
            image_urls.append(url)
            input_md_entries.append({"path": str(local_copy), "original": inp})
    args.image_urls = image_urls

    # Build API arguments
    if model_key == "flux2":
        api_args = build_flux2_args(args, mode)
    else:
        api_args = build_nano2_args(args, mode)

    # Call fal.ai (with timeout via SIGALRM)
    try:
        def _timeout_handler(signum, frame):
            raise TimeoutError(f"Timeout after {IMAGE_TIMEOUT_SECONDS}s")
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(IMAGE_TIMEOUT_SECONDS)
        try:
            result = fal_client.subscribe(endpoint, arguments=api_args)
        finally:
            signal.alarm(0)
    except Exception as e:
        # Preserve prior error shapes where possible
        name = type(e).__name__
        if "FalClientError" in name or "fal" in name.lower():
            print(f"ERROR=fal.ai API error: {e}")
        elif isinstance(e, TimeoutError):
            print(f"ERROR={e}. Try again or use a different model.")
        else:
            print(f"ERROR=Unexpected error: {e}")
        sys.exit(1)

    # Extract result
    if "images" not in result or not result["images"]:
        print("ERROR=No images returned from fal.ai")
        sys.exit(1)

    image_data = result["images"][0]
    image_url = image_data["url"]
    returned_seed = result.get("seed") or args.seed

    # Generate filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    edit_suffix = "_edit" if mode == "edit" else ""
    base_name = f"{timestamp}_{model_key}{edit_suffix}"
    image_filename = f"{base_name}.png"

    # Download image
    image_path = RAW_DIR / image_filename
    download_file(image_url, image_path)

    seed_display = returned_seed if returned_seed is not None else "random"
    size_str = (
        f"{args.width}x{args.height}"
        if model_key == "flux2"
        else api_args.get("aspect_ratio", f"{args.width}x{args.height}")
    )
    finalize_generation_with_media_sync(
        _write_image_artifacts(
            image_path=image_path,
            base_name=base_name,
            image_filename=image_filename,
            args=args,
            mode=mode,
            endpoint=endpoint,
            seed_display=seed_display,
            size_str=size_str,
            input_md_entries=input_md_entries,
            log_extra={"fal_response": result},
        )
    )


def run_image_codex(args):
    """Execute GPT Image 2 generation/edit via ChatGPT Codex OAuth."""
    ensure_dirs(media_type="image")

    mode = "edit" if args.inputs else "generate"
    endpoint = MODEL_MAP["gptimage2"][mode]
    quality = args.quality
    aspect = width_height_to_gpt_aspect(args.width, args.height)
    size = GPT_SIZES[aspect]

    input_md_entries = []
    input_images: List[Dict[str, str]] = []
    if args.inputs:
        for inp in args.inputs:
            local_copy = copy_to_external(inp)
            input_md_entries.append({"path": str(local_copy), "original": inp})
            try:
                input_images.append(_to_input_image_part(str(local_copy)))
            except Exception as e:
                print(f"ERROR=Invalid image input for gptimage2: {e}")
                sys.exit(1)

    b64 = collect_codex_image_b64(
        prompt=args.prompt,
        size=size,
        quality=quality,
        input_images=input_images or None,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    edit_suffix = "_edit" if mode == "edit" else ""
    base_name = f"{timestamp}_gptimage2_{quality}{edit_suffix}"
    image_filename = f"{base_name}.png"
    image_path = RAW_DIR / image_filename

    try:
        raw = base64.b64decode(b64, validate=False)
        image_path.write_bytes(raw)
    except Exception as e:
        print(f"ERROR=Could not save gptimage2 output: {e}")
        sys.exit(1)

    # seed not supported by this API
    seed_display = "n/a" if args.seed is None else f"ignored:{args.seed}"
    size_str = f"{size} ({aspect}, quality={quality})"
    finalize_generation_with_media_sync(
        _write_image_artifacts(
            image_path=image_path,
            base_name=base_name,
            image_filename=image_filename,
            args=args,
            mode=mode,
            endpoint=endpoint,
            seed_display=seed_display,
            size_str=size_str,
            input_md_entries=input_md_entries,
            log_extra={
                "provider": "openai-codex",
                "api_model": GPT_IMAGE_API_MODEL,
                "quality": quality,
                "aspect": aspect,
                "size": size,
                "codex_chat_model": CODEX_CHAT_MODEL,
            },
        )
    )


def run_image_xai(args):
    """Execute Grok Imagine image generate/edit via xAI HTTP API."""
    ensure_dirs(media_type="image")
    creds = require_xai_credentials()
    mode = "edit" if args.inputs else "generate"
    base_url = creds.get("base_url") or "https://api.x.ai/v1"
    endpoint = f"{base_url}/images/edits" if mode == "edit" else f"{base_url}/images/generations"
    quality = args.quality if isinstance(getattr(args, "quality", None), str) else "medium"

    input_md_entries = []
    data_urls: List[str] = []
    if args.inputs:
        for inp in args.inputs:
            local_copy = copy_to_external(inp)
            input_md_entries.append({"path": str(local_copy), "original": inp})
            try:
                data_urls.append(_local_image_to_data_url(str(local_copy)))
            except Exception as exc:
                print(f"ERROR=Invalid image input for grokimage2: {exc}")
                sys.exit(1)
    args.image_data_urls = data_urls
    payload = build_grokimage2_args(args, mode)
    result = _xai_post_json(endpoint, payload, creds, float(CODEX_IMAGE_TIMEOUT_SECONDS))
    ref = extract_xai_image_ref(result)
    if ref is None:
        print("ERROR=xAI image response contained neither url nor b64_json")
        sys.exit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    edit_suffix = "_edit" if mode == "edit" else ""
    base_name = f"{timestamp}_grokimage2_{quality}{edit_suffix}"
    image_filename = f"{base_name}.png"
    image_path = RAW_DIR / image_filename
    kind, value = ref
    try:
        if kind == "url":
            download_xai_media(value, image_path, creds)
        else:
            image_path.write_bytes(base64.b64decode(value, validate=False))
    except Exception as exc:
        print(f"ERROR=Could not save grokimage2 output: {exc}")
        sys.exit(1)

    aspect = payload.get("aspect_ratio")
    resolution = payload.get("resolution")
    size_str = f"{aspect} {resolution} (quality={quality})"
    finalize_generation_with_media_sync(
        _write_image_artifacts(
            image_path=image_path,
            base_name=base_name,
            image_filename=image_filename,
            args=args,
            mode=mode,
            endpoint=endpoint,
            seed_display="n/a",
            size_str=size_str,
            input_md_entries=input_md_entries,
            log_extra={
                "provider": creds.get("provider") or "xai",
                "api_model": GROK_IMAGE_API_MODEL,
                "quality": quality,
                "aspect": aspect,
                "resolution": resolution,
                "xai_response": sanitize_xai_image_log(result),
            },
        )
    )


def run_image(args):
    """Route image models to fal.ai, Codex, or xAI backends."""
    if args.model in CODEX_IMAGE_MODELS:
        run_image_codex(args)
    elif args.model in XAI_IMAGE_MODELS:
        run_image_xai(args)
    else:
        run_image_fal(args)


# ── Video pipeline ───────────────────────────────────────────────────────────

def run_video_xai(args):
    """Execute Grok Imagine video t2v/i2v via xAI HTTP API."""
    ensure_dirs(media_type="video")
    creds = require_xai_credentials()
    mode = "image-to-video" if args.inputs else "text-to-video"
    base_url = creds.get("base_url") or "https://api.x.ai/v1"
    endpoint = f"{base_url}/videos/generations"

    input_md_entries = []
    image_data_url = None
    if args.inputs:
        local_copy = copy_to_external(args.inputs[0])
        input_md_entries.append({"path": str(local_copy), "original": args.inputs[0]})
        try:
            image_data_url = _local_image_to_data_url(str(local_copy))
        except Exception as exc:
            print(f"ERROR=Invalid start frame for grokvideo: {exc}")
            sys.exit(1)
    args.image_data_url = image_data_url
    payload = build_grokvideo_args(args, mode)
    submitted = _xai_post_json(endpoint, payload, creds, 60.0)
    request_id = submitted.get("request_id") if isinstance(submitted, dict) else None
    if not request_id:
        print("ERROR=xAI video response did not include request_id")
        sys.exit(1)

    def _get_status(_rid: str) -> dict:
        return _xai_get_json(f"{base_url}/videos/{request_id}", creds, 30.0)

    result = poll_xai_video(
        str(request_id),
        get_json=_get_status,
        sleeper=time.sleep,
        interval=5,
        timeout_seconds=VIDEO_TIMEOUT_SECONDS,
    )
    status = xai_video_status(result)
    if status != "done":
        print(f"ERROR=xAI video generation {status or 'failed'}: {str(result)[:400]}")
        sys.exit(1)
    video_obj = result.get("video") if isinstance(result, dict) else None
    video = video_obj if isinstance(video_obj, dict) else {}
    video_url = video.get("url")
    if not isinstance(video_url, str) or not video_url.strip():
        print("ERROR=xAI video response contained no video.url")
        sys.exit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    i2v_suffix = "_i2v" if mode == "image-to-video" else ""
    base_name = f"{timestamp}_grokvideo{i2v_suffix}"
    video_filename = f"{base_name}.mp4"
    video_path = VIDEOS_RAW_DIR / video_filename
    try:
        download_xai_media(video_url.strip(), video_path, creds)
    except Exception as exc:
        print(f"ERROR=Could not save grokvideo output: {exc}")
        sys.exit(1)

    finalize_generation_with_media_sync(
        _write_video_artifacts(
            video_path=video_path,
            base_name=base_name,
            video_filename=video_filename,
            args=args,
            mode=mode,
            endpoint=endpoint,
            returned_seed="n/a",
            input_md_entries=input_md_entries,
            end_md_entry=None,
            result=result,
            log_extra={
                "provider": creds.get("provider") or "xai",
                "api_model": GROK_VIDEO_API_MODEL,
                "request_id": request_id,
                "xai_response": result,
            },
        )
    )


def run_video(args):
    """Execute video generation pipeline (text-to-video or image-to-video)."""
    if args.model in XAI_VIDEO_MODELS:
        run_video_xai(args)
        return
    fal_client = require_fal_client()
    ensure_dirs(media_type="video")

    mode = "image-to-video" if args.inputs else "text-to-video"
    model_key = args.model
    endpoint = MODEL_MAP[model_key][mode]

    # Handle input image (image-to-video)
    input_md_entries = []
    if args.inputs:
        local_copy = copy_to_external(args.inputs[0])
        url = upload_to_fal(str(local_copy))
        args.image_url = url
        input_md_entries.append({"path": str(local_copy), "original": args.inputs[0]})

    # Handle end image (optional, image-to-video only)
    end_md_entry = None
    if args.end_image is not None:
        local_copy = copy_to_external(args.end_image)
        url = upload_to_fal(str(local_copy))
        args.end_image_url = url
        end_md_entry = {"path": str(local_copy), "original": args.end_image}
    else:
        args.end_image_url = None

    # Build API arguments
    api_args = build_seedance2_args(args, mode)

    # Call fal.ai (with timeout via SIGALRM)
    try:
        def _timeout_handler(signum, frame):
            raise TimeoutError(f"Timeout after {VIDEO_TIMEOUT_SECONDS}s")
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(VIDEO_TIMEOUT_SECONDS)
        try:
            result = fal_client.subscribe(endpoint, arguments=api_args)
        finally:
            signal.alarm(0)
    except Exception as e:
        name = type(e).__name__
        if "FalClientError" in name or "fal" in name.lower():
            print(f"ERROR=fal.ai API error: {e}")
        elif isinstance(e, TimeoutError):
            print(f"ERROR={e}. Try again or use a different model.")
        else:
            print(f"ERROR=Unexpected error: {e}")
        sys.exit(1)

    # Extract result
    if "video" not in result or "url" not in result["video"]:
        print("ERROR=No video returned from fal.ai")
        sys.exit(1)

    video_url = result["video"]["url"]
    returned_seed = result.get("seed") or args.seed

    # Generate filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    i2v_suffix = "_i2v" if mode == "image-to-video" else ""
    base_name = f"{timestamp}_{model_key}{i2v_suffix}"
    video_filename = f"{base_name}.mp4"

    # Download video
    video_path = VIDEOS_RAW_DIR / video_filename
    download_file(video_url, video_path)

    finalize_generation_with_media_sync(
        _write_video_artifacts(
            video_path=video_path,
            base_name=base_name,
            video_filename=video_filename,
            args=args,
            mode=mode,
            endpoint=endpoint,
            returned_seed=returned_seed,
            input_md_entries=input_md_entries,
            end_md_entry=end_md_entry,
            result=result,
        )
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    all_models = sorted(IMAGE_MODELS | VIDEO_MODELS)
    parser = argparse.ArgumentParser(
        description="mediagen — Image and video generation via fal.ai + ChatGPT Codex OAuth"
    )
    parser.add_argument("--model", required=True, choices=all_models, help="Model to use")
    parser.add_argument("--prompt", required=True, help="Text prompt for generation")

    # Image args
    parser.add_argument("--inputs", nargs="*", default=None, help="Input images: for image edit mode or image-to-video")
    parser.add_argument("--width", type=int, default=1280, help="Output width — image only (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Output height — image only (default: 720)")
    parser.add_argument("--steps", type=int, default=28, help="Inference steps — flux2 only (default: 28)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random; ignored by gptimage2 and grok)")
    parser.add_argument("--enable-web-search", action="store_true", help="Enable web search — nano2 only")
    parser.add_argument(
        "--quality",
        default="medium",
        choices=sorted(VALID_GPT_QUALITIES),
        help="Image quality — gptimage2: low|medium|high; grokimage2: low|medium (default: medium)",
    )

    # Video args
    parser.add_argument("--end-image", default=None, help="End frame image — seedance2 image-to-video only")
    parser.add_argument("--resolution", default="720p", choices=VALID_RESOLUTIONS, help="Video resolution (default: 720p)")
    parser.add_argument("--aspect-ratio", default="16:9", choices=sorted(VALID_ASPECT_RATIOS), help="Video aspect ratio (default: 16:9)")
    parser.add_argument("--duration", type=int, default=5, help="Video duration in seconds (seedance 4-12, grokvideo 1-15; default: 5)")
    parser.add_argument("--camera-fixed", action="store_true", help="Lock camera position — video only")
    parser.add_argument("--no-audio", action="store_true", help="Disable audio generation — video only")

    args = parser.parse_args()

    # Validate argument combinations
    validate_args(args)

    # Route to the right pipeline
    if args.model in IMAGE_MODELS:
        run_image(args)
    elif args.model in VIDEO_MODELS:
        run_video(args)
    else:
        print(f"ERROR=Unknown model: {args.model}")
        sys.exit(1)


if __name__ == "__main__":
    main()
