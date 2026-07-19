#!/usr/bin/env python3
"""mediagen.py — Image and video generation via fal.ai + ChatGPT Codex OAuth

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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
IMAGE_MODELS = FAL_IMAGE_MODELS | CODEX_IMAGE_MODELS
VIDEO_MODELS = {"seedance2"}

VALID_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "auto"}
VALID_RESOLUTIONS = {"480p", "720p", "1080p"}
VALID_GPT_QUALITIES = {"low", "medium", "high"}

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
}

IMAGE_TIMEOUT_SECONDS = 120
CODEX_IMAGE_TIMEOUT_SECONDS = 300
VIDEO_TIMEOUT_SECONDS = 300

# GPT Image 2 via Codex Responses API (mirrors Hermes openai-codex image plugin)
GPT_IMAGE_API_MODEL = "gpt-image-2"
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


def validate_args(args):
    """Validate argument combinations and exit with error if invalid."""
    model_key = args.model
    is_video_model = model_key in VIDEO_MODELS
    is_image_model = model_key in IMAGE_MODELS
    is_codex_image = model_key in CODEX_IMAGE_MODELS
    is_fal_image = model_key in FAL_IMAGE_MODELS

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
            print("ERROR=--quality is only supported for gptimage2.")
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
            print("ERROR=--quality is only supported for gptimage2.")
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

    # Video-specific validations
    if is_video_model:
        # Duration range
        if args.duration < 4 or args.duration > 12:
            print(f"ERROR=--duration must be between 4 and 12 seconds, got {args.duration}.")
            sys.exit(1)
        # Resolution
        if args.resolution not in VALID_RESOLUTIONS:
            print(f"ERROR=--resolution must be one of {VALID_RESOLUTIONS}, got '{args.resolution}'.")
            sys.exit(1)
        # Aspect ratio
        if args.aspect_ratio not in VALID_ASPECT_RATIOS:
            print(f"ERROR=--aspect-ratio must be one of {VALID_ASPECT_RATIOS}, got '{args.aspect_ratio}'.")
            sys.exit(1)
        # Image-to-video: inputs must have exactly one image
        if args.inputs is not None:
            if len(args.inputs) != 1:
                print("ERROR=Video image-to-video requires exactly one input image (--inputs <path>).")
                sys.exit(1)
        # End image without start image
        if args.end_image is not None and args.inputs is None:
            print("ERROR=--end-image requires --inputs (start frame) to be provided.")
            sys.exit(1)

    # Image-specific validations (fal caps)
    if is_fal_image:
        if args.inputs is not None and len(args.inputs) > 4:
            print("ERROR=Image edit mode supports at most 4 input images.")
            sys.exit(1)


# ── Codex / GPT Image 2 backend ──────────────────────────────────────────────


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
        raise ValueError(f"Unsupported image format for gptimage2: {path}")
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
):
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
    log_data = {
        "filename": image_filename,
        "prompt": args.prompt,
        "model": endpoint,
        "mode": mode,
        "seed": None if seed_display == "n/a" else (None if seed_display == "random" else seed_display),
        "width": args.width,
        "height": args.height,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": [str(Path(e["path"])) for e in input_md_entries] if mode == "edit" else [],
        **log_extra,
    }
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)

    print(f"FILENAME={image_filename} PROMPT={args.prompt} SEED={seed_display}")


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


def run_image(args):
    """Route image models to fal.ai or Codex backends."""
    if args.model in CODEX_IMAGE_MODELS:
        run_image_codex(args)
    else:
        run_image_fal(args)


# ── Video pipeline ───────────────────────────────────────────────────────────

def run_video(args):
    """Execute video generation pipeline (text-to-video or image-to-video)."""
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

    # Write .md file
    md_path = VIDEOS_DIR / f"{base_name}.md"
    inputs_lines = []
    if mode == "image-to-video":
        entry = input_md_entries[0]
        orig = Path(entry["original"])
        if RAW_DIR.exists() and orig.parent.resolve() == RAW_DIR.resolve():
            md_base = orig.stem
            inputs_lines.append(f"- Start frame: [{orig.name}](../../images/{md_base}.md)")
        else:
            inputs_lines.append(f"- Start frame: [{Path(entry['path']).name}](../external/{Path(entry['path']).name})")
        if end_md_entry:
            end_orig = Path(end_md_entry["original"])
            if RAW_DIR.exists() and end_orig.parent.resolve() == RAW_DIR.resolve():
                end_md_base = end_orig.stem
                inputs_lines.append(f"- End frame: [{end_orig.name}](../../images/{end_md_base}.md)")
            else:
                inputs_lines.append(f"- End frame: [{Path(end_md_entry['path']).name}](../external/{Path(end_md_entry['path']).name})")
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

    # Write JSON log
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
        "fal_response": result,
    }
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)

    # Stdout for LLM parsing
    print(f"FILENAME={video_filename} PROMPT={args.prompt} SEED={seed_display}")


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
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random; ignored by gptimage2)")
    parser.add_argument("--enable-web-search", action="store_true", help="Enable web search — nano2 only")
    parser.add_argument(
        "--quality",
        default="medium",
        choices=sorted(VALID_GPT_QUALITIES),
        help="GPT Image 2 quality tier — gptimage2 only (default: medium)",
    )

    # Video args
    parser.add_argument("--end-image", default=None, help="End frame image — seedance2 image-to-video only")
    parser.add_argument("--resolution", default="720p", choices=VALID_RESOLUTIONS, help="Video resolution (default: 720p)")
    parser.add_argument("--aspect-ratio", default="16:9", choices=VALID_ASPECT_RATIOS, help="Video aspect ratio (default: 16:9)")
    parser.add_argument("--duration", type=int, default=5, help="Video duration in seconds, 4-12 (default: 5)")
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
