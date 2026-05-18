#!/usr/bin/env python3
"""Resize banner ads with GPT Image 2 plus Adobe Firefly."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: requests. Install with: pip install requests") from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: Pillow. Install with: pip install pillow") from exc


GPT_IMAGE_2_CONSTRAINTS = {
    "multiple": 16,
    "max_edge": 3840,
    "max_aspect_ratio": 3,
    "min_pixels": 655_360,
    "max_pixels": 8_294_400,
}

FIREFLY_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
FIREFLY_API_BASE_URL = "https://firefly-api.adobe.io"
FIREFLY_SCOPE = "openid,AdobeID,ff_apis,firefly_api"
OPENAI_IMAGE_EDITS_ENDPOINT = "https://api.openai.com/v1/images/edits"
PACK_ENV_FILE = Path.home() / ".config/acrc-codex-skills/.env"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(OPENAI_API_KEY\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(FIREFLY_CLIENT_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(FIREFLY_SERVICES_CLIENT_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(access[_-]?token\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(sig=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"(code=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


@dataclass
class SizeSpec:
    target_w: int
    target_h: int
    safe_w: int
    safe_h: int
    raw: str

    @property
    def label(self) -> str:
        return f"{self.target_w}x{self.target_h}_safe_{self.safe_w}x{self.safe_h}"


@dataclass
class Attempt:
    safe_w: int
    safe_h: int


def load_env_file(path: Path | None) -> None:
    candidates: list[Path] = []
    if path:
        candidates.append(path)
    else:
        candidates.extend([Path.cwd() / ".env.local", Path.cwd() / ".env", PACK_ENV_FILE])

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    for candidate in candidates:
        if not candidate.exists():
            continue
        if load_dotenv:
            load_dotenv(candidate)
            continue
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("("):
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return ""


def parse_axis(value: str, fallback: int) -> int:
    cleaned = value.strip().lower()
    if cleaned in {"", "_", "*", "auto", "target"}:
        return fallback
    if not cleaned.isdigit():
        raise ValueError(f"Invalid dimension value: {value!r}")
    parsed = int(cleaned)
    if parsed <= 0:
        raise ValueError("Dimensions must be positive integers.")
    return parsed


def split_dims(value: str, fallback_w: int | None = None, fallback_h: int | None = None) -> tuple[int, int]:
    match = re.fullmatch(r"\s*([^xX]+)\s*[xX]\s*([^xX]+)\s*", value)
    if not match:
        raise ValueError(f"Expected dimensions like WIDTHxHEIGHT, got: {value!r}")
    fw = fallback_w if fallback_w is not None else -1
    fh = fallback_h if fallback_h is not None else -1
    width = parse_axis(match.group(1), fw)
    height = parse_axis(match.group(2), fh)
    return width, height


def parse_size_spec(raw: str) -> SizeSpec:
    value = raw.strip()
    if not value:
        raise ValueError("Empty size spec.")

    if ":" in value:
        target_part, safe_part = value.split(":", 1)
    elif "@" in value:
        target_part, safe_part = value.split("@", 1)
    else:
        target_part, safe_part = value, ""

    target_w, target_h = split_dims(target_part)
    if safe_part.strip():
        safe_w, safe_h = split_dims(safe_part, target_w, target_h)
    else:
        safe_w, safe_h = target_w, target_h

    if safe_w > target_w or safe_h > target_h:
        raise ValueError(
            f"Safe area {safe_w}x{safe_h} cannot exceed target {target_w}x{target_h}."
        )

    return SizeSpec(target_w=target_w, target_h=target_h, safe_w=safe_w, safe_h=safe_h, raw=raw)


def build_safe_area_attempts(spec: SizeSpec) -> list[Attempt]:
    attempts = [Attempt(spec.safe_w, spec.safe_h)]
    if spec.safe_w != spec.target_w or spec.safe_h != spec.target_h:
        attempts.append(
            Attempt(
                int(round((spec.safe_w + spec.target_w) / 2)),
                int(round((spec.safe_h + spec.target_h) / 2)),
            )
        )
        attempts.append(Attempt(spec.target_w, spec.target_h))

    seen: set[tuple[int, int]] = set()
    unique: list[Attempt] = []
    for attempt in attempts:
        key = (attempt.safe_w, attempt.safe_h)
        if key in seen:
            continue
        seen.add(key)
        unique.append(attempt)
    return unique


def clamp(value: int, min_v: int, max_v: int) -> int:
    return min(max_v, max(min_v, value))


def round_to_multiple(value: int, step: int) -> int:
    return int(round(value / step) * step)


def ceil_to_multiple(value: int, step: int) -> int:
    return int(math.ceil(value / step) * step)


def floor_to_multiple(value: int, step: int) -> int:
    return int(math.floor(value / step) * step)


def is_gpt_image_2_size_valid(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    if width % GPT_IMAGE_2_CONSTRAINTS["multiple"] != 0:
        return False
    if height % GPT_IMAGE_2_CONSTRAINTS["multiple"] != 0:
        return False
    if width >= GPT_IMAGE_2_CONSTRAINTS["max_edge"] or height >= GPT_IMAGE_2_CONSTRAINTS["max_edge"]:
        return False
    if max(width, height) / min(width, height) > GPT_IMAGE_2_CONSTRAINTS["max_aspect_ratio"]:
        return False
    total_pixels = width * height
    if total_pixels < GPT_IMAGE_2_CONSTRAINTS["min_pixels"] or total_pixels > GPT_IMAGE_2_CONSTRAINTS["max_pixels"]:
        return False
    return True


def choose_best_gpt_image_2_size(requested_width: int, requested_height: int) -> dict[str, Any]:
    req_w = max(1, int(round(requested_width)))
    req_h = max(1, int(round(requested_height)))
    target_ratio = req_w / req_h
    target_pixels = req_w * req_h
    best: dict[str, Any] | None = None
    score_rows: list[dict[str, Any]] = []

    step = GPT_IMAGE_2_CONSTRAINTS["multiple"]
    for width in range(step, GPT_IMAGE_2_CONSTRAINTS["max_edge"], step):
        ratio_min_h = ceil_to_multiple(math.ceil(width / GPT_IMAGE_2_CONSTRAINTS["max_aspect_ratio"]), step)
        ratio_max_h = floor_to_multiple(math.floor(width * GPT_IMAGE_2_CONSTRAINTS["max_aspect_ratio"]), step)
        min_pixel_h = ceil_to_multiple(math.ceil(GPT_IMAGE_2_CONSTRAINTS["min_pixels"] / width), step)
        max_pixel_h = floor_to_multiple(math.floor(GPT_IMAGE_2_CONSTRAINTS["max_pixels"] / width), step)
        min_h = max(step, ratio_min_h, min_pixel_h)
        max_h = min(GPT_IMAGE_2_CONSTRAINTS["max_edge"] - step, ratio_max_h, max_pixel_h)
        if min_h > max_h:
            continue

        preferred_h = clamp(round_to_multiple(req_h, step), min_h, max_h)
        candidate_heights = sorted(
            set(
                [
                    preferred_h,
                    clamp(preferred_h - step, min_h, max_h),
                    clamp(preferred_h + step, min_h, max_h),
                    min_h,
                    max_h,
                ]
            )
        )

        for height in candidate_heights:
            if not is_gpt_image_2_size_valid(width, height):
                continue
            ratio = width / height
            ratio_penalty = abs(math.log(ratio / target_ratio))
            width_penalty = abs(width - req_w) / req_w
            height_penalty = abs(height - req_h) / req_h
            pixel_penalty = abs((width * height) - target_pixels) / max(target_pixels, 1)
            undersize_penalty = 0.08 if (width < req_w or height < req_h) else 0.0
            score = width_penalty + height_penalty + (ratio_penalty * 0.6) + (pixel_penalty * 0.2) + undersize_penalty
            row = {"width": width, "height": height, "score": score, "ratio": ratio, "pixels": width * height}
            score_rows.append(row)
            if best is None or score < best["score"]:
                best = row

    if best is None:
        raise ValueError("No valid GPT Image 2 size found for the requested dimensions.")

    gcd_value = math.gcd(best["width"], best["height"])
    top_rows = sorted(score_rows, key=lambda row: row["score"])[:10]
    return {
        "width": best["width"],
        "height": best["height"],
        "size": f"{best['width']}x{best['height']}",
        "ratio_label": f"{best['width'] // gcd_value}:{best['height'] // gcd_value}",
        "total_pixels": best["pixels"],
        "top_candidates": top_rows,
    }


PROMPT_TEMPLATE = """Role
You are a Banner Re-Sizer engine that outputs a finished ad banner image only, with no explanatory text.

