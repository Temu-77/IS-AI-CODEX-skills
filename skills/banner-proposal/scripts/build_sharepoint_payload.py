#!/usr/bin/env python3
"""Power Automate SaveCreativeProductionRun用payloadを作成する。

このhelperはJSON payloadだけを作成する。POSTは既存の
power_automate_workflow_templateスクリプトで行う。
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any

from phase_timing_utils import record_phase_event, utc_now_iso


TEXT_ARTIFACTS = [
    "run_summary.json",
    "banner_spec.yaml",
    "banner_concepts.json",
    "gpt_image_prompt.json",
    "qa_report.md",
    "phase_timings.json",
    "brand_asset_cache.json",
    "image_generation_batch_report.json",
    "canvas_outputs.json",
    "human_feedback.md",
]

TEXT_PATTERNS = ["generated_image_*.png.metadata.json"]
IMAGE_PATTERNS = ["generated_image_*.png", "generated_image_*.jpg", "generated_image_*.jpeg", "generated_image_*.webp"]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(OPENAI_API_KEY\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(PA_WORKFLOW_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(FIREFLY_CLIENT_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(FIREFLY_SERVICES_CLIENT_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(access[_-]?token\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(sig=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"(code=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"(shared[_-]?secret\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="成果物が入ったrunフォルダ。")
    parser.add_argument("--output", required=True, help="出力するpayload JSONパス。")
    return parser.parse_args()


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("("):
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def load_run_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_summary.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def text_artifact(path: Path) -> dict[str, Any]:
    content = redact_secrets(path.read_text(encoding="utf-8", errors="replace"))
    return {
        "file_name": path.name,
        "content_type": content_type_for_text(path),
        "content": content,
    }


def image_artifact(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
    return {
        "file_name": path.name,
        "content_type": mime,
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def content_type_for_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix in {".yaml", ".yml"}:
        return "text/yaml; charset=utf-8"
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


def collect_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for name in TEXT_ARTIFACTS:
        path = run_dir / name
        if path.exists():
            artifacts.append(text_artifact(path))

    for pattern in TEXT_PATTERNS:
        for path in sorted(run_dir.glob(pattern)):
            artifacts.append(text_artifact(path))

    seen: set[Path] = set()
    for pattern in IMAGE_PATTERNS:
        for path in sorted(run_dir.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            artifacts.append(image_artifact(path))
    return artifacts


def main() -> int:
    started_at = utc_now_iso()
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not run_dir.exists():
        raise FileNotFoundError(run_dir)

    summary = load_run_summary(run_dir)
    qa = summary.get("qa") or {}
    payload = {
        "run_id": str(summary.get("run_id", run_dir.name)),
        "project_name": str(summary.get("project_name", "")),
        "created_at": str(summary.get("created_at", "")),
        "status": str(summary.get("status", "draft")),
        "qa_score": int(qa.get("score") or 0),
        "qa_summary": redact_secrets(str(qa.get("summary", ""))),
        "artifacts": collect_artifacts(run_dir),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_phase_event(
        run_dir,
        "phase_1",
        "sharepoint_payload_flow1",
        started_at=started_at,
        extra={"output": str(output_path), "artifact_count": len(payload["artifacts"])},
    )
    print(f"SharePoint payloadを書き出しました: {output_path}")
    print(f"含めた成果物数: {len(payload['artifacts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
