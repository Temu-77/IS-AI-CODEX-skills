#!/usr/bin/env python3
"""Generate multiple GPT Image 2 banner images in parallel."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from phase_timing_utils import record_phase_event, utc_now_iso
except ImportError:  # pragma: no cover
    record_phase_event = None  # type: ignore[assignment]

    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True, help="gpt_image_prompt.json。")
    parser.add_argument("--output-dir", help="生成画像の保存先。未指定時はprompt-fileの親ディレクトリ。")
    parser.add_argument("--concept-ids", help="カンマ区切りのconcept ID。未指定時はpromptファイル内の全prompts。")
    parser.add_argument("--mode", choices=["generate", "edit"], default="generate")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", help="生成サイズ。未指定時はpromptファイルのgeneration_size。")
    parser.add_argument("--quality", choices=["low", "medium", "high", "auto"], default="medium")
    parser.add_argument("--final-size", help="別名リサイズ版が必要な場合の最終サイズ。")
    parser.add_argument("--resize-to-final-size", action="store_true", help="明示時だけfinal-sizeへ上書きリサイズする。")
    parser.add_argument("--source-image", action="append", default=[], help="editモードの参照画像。複数指定可。")
    parser.add_argument("--mask", help="editモードのmask画像。")
    parser.add_argument("--concurrency", type=int, default=4, help="並列数。初期値は4。")
    parser.add_argument("--skip-existing", action="store_true", help="出力PNGがあれば再生成しない。")
    parser.add_argument("--dry-run", action="store_true", help="APIを呼ばずrequest previewだけ作る。")
    parser.add_argument("--report", help="batch reportの出力先。未指定時は<output-dir>/image_generation_batch_report.json。")
    return parser.parse_args()


def load_prompt_data(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("prompts"), list):
        raise ValueError("prompt-file must be a gpt_image_prompt.json with a prompts array.")
    return data


def default_concept_ids(data: dict[str, Any]) -> list[str]:
    ids = [str(item.get("concept_id", "")).strip() for item in data.get("prompts", [])]
    return [concept_id for concept_id in ids if concept_id]


def split_concept_ids(value: str | None, data: dict[str, Any]) -> list[str]:
    if not value:
        return default_concept_ids(data)
    return [item.strip() for item in value.split(",") if item.strip()]


def command_for_concept(args: argparse.Namespace, script_path: Path, prompt_path: Path, output_path: Path, concept_id: str) -> list[str]:
    command = [
        sys.executable,
        str(script_path),
        "--prompt-file",
        str(prompt_path),
        "--concept-id",
        concept_id,
        "--output",
        str(output_path),
        "--mode",
        args.mode,
        "--model",
        args.model,
        "--quality",
        args.quality,
    ]
    if args.size:
        command.extend(["--size", args.size])
    if args.final_size:
        command.extend(["--final-size", args.final_size])
    if args.resize_to_final_size:
        command.append("--resize-to-final-size")
    for source_image in args.source_image:
        command.extend(["--source-image", source_image])
    if args.mask:
        command.extend(["--mask", args.mask])
    if args.dry_run:
        command.append("--dry-run")
    return command


def run_one(command: list[str], concept_id: str, output_path: Path, skipped: bool) -> dict[str, Any]:
    started_at = utc_now_iso()
    if skipped:
        return {
            "concept_id": concept_id,
            "output": str(output_path),
            "status": "skipped_existing",
            "started_at": started_at,
            "ended_at": utc_now_iso(),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=360)
    except subprocess.TimeoutExpired as exc:
        return {
            "concept_id": concept_id,
            "output": str(output_path),
            "status": "timeout",
            "started_at": started_at,
            "ended_at": utc_now_iso(),
            "returncode": 124,
            "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "Timed out after 360 seconds.",
        }
    return {
        "concept_id": concept_id,
        "output": str(output_path),
        "status": "completed" if completed.returncode == 0 else "failed",
        "started_at": started_at,
        "ended_at": utc_now_iso(),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }


def main() -> int:
    args = parse_args()
    prompt_path = Path(args.prompt_file).expanduser().resolve()
    data = load_prompt_data(prompt_path)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else prompt_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).expanduser().resolve() if args.report else output_dir / "image_generation_batch_report.json"
    script_path = Path(__file__).resolve().with_name("generate_gpt_image2.py")
    concept_ids = split_concept_ids(args.concept_ids, data)
    if not concept_ids:
        raise SystemExit("No concept IDs found.")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")

    started_at = utc_now_iso()
    jobs: list[tuple[str, Path, list[str], bool]] = []
    for concept_id in concept_ids:
        output_path = output_dir / f"generated_image_{concept_id}.png"
        skipped = args.skip_existing and output_path.exists()
        command = command_for_concept(args, script_path, prompt_path, output_path, concept_id)
        jobs.append((concept_id, output_path, command, skipped))

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(run_one, command, concept_id, output_path, skipped) for concept_id, output_path, command, skipped in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['concept_id']}: {result['status']} -> {result['output']}")

    results.sort(key=lambda item: item["concept_id"])
    failed = [item for item in results if item["returncode"] != 0]
    report = {
        "created_at": utc_now_iso(),
        "started_at": started_at,
        "ended_at": utc_now_iso(),
        "prompt_file": str(prompt_path),
        "mode": args.mode,
        "model": args.model,
        "quality": args.quality,
        "size": args.size or data.get("generation_size"),
        "concurrency": args.concurrency,
        "source_image_count": len(args.source_image),
        "results": results,
        "status": "failed" if failed else "completed",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if record_phase_event is not None:
        record_phase_event(
            output_dir,
            "phase_1",
            "image_generation_batch",
            status=report["status"],
            started_at=started_at,
            extra={
                "concept_count": len(concept_ids),
                "quality": args.quality,
                "concurrency": args.concurrency,
                "report": str(report_path),
            },
        )
    print(f"Batch report: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