Task
Input:
- original_banner image
- target_size: {target_w}x{target_h} pixels
- safe_area_size: {safe_w}x{safe_h} pixels

Output:
- exactly one finished banner image that preserves the original banner's critical content while ensuring all important elements fit fully inside the provided safe area

Context / Constraints
- Use only the elements that actually exist in the source banner.
- Do not invent, add, replace, or infer missing elements.
- If the original banner does not contain a logo, CTA, price, product shot, legal line, or other element, do not create one.
- Preserve all essential elements that are present in the source banner, including product shot, logo, headline, body copy, price or offer, CTA, and legal text when present.
- Keep all critical existing elements fully visible, legible, and undistorted.
- Do not crop out, warp, recolor, rewrite, or restyle essential content.
- Maintain original brand identity, colors, typography style, hierarchy, and message.
- Adapt composition with proportional scaling, repositioning, layout reflow, and background extension when needed.
- Background may extend beyond the safe area.
- Only critical content must remain fully inside the safe area.
- Do not draw, label, or visualize the safe area.

Safe Area Rules
- Treat safe_area_size as the centered protected content zone.
- Price, CTA, logo, and legal text must remain fully inside the safe area if they exist.
- No critical text or object may extend outside the safe area.
- Backgrounds, textures, and non-critical decoration may extend outside.

