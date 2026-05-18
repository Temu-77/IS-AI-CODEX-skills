#!/usr/bin/env python3
"""ユーザー目視フィードバックをhuman_feedback.mdへ保存する。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from phase_timing_utils import record_phase_event, utc_now_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="成果物が入ったrunフォルダ。")
    parser.add_argument("--feedback", help="ユーザーから受け取った目視フィードバック本文。")
    parser.add_argument("--feedback-file", help="フィードバック本文を含むテキスト/Markdownファイル。")
    parser.add_argument("--approval-status", default="pending", choices=["approved", "revise", "rejected", "pending"], help="目視承認ステータス。")
    parser.add_argument("--selected-concept", default="", help="採用または主対象の案ID。例: concept_1")
    parser.add_argument("--append", action="store_true", help="既存のhuman_feedback.mdへ追記する。")
    return parser.parse_args()


def load_feedback(args: argparse.Namespace) -> str:
    if args.feedback_file:
        return Path(args.feedback_file).expanduser().read_text(encoding="utf-8").strip()
    if args.feedback:
        return args.feedback.strip()
    raise SystemExit("--feedback または --feedback-file が必要です。")


def load_summary(run_dir: Path) -> dict:
    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def update_summary(run_dir: Path, status: str, selected_concept: str, feedback_id: str, created_at: str) -> None:
    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        return
    summary = load_summary(run_dir)
    summary["human_feedback"] = {
        "latest_feedback_id": feedback_id,
        "approval_status": status,
        "selected_concept": selected_concept,
        "saved_at": created_at,
        "file": "human_feedback.md",
    }
    history = summary.setdefault("human_feedback_history", [])
    if isinstance(history, list):
        history.append(
            {
                "feedback_id": feedback_id,
                "approval_status": status,
                "selected_concept": selected_concept,
                "saved_at": created_at,
                "file": "human_feedback.md",
            }
        )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    started_at = utc_now_iso()
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        raise FileNotFoundError(run_dir)

    feedback = load_feedback(args)
    created_at_dt = datetime.now(timezone.utc)
    created_at = created_at_dt.isoformat()
    received_at_local = datetime.now().astimezone().isoformat()
    feedback_id = "feedback-" + created_at_dt.strftime("%Y%m%dT%H%M%SZ")
    summary = load_summary(run_dir)
    run_id = str(summary.get("run_id", run_dir.name))
    project_name = str(summary.get("project_name", ""))
    section = "\n".join(
        [
            f"# バナー案チェック(目視)・承認フィードバック: {feedback_id}",
            "",
            "## メタ情報",
            "",
            f"- フィードバックID: {feedback_id}",
            f"- Run ID: {run_id}",
            f"- 案件名: {project_name or '未指定'}",
            f"- 受領日時(UTC): {created_at}",
            f"- 受領日時(ローカル): {received_at_local}",
            f"- フェーズ: Phase 2 / 人間目視フィードバック",
            f"- 承認ステータス: {args.approval_status}",
            f"- 対象/採用案: {args.selected_concept or '未指定'}",
            "",
            "## フィードバック本文",
            "",
            feedback,
            "",
        ]
    )

    output = run_dir / "human_feedback.md"
    if args.append and output.exists():
        existing = output.read_text(encoding="utf-8").rstrip()
        output.write_text(existing + "\n\n---\n\n" + section, encoding="utf-8")
    else:
        output.write_text(section, encoding="utf-8")

    update_summary(run_dir, args.approval_status, args.selected_concept, feedback_id, created_at)
    record_phase_event(
        run_dir,
        "phase_2",
        "human_feedback_saved",
        started_at=started_at,
        extra={
            "feedback_id": feedback_id,
            "approval_status": args.approval_status,
            "selected_concept": args.selected_concept,
        },
    )
    print(f"目視フィードバックを保存しました: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
