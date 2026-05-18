#!/usr/bin/env python3
"""Create a reusable cache for brand guideline and asset analysis inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from phase_timing_utils import record_phase_event, utc_now_iso
except ImportError:  # pragma: no cover - direct reuse outside the skill folder
    record_phase_event = None  # type: ignore[assignment]

    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


SOURCE_KEYS = [
    "orientation_file",
    "brand_guidelines",
    "logos",
    "background_assets",
    "reference_banners",
    "past_creatives",
]

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_TEXT_CHARS = 120_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="入力YAMLまたはrun_summary.json。")
    parser.add_argument("--run-dir", required=True, help="brand_asset_cache.jsonを書き出すrunフォルダ。")
    parser.add_argument("--cache-root", help="キャッシュルート。未指定時は$BANNER_PROPOSAL_CACHE_DIRまたはcwd/.cache/banner-proposal/brand-assets。")
    return parser.parse_args()


def strip_quotes(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_list_key is None:
                continue
            data.setdefault(current_list_key, []).append(strip_quotes(stripped[2:]))
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = strip_quotes(value)
            current_list_key = None
    return data


def load_inputs(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("inputs", data)
    return parse_simple_yaml(path)


def normalize_paths(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def collect_source_paths(inputs: dict[str, Any]) -> list[tuple[str, Path]]:
    collected: list[tuple[str, Path]] = []
    for key in SOURCE_KEYS:
        for raw_path in normalize_paths(inputs.get(key)):
            path = Path(raw_path).expanduser()
            collected.append((key, path if path.is_absolute() else Path.cwd() / path))
    return collected


def default_cache_root() -> Path:
    configured = os.environ.get("BANNER_PROPOSAL_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / ".cache/banner-proposal/brand-assets").resolve()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_text_file(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], "truncated"
    return text, "complete"


def extract_pptx_text(path: Path) -> tuple[str, str]:
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
        for slide_name in slide_names:
            root = ElementTree.fromstring(archive.read(slide_name))
            slide_text = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
            if slide_text:
                texts.append(f"## {Path(slide_name).stem}\n" + "\n".join(slide_text))
    text = "\n\n".join(texts)
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], "truncated"
    return text, "complete"


def extract_pdf_text(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return "", "skipped_missing_pypdf"
    reader = PdfReader(str(path))
    texts: list[str] = []
    for index, page in enumerate(reader.pages[:40], start=1):
        extracted = page.extract_text() or ""
        if extracted.strip():
            texts.append(f"## page {index}\n{extracted.strip()}")
    text = "\n\n".join(texts)
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], "truncated"
    return text, "complete"


def image_metadata(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return {"image_status": "skipped_missing_pillow"}
    try:
        with Image.open(path) as image:
            return {
                "image_status": "read",
                "width": image.size[0],
                "height": image.size[1],
                "mode": image.mode,
                "format": image.format,
            }
    except Exception as exc:  # noqa: BLE001 - metadata is best-effort
        return {"image_status": "failed", "error": str(exc)}


def build_entry(category: str, path: Path, cache_root: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "category": category,
            "source_path": str(path),
            "status": "missing",
        }

    sha = file_sha256(path)
    cache_dir = cache_root / sha[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    extension = path.suffix.lower()
    metadata: dict[str, Any] = {
        "category": category,
        "source_path": str(path),
        "source_name": path.name,
        "sha256": sha,
        "cache_dir": str(cache_dir),
        "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "cached_at": utc_now_iso(),
        "extension": extension,
        "status": "cached",
    }

    extracted_text = ""
    extraction_status = "not_applicable"
    if extension in TEXT_EXTENSIONS:
        extracted_text, extraction_status = extract_text_file(path)
    elif extension == ".pptx":
        extracted_text, extraction_status = extract_pptx_text(path)
    elif extension == ".pdf":
        extracted_text, extraction_status = extract_pdf_text(path)
    elif extension in IMAGE_EXTENSIONS:
        metadata.update(image_metadata(path))

    metadata["text_extraction_status"] = extraction_status
    if extracted_text:
        extracted_path = cache_dir / "extracted_text.txt"
        extracted_path.write_text(extracted_text, encoding="utf-8")
        metadata["extracted_text_path"] = str(extracted_path)
        metadata["extracted_text_chars"] = len(extracted_text)

    (cache_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def build_cache(input_path: Path, run_dir: Path, cache_root: Path) -> dict[str, Any]:
    inputs = load_inputs(input_path)
    started_at = utc_now_iso()
    cache_root.mkdir(parents=True, exist_ok=True)
    entries = [build_entry(category, path, cache_root) for category, path in collect_source_paths(inputs)]
    result = {
        "cache_version": "1.0",
        "created_at": utc_now_iso(),
        "cache_root": str(cache_root),
        "source_input": str(input_path),
        "entries": entries,
    }
    output_path = run_dir / "brand_asset_cache.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if record_phase_event is not None:
        record_phase_event(
            run_dir,
            "phase_1",
            "brand_asset_cache",
            started_at=started_at,
            extra={"entries": len(entries), "cache_root": str(cache_root)},
        )
    return result


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    run_dir = Path(args.run_dir).expanduser().resolve()
    cache_root = Path(args.cache_root).expanduser().resolve() if args.cache_root else default_cache_root()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if not run_dir.exists():
        raise FileNotFoundError(run_dir)
    result = build_cache(input_path, run_dir, cache_root)
    print(f"ブランド資料キャッシュを書き出しました: {run_dir / 'brand_asset_cache.json'}")
    print(f"キャッシュ対象: {len(result['entries'])} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