Output Format
- Return only the generated final banner image.
- No captions, no JSON, no notes, no overlays, no additional text.

Stop Conditions
- End immediately after returning the single final banner image.
- If the banner cannot be safely adapted while preserving critical existing content inside the safe area, return exactly: ERROR
"""


def build_prompt(spec: SizeSpec, attempt: Attempt, edit_instruction: str = "") -> str:
    prompt = PROMPT_TEMPLATE.format(
        target_w=spec.target_w,
        target_h=spec.target_h,
        safe_w=attempt.safe_w,
        safe_h=attempt.safe_h,
    )
    if edit_instruction.strip():
        prompt += (
            "\nUser Edit Request\n"
            f"- Apply this requested change while preserving target size and safe area: {edit_instruction.strip()}\n"
            "- If the request conflicts with source-only content preservation or safe-area placement, prioritize safe placement and legibility.\n"
        )
    return prompt


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def base64_to_image(data: str) -> Image.Image:
    return Image.open(BytesIO(base64.b64decode(data))).convert("RGBA")


def generate_with_gpt_image_2(
    source_image: Image.Image,
    spec: SizeSpec,
    attempt: Attempt,
    prompt: str,
    quality: str,
) -> tuple[Image.Image, dict[str, Any]]:
    api_key = env_first("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing.")

    plan = choose_best_gpt_image_2_size(attempt.safe_w, attempt.safe_h)
    png_bytes = image_to_png_bytes(source_image)
    files = {"image[]": ("source.png", png_bytes, "image/png")}
    data = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "size": plan["size"],
        "quality": quality,
        "output_format": "png",
    }

    response = requests.post(
        OPENAI_IMAGE_EDITS_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        data=data,
        files=files,
        timeout=240,
    )
    try:
        response_json = response.json()
    except Exception:
        response_json = {"raw": response.text}

    if response.status_code != 200:
        details = (
            response_json.get("error", {}).get("message")
            if isinstance(response_json.get("error"), dict)
            else None
        )
        details = details or response_json.get("message") or json.dumps(response_json)[:1000]
        raise ValueError(f"OpenAI GPT Image 2 request failed: {details}")

    data_list = response_json.get("data") or []
    image_b64 = data_list[0].get("b64_json") if data_list else None
    if not image_b64:
        raise ValueError(f"OpenAI GPT Image 2 returned no image payload: {response_json}")

    meta = {
        "provider": "openai",
        "model": "gpt-image-2",
        "quality": quality,
        "attempt": asdict(attempt),
        "size": plan["size"],
        "ratio": plan["ratio_label"],
        "pixels": plan["total_pixels"],
    }
    return base64_to_image(image_b64), meta


def normalize_to_safe_area(image: Image.Image, safe_w: int, safe_h: int) -> tuple[Image.Image, dict[str, Any]]:
    img_w, img_h = image.size
    if img_w == safe_w and img_h == safe_h:
        return image, {"anchor": "none", "scale": 1.0, "new_w": img_w, "new_h": img_h}

    scale_w = safe_w / img_w
    scale_h = safe_h / img_h
    anchor = "width" if scale_w >= scale_h else "height"
    scale = max(scale_w, scale_h)
    resized_w = max(1, int(round(img_w * scale)))
    resized_h = max(1, int(round(img_h * scale)))
    resized = image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    sx = max(0, int(round((resized_w - safe_w) / 2)))
    sy = max(0, int(round((resized_h - safe_h) / 2)))
    cropped = resized.crop((sx, sy, sx + safe_w, sy + safe_h))
    return cropped, {"anchor": anchor, "scale": scale, "new_w": safe_w, "new_h": safe_h}


def firefly_credentials() -> tuple[str, str]:
    client_id = env_first("FIREFLY_CLIENT_ID", "FIREFLY_SERVICES_CLIENT_ID")
    client_secret = env_first("FIREFLY_CLIENT_SECRET", "FIREFLY_SERVICES_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("FIREFLY_CLIENT_ID and FIREFLY_CLIENT_SECRET are required for Firefly outpaint.")
    return client_id, client_secret


def retrieve_firefly_access_token() -> str:
    client_id, client_secret = firefly_credentials()
    form = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": FIREFLY_SCOPE,
    }
    response = requests.post(
        FIREFLY_TOKEN_URL,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=120,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if not response.ok:
        detail = payload.get("error_description") or payload.get("error") or f"Token failed: {payload}"
        raise ValueError(redact(str(detail)))
    token = payload.get("access_token")
    if not token:
        raise ValueError(f"Adobe token response did not include access_token: {payload}")
    return token


def firefly_headers(access_token: str, content_type: str | None = None, content_length: int | None = None, api_key_header: str = "X-API-Key") -> dict[str, str]:
    client_id, _ = firefly_credentials()
    headers = {
        "Authorization": f"Bearer {access_token}",
        api_key_header: client_id,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    return headers


def upload_image_to_firefly(image: Image.Image, access_token: str) -> str:
    png_bytes = image_to_png_bytes(image)
    response = requests.post(
        f"{FIREFLY_API_BASE_URL}/v2/storage/image",
        headers=firefly_headers(access_token, content_type="image/png", content_length=len(png_bytes)),
        data=png_bytes,
        timeout=180,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if not response.ok:
        detail = payload.get("message") or f"Firefly upload failed: {payload}"
        raise ValueError(redact(str(detail)))
    images = payload.get("images") or []
    if not images or not images[0].get("id"):
        raise ValueError(f"Firefly upload response missing image id: {payload}")
    return images[0]["id"]


def extract_firefly_output_url(payload: dict[str, Any]) -> str | None:
    paths = [
        ("result", "outputs", 0, "image", "url"),
        ("outputs", 0, "image", "url"),
    ]
    for path in paths:
        cur: Any = payload
        try:
            for part in path:
                cur = cur[part]
            if isinstance(cur, str) and cur:
                return cur
        except Exception:
            continue
    return None


def assert_allowed_status_url(status_url: str) -> str:
    parsed = urlparse(status_url)
    if parsed.scheme != "https":
        raise ValueError("Firefly statusUrl must use HTTPS.")
    host = parsed.hostname or ""
    if host == "firefly-api.adobe.io" or re.fullmatch(r"firefly-[a-z0-9-]+\.adobe\.io", host, re.IGNORECASE):
        return status_url
    raise ValueError(f"Firefly statusUrl host is not allowed: {host}")


def expand_firefly_image(
    upload_id: str,
    target_w: int,
    target_h: int,
    access_token: str,
    poll_interval: float,
    poll_timeout: float,
) -> str:
    body = {
        "numVariations": 1,
        "size": {"width": target_w, "height": target_h},
        "image": {"source": {"uploadId": upload_id}},
    }
    response = requests.post(
        f"{FIREFLY_API_BASE_URL}/v3/images/expand-async",
        headers=firefly_headers(access_token, content_type="application/json", api_key_header="X-Api-Key"),
        json=body,
        timeout=180,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if not response.ok:
        detail = payload.get("message") or f"Firefly expand request failed: {payload}"
        raise ValueError(redact(str(detail)))

    immediate_url = extract_firefly_output_url(payload)
    if immediate_url:
        return immediate_url

    status_url = payload.get("statusUrl")
    if not status_url:
        raise ValueError(f"Firefly expand response missing statusUrl: {payload}")
    status_url = assert_allowed_status_url(status_url)

    deadline = time.monotonic() + poll_timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        status_response = requests.get(
            status_url,
            headers=firefly_headers(access_token, api_key_header="X-Api-Key"),
            timeout=60,
        )
        try:
            status_payload = status_response.json()
        except Exception:
            status_payload = {"raw": status_response.text}
        if not status_response.ok:
            detail = status_payload.get("message") or f"Firefly status polling failed: {status_payload}"
            raise ValueError(redact(str(detail)))

        status = (status_payload.get("status") or "").lower()
        if status == "succeeded":
            output_url = extract_firefly_output_url(status_payload)
            if output_url:
                return output_url
            raise ValueError(f"Firefly succeeded but response had no image URL: {status_payload}")
        if status == "failed":
            raise ValueError(f"Firefly job failed: {status_payload}")

    raise TimeoutError("Firefly expand polling timed out.")


def download_image(url: str) -> Image.Image:
    response = requests.get(url, timeout=240)
    if not response.ok:
        raise ValueError(f"Failed to download Firefly image: HTTP {response.status_code}")
    return Image.open(BytesIO(response.content)).convert("RGBA")


def exact_target(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    if image.size == (target_w, target_h):
        return image
    return image.resize((target_w, target_h), Image.Resampling.LANCZOS)


def sanitize_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return value or "banner"


def dry_run_plan(specs: list[SizeSpec]) -> list[dict[str, Any]]:
    rows = []
    for spec in specs:
        attempts = build_safe_area_attempts(spec)
        attempt_rows = []
        for attempt in attempts:
            plan = choose_best_gpt_image_2_size(attempt.safe_w, attempt.safe_h)
            attempt_rows.append({"attempt": asdict(attempt), "gpt_image_2_plan": {k: v for k, v in plan.items() if k != "top_candidates"}})
        rows.append({"size": asdict(spec), "model": "gpt-image-2", "attempts": attempt_rows, "needs_firefly": spec.safe_w != spec.target_w or spec.safe_h != spec.target_h})
    return rows


def process_one(
    source_image: Image.Image,
    spec: SizeSpec,
    args: argparse.Namespace,
    output_dir: Path,
) -> dict[str, Any]:
    print(f"\n=== {spec.raw} -> target {spec.target_w}x{spec.target_h}, safe {spec.safe_w}x{spec.safe_h} ===")
    attempt_errors: list[str] = []
    master_image: Image.Image | None = None
    generation_meta: dict[str, Any] | None = None
    used_attempt: Attempt | None = None

    for attempt in build_safe_area_attempts(spec):
        prompt = build_prompt(spec, attempt, args.edit_instruction)
        print(f"Trying gpt-image-2 safe-area generation at {attempt.safe_w}x{attempt.safe_h}...")
        try:
            master_image, generation_meta = generate_with_gpt_image_2(
                source_image,
                spec,
                attempt,
                prompt,
                args.gpt_quality,
            )
            used_attempt = attempt
            print(f"Safe-area generation succeeded. Master size: {master_image.size[0]}x{master_image.size[1]}")
            break
        except Exception as exc:
            message = f"{attempt.safe_w}x{attempt.safe_h}: {exc}"
            attempt_errors.append(message)
            print(f"Attempt failed: {message}")

    if master_image is None or generation_meta is None or used_attempt is None:
        raise RuntimeError("Generation failed for all safe-area attempts:\n" + "\n".join(attempt_errors))

    normalized, normalize_meta = normalize_to_safe_area(master_image, used_attempt.safe_w, used_attempt.safe_h)

    output_stem = sanitize_filename(spec.label)
    output_path = output_dir / f"{output_stem}.png"
    intermediate_paths: dict[str, str] = {}
    if args.keep_intermediates:
        master_path = output_dir / f"{output_stem}_master.png"
        safe_path = output_dir / f"{output_stem}_safe.png"
        master_image.save(master_path)
        normalized.save(safe_path)
        intermediate_paths = {"master": str(master_path), "safe": str(safe_path)}

    if used_attempt.safe_w == spec.target_w and used_attempt.safe_h == spec.target_h:
        final_image = exact_target(normalized, spec.target_w, spec.target_h)
        firefly_meta = {"used": False, "reason": "safe_area_matches_target"}
    else:
        print("Uploading normalized safe-area image to Adobe Firefly...")
        token = retrieve_firefly_access_token()
        upload_id = upload_image_to_firefly(normalized, token)
        print(f"Firefly upload id: {upload_id}")
        output_url = expand_firefly_image(
            upload_id,
            spec.target_w,
            spec.target_h,
            token,
            poll_interval=args.firefly_poll_interval,
            poll_timeout=args.firefly_poll_timeout,
        )
        print("Firefly expand succeeded. Downloading final image...")
        final_image = exact_target(download_image(output_url), spec.target_w, spec.target_h)
        firefly_meta = {"used": True, "upload_id": upload_id, "output_url_saved": False}

    final_image.save(output_path)
    print(f"Saved final: {output_path}")

    return {
        "input_size": list(source_image.size),
        "size": asdict(spec),
        "model": "gpt-image-2",
        "generation": generation_meta,
        "used_attempt": asdict(used_attempt),
        "normalize": normalize_meta,
        "firefly": firefly_meta,
        "output_path": str(output_path),
        "intermediates": intermediate_paths,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resize an existing banner into target sizes using GPT Image 2 plus Adobe Firefly outpaint.",
    )
    parser.add_argument("input_image", help="Path to the source banner image")
    parser.add_argument(
        "--size",
        action="append",
        required=True,
        help="Target and optional safe area, for example 1200x628:1040x508 or 920x1020:500x_",
    )
    parser.add_argument("--gpt-quality", choices=["low", "medium", "high"], default="high")
    parser.add_argument("--output-dir", default="banner-resizer-output")
    parser.add_argument("--env-file", help="Optional .env file to load before running")
    parser.add_argument("--edit-instruction", default="", help="Optional edit instruction to apply during safe-area generation")
    parser.add_argument("--keep-intermediates", action="store_true", help="Save master and normalized safe-area images")
    parser.add_argument("--zip", action="store_true", help="Create a zip archive containing final PNG outputs")
    parser.add_argument("--dry-run", action="store_true", help="Parse sizes and print generation plans without calling APIs")
    parser.add_argument("--firefly-poll-interval", type=float, default=2.0)
    parser.add_argument("--firefly-poll-timeout", type=float, default=240.0)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    load_env_file(Path(args.env_file).expanduser() if args.env_file else None)
    input_path = Path(args.input_image).expanduser().resolve()
    if not input_path.exists():
        parser.error(f"Input image does not exist: {input_path}")

    try:
        specs = [parse_size_spec(raw) for raw in args.size]
    except ValueError as exc:
        parser.error(str(exc))

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        source_image = Image.open(input_path).convert("RGBA")
    except Exception as exc:
        raise SystemExit(f"Could not read image {input_path}: {exc}") from exc

    if args.dry_run:
        plan = dry_run_plan(specs)
        print(json.dumps(plan, indent=2))
        manifest_path = output_dir / "dry_run_plan.json"
        manifest_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Saved dry-run plan: {manifest_path}")
        return 0

    results = []
    for spec in specs:
        try:
            results.append(process_one(source_image, spec, args, output_dir))
        except Exception as exc:
            safe_error = redact(str(exc))
            print(f"[ERROR] {spec.raw}: {safe_error}", file=sys.stderr)
            results.append({"size": asdict(spec), "error": safe_error})

    manifest = {
        "input_image": str(input_path),
        "output_dir": str(output_dir),
        "results": results,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved manifest: {manifest_path}")

    if args.zip:
        zip_path = output_dir / "generated_banners.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for result in results:
                output_path = result.get("output_path")
                if output_path and Path(output_path).exists():
                    archive.write(output_path, arcname=Path(output_path).name)
            archive.write(manifest_path, arcname=manifest_path.name)
        print(f"Saved zip: {zip_path}")

    failed = [result for result in results if result.get("error")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
