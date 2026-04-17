#!/usr/bin/env python3
"""mediagen.py — Image and video generation via fal.ai

Usage (image):
  python mediagen.py \
    --model <flux2|nano2> \
    --prompt "..." \
    [--inputs <path1> [<path2> ...]] \
    [--width 1280] \
    [--height 720] \
    [--steps 28] \
    [--seed 42] \
    [--enable-web-search]

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

import argparse
import json
import os
import shutil
import signal
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import fal_client

# ── Constants ────────────────────────────────────────────────────────────────

WORKSPACE = Path(os.environ.get("MEDIAGEN_WORKSPACE", os.path.expanduser("~/.hermes/workspace/mediagen")))
IMAGES_DIR = WORKSPACE / "images"
RAW_DIR = IMAGES_DIR / "raw"
VIDEOS_DIR = WORKSPACE / "videos"
VIDEOS_RAW_DIR = VIDEOS_DIR / "raw"
EXTERNAL_DIR = WORKSPACE / "external"
LOGS_DIR = WORKSPACE / "logs"

IMAGE_MODELS = {"flux2", "nano2"}
VIDEO_MODELS = {"seedance2"}

VALID_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "auto"}
VALID_RESOLUTIONS = {"480p", "720p", "1080p"}

MODEL_MAP = {
    "flux2": {
        "generate": "fal-ai/flux-2",
        "edit": "fal-ai/flux-2/edit",
    },
    "nano2": {
        "generate": "fal-ai/nano-banana-2",
        "edit": "fal-ai/nano-banana-2/edit",
    },
    "seedance2": {
        "text-to-video": "fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
        "image-to-video": "fal-ai/bytedance/seedance/v1.5/pro/image-to-video",
    },
}

IMAGE_TIMEOUT_SECONDS = 120
VIDEO_TIMEOUT_SECONDS = 300

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


def upload_to_fal(path: str) -> str:
    """Upload a file to fal.ai storage and return the public URL."""
    return fal_client.upload_file(path)


def download_file(url: str, dest: Path):
    """Download a file from a URL to a local path."""
    urllib.request.urlretrieve(url, str(dest))


def width_height_to_aspect_ratio(width: int, height: int) -> str:
    """Convert width/height to aspect ratio string for nano2."""
    from math import gcd
    g = gcd(width, height)
    return f"{width // g}:{height // g}"


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

    # Image-only args used with video model
    if is_video_model:
        if hasattr(args, 'width') and (args.width != 1280 or args.height != 720):
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

    # Video-only args used with image model
    if is_image_model:
        if hasattr(args, 'resolution') and args.resolution != "720p":
            print("ERROR=--resolution is not supported for image models. Use --width/--height instead.")
            sys.exit(1)
        if hasattr(args, 'aspect_ratio_set') and args.aspect_ratio != "16:9":
            print("ERROR=--aspect-ratio is not supported for image models. Use --width/--height instead.")
            sys.exit(1)
        if hasattr(args, 'duration') and args.duration != 5:
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

    # Image-specific validations
    if is_image_model:
        if args.inputs is not None and len(args.inputs) > 4:
            print("ERROR=Image edit mode supports at most 4 input images.")
            sys.exit(1)


# ── Image pipeline ──────────────────────────────────────────────────────────

def run_image(args):
    """Execute image generation/edit pipeline."""
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
    except fal_client.client.FalClientError as e:
        print(f"ERROR=fal.ai API error: {e}")
        sys.exit(1)
    except TimeoutError as e:
        print(f"ERROR={e}. Try again or use a different model.")
        sys.exit(1)
    except Exception as e:
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

    # Write .md file
    md_path = IMAGES_DIR / f"{base_name}.md"
    inputs_section = ""
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

    seed_display = returned_seed if returned_seed is not None else "random"
    size_str = f"{args.width}x{args.height}" if model_key == "flux2" else api_args.get("aspect_ratio", f"{args.width}x{args.height}")

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

    # Write JSON log
    log_path = LOGS_DIR / f"{base_name}.json"
    log_data = {
        "filename": image_filename,
        "prompt": args.prompt,
        "model": endpoint,
        "mode": mode,
        "seed": returned_seed,
        "width": args.width,
        "height": args.height,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": [str(Path(e["path"])) for e in input_md_entries] if mode == "edit" else [],
        "fal_response": result,
    }
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)

    # Stdout for LLM parsing
    print(f"FILENAME={image_filename} PROMPT={args.prompt} SEED={seed_display}")


# ── Video pipeline ───────────────────────────────────────────────────────────

def run_video(args):
    """Execute video generation pipeline (text-to-video or image-to-video)."""
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
    except fal_client.client.FalClientError as e:
        print(f"ERROR=fal.ai API error: {e}")
        sys.exit(1)
    except TimeoutError as e:
        print(f"ERROR={e}. Try again or use a different model.")
        sys.exit(1)
    except Exception as e:
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
    parser = argparse.ArgumentParser(description="mediagen — Image and video generation via fal.ai")
    parser.add_argument("--model", required=True, choices=all_models, help="Model to use")
    parser.add_argument("--prompt", required=True, help="Text prompt for generation")

    # Image args
    parser.add_argument("--inputs", nargs="*", default=None, help="Input images: for image edit mode or image-to-video")
    parser.add_argument("--width", type=int, default=1280, help="Output width — image only (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Output height — image only (default: 720)")
    parser.add_argument("--steps", type=int, default=28, help="Inference steps — flux2 only (default: 28)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random)")
    parser.add_argument("--enable-web-search", action="store_true", help="Enable web search — nano2 only")

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
