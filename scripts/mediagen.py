#!/usr/bin/env python3
"""mediagen.py — Image generation and editing via fal.ai

Usage:
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
EXTERNAL_DIR = WORKSPACE / "external"
LOGS_DIR = WORKSPACE / "logs"

MODEL_MAP = {
    "flux2": {
        "generate": "fal-ai/flux-2",
        "edit": "fal-ai/flux-2/edit",
    },
    "nano2": {
        "generate": "fal-ai/nano-banana-2",
        "edit": "fal-ai/nano-banana-2/edit",
    },
}

TIMEOUT_SECONDS = 120

# ── Helpers ──────────────────────────────────────────────────────────────────


def ensure_dirs():
    """Create workspace directories if they don't exist."""
    for d in [RAW_DIR, EXTERNAL_DIR, LOGS_DIR]:
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


def download_image(url: str, dest: Path):
    """Download an image from a URL to a local path."""
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


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="mediagen — Image generation via fal.ai")
    parser.add_argument("--model", required=True, choices=["flux2", "nano2"], help="Model to use")
    parser.add_argument("--prompt", required=True, help="Text prompt for generation")
    parser.add_argument("--inputs", nargs="*", default=None, help="Input images for edit mode")
    parser.add_argument("--width", type=int, default=1280, help="Output width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Output height (default: 720)")
    parser.add_argument("--steps", type=int, default=28, help="Inference steps — flux2 only (default: 28)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random)")
    parser.add_argument("--enable-web-search", action="store_true", help="Enable web search — nano2 only")
    args = parser.parse_args()

    # Ensure workspace dirs exist
    ensure_dirs()

    # Determine mode
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
            # Check if input was a previously generated image
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
            raise TimeoutError(f"Timeout after {TIMEOUT_SECONDS}s")
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(TIMEOUT_SECONDS)
        try:
            result = fal_client.subscribe(endpoint, arguments=api_args)
        finally:
            signal.alarm(0)  # cancel alarm
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
    download_image(image_url, image_path)

    # Write .md file
    md_path = IMAGES_DIR / f"{base_name}.md"
    inputs_section = ""
    if mode == "edit":
        lines = []
        for entry in input_md_entries:
            # Check if input was a previously generated image (exists in raw/)
            orig = Path(entry["original"])
            if RAW_DIR.exists() and orig.parent.resolve() == RAW_DIR.resolve():
                # Input was a raw generated image — link to its .md
                md_base = orig.stem
                lines.append(f"- [{orig.name}](./{md_base}.md)")
            else:
                # External file — link to its copy
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


if __name__ == "__main__":
    main()
