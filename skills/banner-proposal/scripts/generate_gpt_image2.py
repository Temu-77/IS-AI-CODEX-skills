#!/usr/bin/env python3
"""Generate or edit a banner image with GPT Image 2.

The script reads OPENAI_API_KEY from the environment and never accepts an API
key as an argument. Use --dry-run to inspect the sanitized request without
calling the API.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


OPENAI_IMAGE_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1] if SKILL_ROOT.parent.name == "skills" else SKILL_ROOT.parent
REPO_OPENAI_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_OPENAI_ENV_FILE = Path.home() / ".config/jt-codex/openai.env"
PACK_ENV_FILE = Path.home() / ".config/acrc-codex-skills/.env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True, help="gpt_image_prompt.json or a JSON/text prompt file.")
    parser.add_argument("--concept-id", default="concept_1", help="Concept ID to select from gpt_image_prompt.json.")
    parser.add_argument("--output", required=True, help="Output PNG path for the generated image.")
    parser.add_argument("--mode", choices=["generate", "edit"], default="generate")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default=None, help="Override generation size. Defaults to file generation_size.")
    parser.add_argument("--quality", default=None, choices=["low", "medium", "high", "auto"])
    parser.add_argument("--final-size", default=None, help="Optional crop/resize size, e.g. 600x500.")
    parser.add_argument(
        "--resize-to-final-size",
        action="store_true",
        help="明示した場合だけ、API返却画像を--final-sizeへトリミング/リサイズする。通常はAPI返却解像度を保持する。",
    )
    parser.add_argument("--source-image", action="append", default=[], help="Source/reference image for edit mode.")
    parser.add_argument("--mask", help="Optional mask image for edit mode.")
    parser.add_argument("--dry-run", action="store_true", help="Write a sanitized request JSON beside output.")
    return parser.parse_args()


def load_prompt(path: Path, concept_id: str) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text.strip(), {}

    if isinstance(data, dict) and isinstance(data.get("prompts"), list):
        for item in data["prompts"]:
            if item.get("concept_id") == concept_id:
                return str(item.get("prompt", "")).strip(), data
        raise KeyError(f"concept_id not found in prompt file: {concept_id}")
    if isinstance(data, dict) and "prompt" in data:
        return str(data["prompt"]).strip(), data
    raise ValueError(f"Unsupported prompt file shape: {path}")


def parse_size(size: str) -> tuple[int, int]:
    try:
        width_text, height_text = size.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except Exception as exc:  # noqa: BLE001 - provide a friendly CLI error
        raise ValueError(f"Invalid size '{size}'. Expected WIDTHxHEIGHT.") from exc
    return width, height


def validate_gpt_image2_size(size: str) -> None:
    width, height = parse_size(size)
    pixels = width * height
    if width % 16 != 0 or height % 16 != 0:
        raise ValueError("GPT Image 2 generation size must use edges that are multiples of 16.")
    if max(width, height) > 3840:
        raise ValueError("GPT Image 2 generation size cannot have an edge above 3840px.")
    if pixels < 655_360 or pixels > 8_294_400:
        raise ValueError("GPT Image 2 generation size must be between 655,360 and 8,294,400 pixels.")
    if max(width, height) / min(width, height) > 3:
        raise ValueError("GPT Image 2 generation size long:short ratio must be at most 3:1.")


def write_request_preview(output_path: Path, request_payload: dict[str, Any]) -> None:
    preview_path = output_path.with_suffix(output_path.suffix + ".request.json")
    preview_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Dry-run request written: {preview_path}")


def unquote_env_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_openai_api_key_from_file(env_file: Path) -> str | None:
    if env_file.exists():
        mode = env_file.stat().st_mode & 0o777
        if mode & 0o077:
            print(f"Warning: {env_file} should be readable only by the current user. Run: chmod 600 {env_file}", file=sys.stderr)
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "OPENAI_API_KEY":
                api_key = unquote_env_value(value)
                if api_key:
                    os.environ["OPENAI_API_KEY"] = api_key
                    return api_key
    return None


def load_openai_api_key(env_file: Path = DEFAULT_OPENAI_ENV_FILE) -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]

    checked_files: list[Path] = []
    for candidate in (Path.cwd() / ".env", REPO_OPENAI_ENV_FILE, PACK_ENV_FILE, env_file):
        if candidate in checked_files:
            continue
        checked_files.append(candidate)
        api_key = load_openai_api_key_from_file(candidate)
        if api_key:
            return api_key

    raise RuntimeError(
        "OPENAI_API_KEY is required. Set it in the environment or in one of: "
        + ", ".join(str(path) for path in checked_files)
        + ". Use file permissions 600 and do not pass API keys as arguments."
    )


def call_generation_api(api_key: str, payload: dict[str, Any]) -> bytes:
    request = urllib.request.Request(
        OPENAI_IMAGE_GENERATIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI image generation failed with HTTP {exc.code}: {detail}") from exc

    data = json.loads(body)
    item = data.get("data", [{}])[0]
    if "b64_json" in item:
        return base64.b64decode(item["b64_json"])
    if "url" in item:
        with urllib.request.urlopen(item["url"], timeout=180) as image_response:
            return image_response.read()
    raise RuntimeError("OpenAI image response did not include b64_json or url.")


def call_edit_api_with_sdk(args: argparse.Namespace, prompt: str, size: str, quality: str) -> bytes:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Edit mode requires the openai Python package. Generation mode uses stdlib only.") from exc

    if not args.source_image:
        raise ValueError("Edit mode requires at least one --source-image.")
    client = OpenAI()
    image_files = [open(Path(path), "rb") for path in args.source_image]
    mask_file = open(Path(args.mask), "rb") if args.mask else None
    try:
        kwargs: dict[str, Any] = {
            "model": args.model,
            "image": image_files if len(image_files) > 1 else image_files[0],
            "prompt": prompt,
            "size": size,
            "quality": quality,
        }
        if mask_file is not None:
            kwargs["mask"] = mask_file
        result = client.images.edit(**kwargs)
        b64_json = result.data[0].b64_json
        if not b64_json:
            raise RuntimeError("OpenAI edit response did not include b64_json.")
        return base64.b64decode(b64_json)
    finally:
        for handle in image_files:
            handle.close()
        if mask_file is not None:
            mask_file.close()


def maybe_resize_and_crop(path: Path, final_size: str | None) -> None:
    if not final_size:
        return
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        print("Pillow is not installed; skipped final resize/crop.", file=sys.stderr)
        return

    target_width, target_height = parse_size(final_size)
    with Image.open(path) as image:
        image = image.convert("RGBA")
        source_width, source_height = image.size
        target_ratio = target_width / target_height
        source_ratio = source_width / source_height

        if source_ratio > target_ratio:
            new_width = int(source_height * target_ratio)
            left = (source_width - new_width) // 2
            crop_box = (left, 0, left + new_width, source_height)
        else:
            new_height = int(source_width / target_ratio)
            top = (source_height - new_height) // 2
            crop_box = (0, top, source_width, top + new_height)

        image = image.crop(crop_box).resize((target_width, target_height), Image.LANCZOS)
        image.save(path)


def get_image_size(path: Path) -> str | None:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None

    try:
        with Image.open(path) as image:
            return f"{image.size[0]}x{image.size[1]}"
    except Exception:  # noqa: BLE001 - metadata is best-effort
        return None


def write_output_metadata(
    output_path: Path,
    request_payload: dict[str, Any],
    requested_final_size: str | None,
    resize_applied: bool,
) -> None:
    metadata = {
        "output_file": str(output_path),
        "model": request_payload.get("model"),
        "requested_generation_size": request_payload.get("size"),
        "quality": request_payload.get("quality"),
        "saved_image_size": get_image_size(output_path),
        "requested_final_size": requested_final_size,
        "resize_applied": resize_applied,
        "delivery_note": "API返却画像を納品マスターとして保存。resize_applied=trueの場合のみ別解像度へ変換。",
    }
    metadata_path = output_path.with_suffix(output_path.suffix + ".metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    prompt_path = Path(args.prompt_file).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prompt, prompt_data = load_prompt(prompt_path, args.concept_id)
    if not prompt:
        raise ValueError("Selected prompt is empty.")

    size = args.size or str(prompt_data.get("generation_size") or "1200x1008")
    quality = args.quality or str(prompt_data.get("quality") or "high")
    final_size = args.final_size or prompt_data.get("final_size")
    validate_gpt_image2_size(size)

    request_payload = {
        "model": args.model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
    }

    if args.dry_run:
        write_request_preview(output_path, request_payload)
        return 0

    api_key = load_openai_api_key()

    if args.mode == "generate":
        image_bytes = call_generation_api(api_key, request_payload)
    else:
        image_bytes = call_edit_api_with_sdk(args, prompt, size, quality)

    output_path.write_bytes(image_bytes)
    resize_applied = False
    if args.resize_to_final_size and final_size:
        maybe_resize_and_crop(output_path, str(final_size))
        resize_applied = True
    write_output_metadata(output_path, request_payload, str(final_size) if final_size else None, resize_applied)
    print(f"Wrote image: {output_path}")
    if not resize_applied:
        print("Kept API output resolution for delivery master.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
