#!/usr/bin/env python3
"""安全なバナー案作成runフォルダを準備する。

このヘルパーは外部APIを呼ばない。ユーザー入力ファイルを正規化し、
後続ステップで調査結果、画像生成結果、QA、Canvas出力、SharePoint保存payloadを
埋められるように主要成果物を作成する。
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cache_brand_assets import build_cache, default_cache_root
from phase_timing_utils import init_phase_timings, record_phase_event


CONCEPT_VARIANTS = [
    (
        "主訴求ストレート型",
        "キャンペーンの主訴求を最短距離で伝え、クリック前の理解負荷を下げる。",
        "一目で内容を理解し、詳細確認へ進む。",
    ),
    (
        "ベネフィット対比型",
        "ユーザー課題と提供価値の差分を見せ、利用後の変化を想起させる。",
        "自分ごと化し、便益の確認へ進む。",
    ),
    (
        "信頼・根拠訴求型",
        "ブランドらしさ、信頼要素、素材の質感を前面に出し、不安を減らす。",
        "安心してキャンペーン内容を読む。",
    ),
    (
        "行動喚起型",
        "CTAと参加・購入・申込の動機を明確化し、行動への迷いを減らす。",
        "今すぐ次のアクションを押す。",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="入力YAMLテンプレートのパス。")
    parser.add_argument("--output-dir", required=True, help="run成果物の出力ディレクトリ。")
    parser.add_argument("--run-id", help="任意のrun ID。未指定時はタイムスタンプ。")
    parser.add_argument("--dry-run", action="store_true", help="生成内容をdry-runドラフトとして扱う。")
    parser.add_argument("--overwrite", action="store_true", help="既存の非空ディレクトリへの書き込みを許可する。")
    return parser.parse_args()


def strip_quotes(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    """Parse the simple top-level YAML shape used by the bundled template."""
    data: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if current_list_key is None:
                raise ValueError(f"List item without key in {path}: {raw_line}")
            data.setdefault(current_list_key, []).append(strip_quotes(stripped[2:]))
            continue

        if ":" not in stripped:
            raise ValueError(f"Unsupported YAML line in {path}: {raw_line}")

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = coerce_scalar(strip_quotes(value))
            current_list_key = None

    return data


def coerce_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def quote_yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def sanitize_run_id_part(value: Any) -> str:
    text = str(value or "unknown").strip()
    text = re.sub(r'[\\/:*?"<>|#%&{}~]+', "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-_. ")
    return text[:64] or "unknown"


def build_default_run_id(inputs: dict[str, Any], timestamp: str) -> str:
    client = sanitize_run_id_part(inputs.get("client_name", "client"))
    campaign = sanitize_run_id_part(inputs.get("campaign_name", inputs.get("project_name", "campaign")))
    return f"banner-production__{client}__{campaign}__{timestamp}"


def write_banner_spec(path: Path, run_id: str, created_at: str, inputs: dict[str, Any]) -> None:
    ordered_keys = [
        "client_name",
        "campaign_name",
        "project_name",
        "service_target",
        "campaign_objective",
        "regulated_category",
        "adult_only",
        "banner_final_size",
        "generation_size",
        "iteration",
        "orientation_file",
        "reference_banners",
        "background_assets",
        "logos",
        "brand_guidelines",
        "past_creatives",
        "required_assets_policy",
        "compliance_notes",
        "banned_expressions",
        "notes",
    ]
    lines = [
        f"run_id: {quote_yaml(run_id)}",
        f"created_at: {quote_yaml(created_at)}",
        'workflow: "2-1-banner-concept"',
    ]
    for key in ordered_keys:
        if key not in inputs:
            continue
        value = inputs[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            if value:
                lines.extend(f"  - {quote_yaml(item)}" for item in value)
        else:
            lines.append(f"{key}: {quote_yaml(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_concepts(inputs: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    campaign_name = str(inputs.get("campaign_name", "キャンペーン"))
    client_name = str(inputs.get("client_name", "クライアント"))
    objective = str(inputs.get("campaign_objective", "キャンペーン目的"))
    service_target = str(inputs.get("service_target", "ターゲット"))
    final_size = str(inputs.get("banner_final_size", "600x500"))
    generation_size = str(inputs.get("generation_size", "1200x1008"))
    delivery_size = str(inputs.get("delivery_size", generation_size))
    regulated_category = str(inputs.get("regulated_category", "none")).lower()
    adult_only = bool(inputs.get("adult_only", False))
    regulated_constraints: list[str] = []
    if regulated_category in {"tobacco", "heated tobacco", "nicotine"} or adult_only:
        regulated_constraints = [
            "成人向け前提。若年層訴求、未成年、学校、家族利用を示唆しない。",
            "健康、安全、禁煙、医療、リスク低減に関する訴求をしない。",
            "価格、割引、販売場所、発売日、ランキング、法務表記を勝手に作らない。",
        ]

    concepts: list[dict[str, Any]] = []
    for index, (title, intent, response) in enumerate(CONCEPT_VARIANTS, start=1):
        copy_stub = f"{campaign_name}の魅力を伝える"
        sub_copy_stub = "今知りたいポイントを明確に"
        visual = (
            "提供された背景/商品/素材画像とロゴを主要なビジュアル要素として使う。"
            "無関係な写真素材を勝手に作らない。"
        )
        layout = (
            "メインコピーは最も読みやすい領域に配置し、ロゴは明確に見せる。"
            f"CTA領域を確保し、媒体上の想定比率 {final_size} でも成立する余白を残す。"
        )
        regulated_note = (
            " 対象は成人のみ。表現は上質で抑制的にし、健康/安全訴求や若年層向けの記号を避ける。"
            if regulated_constraints
            else ""
        )
        prompt = (
            f"{client_name} / {campaign_name} の日本語Webバナー案を作成する。"
            f"生成サイズと納品マスターサイズは {delivery_size}。媒体上の想定表示サイズは {final_size}。"
            f"案の方向性: {title}。目的: {objective}。ターゲット: {service_target}。"
            f"メインコピー: {copy_stub}。サブコピー: {sub_copy_stub}。"
            f"{visual} {layout}{regulated_note} API返却画像をリサイズせず納品しても文字が読みやすいこと。"
        )
        if dry_run:
            prompt += " これはdry-run用の仮プロンプト。実調査と素材分析後に置き換える。"

        concepts.append(
            {
                "concept_id": f"concept_{index}",
                "title": title,
                "strategic_intent": intent,
                "target_response": response,
                "main_copy": copy_stub,
                "sub_copy": sub_copy_stub,
                "other_copy": "",
                "visual_direction": visual,
                "layout_instruction": layout,
                "asset_usage": "提供素材とロゴを使用。無関係な写真素材は生成しない。",
                "logo_usage": "ガイドラインで許可されない限り、提供ロゴを変形・改色せず明瞭に使う。",
                "tone_and_manner": "ブランド調査とオリエン分析後にトーンを確定する。",
                "generation_prompt": prompt,
                "negative_constraints": [
                    "根拠のない主張、ランキング、価格、キャンペーン日程、法務表記を追加しない。",
                    "未提供の人物、商品、ブランド資産の写真素材を使わない。",
                    "読めない小さな日本語テキストを作らない。",
                ]
                + regulated_constraints,
            }
        )
    return concepts


def build_gpt_image_prompt(inputs: dict[str, Any], concepts: list[dict[str, Any]]) -> dict[str, Any]:
    generation_size = str(inputs.get("generation_size", "1200x1008"))
    design_target_size = str(inputs.get("banner_final_size", "600x500"))
    delivery_size = str(inputs.get("delivery_size", generation_size))
    return {
        "model": "gpt-image-2",
        "quality": str(inputs.get("image_quality", "medium")),
        "generation_size": generation_size,
        "delivery_size": delivery_size,
        "design_target_size": design_target_size,
        "preserve_api_output_resolution": True,
        "resize_to_final_size": False,
        "output_format": "png",
        "notes": [
            "OPENAI_API_KEYは環境変数、またはユーザー設定ファイルから読む。",
            "GPT Image 2から返却された画像を、同じ解像度の納品マスターとして保存する。",
            "600x500などの媒体指定サイズはレイアウト比率の参照値として扱い、明示指示がある場合だけ別名でリサイズ版を作る。",
            "生成後、すべての文字と訴求内容を人間/Codex QAで確認する。",
        ],
        "prompts": [
            {
                "concept_id": concept["concept_id"],
                "title": concept["title"],
                "prompt": concept["generation_prompt"],
                "negative_constraints": concept["negative_constraints"],
            }
            for concept in concepts
        ],
    }


def write_qa_report(path: Path, dry_run: bool) -> None:
    status = "dry-run開始チェックリスト" if dry_run else "開始チェックリスト"
    path.write_text(
        "\n".join(
            [
                "# Codex QAレポート",
                "",
                f"状態: {status}",
                "",
                "## 必須チェック",
                "",
                "- 基本仕様チェック: 未評価",
                "- ブランドガイドラインチェック: 未評価",
                "- ハルシネーションチェック: 未評価",
                "- 規制カテゴリチェック: 該当時は未評価",
                "- 過去CR類似性チェック: 未評価",
                "",
                "## 通過基準",
                "",
                "- 基本仕様とハルシネーションチェックは納品前に100% OKにする。",
                "- 年齢制限商材では規制カテゴリチェックを100% OKにする。",
                "- ブランドガイドラインと過去CR類似性は、実質的に問題がなければ通過可。",
                "",
                "## 要修正",
                "",
                "- dry-run案を、実調査と提供ファイルに基づく案へ置き換える。",
                "- 生成された文字とビジュアル上の訴求をオリエン資料と照合する。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"{output_dir} is not empty. Use --overwrite to write into it.")
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = parse_simple_yaml(input_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or build_default_run_id(inputs, timestamp)
    created_at = datetime.now(timezone.utc).isoformat()
    project_name = str(inputs.get("project_name") or f"{inputs.get('client_name', '')} - {inputs.get('campaign_name', '')}").strip(" -")
    init_phase_timings(output_dir, run_id)
    brand_cache = build_cache(input_path, output_dir, default_cache_root())

    concepts = build_concepts(inputs, args.dry_run)
    gpt_image_prompt = build_gpt_image_prompt(inputs, concepts)

    banner_spec_path = output_dir / "banner_spec.yaml"
    concepts_path = output_dir / "banner_concepts.json"
    image_prompt_path = output_dir / "gpt_image_prompt.json"
    qa_report_path = output_dir / "qa_report.md"
    run_summary_path = output_dir / "run_summary.json"

    write_banner_spec(banner_spec_path, run_id, created_at, inputs)
    concepts_path.write_text(json.dumps(concepts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    image_prompt_path.write_text(json.dumps(gpt_image_prompt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_qa_report(qa_report_path, args.dry_run)

    run_summary = {
        "run_id": run_id,
        "project_name": project_name,
        "created_at": created_at,
        "status": "draft",
        "workflow": "2-1-banner-concept",
        "inputs": inputs,
        "outputs": {
            "banner_spec": str(banner_spec_path),
            "banner_concepts": str(concepts_path),
            "gpt_image_prompt": str(image_prompt_path),
            "qa_report": str(qa_report_path),
            "generated_images": [],
            "canvas_outputs": "",
            "phase_timings": str(output_dir / "phase_timings.json"),
            "brand_asset_cache": str(output_dir / "brand_asset_cache.json"),
        },
        "sharepoint": {
            "folder_name_template": "banner-production__<client_name>__<campaign_name>__<YYYYMMDDTHHMMSSZ>",
            "artifact_folder_name": run_id,
        },
        "brand_asset_cache": {
            "file": "brand_asset_cache.json",
            "cache_root": brand_cache.get("cache_root", ""),
            "entries": len(brand_cache.get("entries", [])),
        },
        "qa": {
            "score": 0,
            "summary": "ドラフト実行フォルダを作成。QAは未実行。",
            "must_fix": [
                "dry-run内容を、調査と提供ファイルに基づく案へ置き換える。",
                "納品前にバナー画像を生成し、QAを実行する。",
            ],
            "improvement_points": [],
        },
    }
    run_summary_path.write_text(json.dumps(run_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_phase_event(
        output_dir,
        "phase_1",
        "prepare_run",
        started_at=started_at,
        extra={"run_id": run_id, "image_quality": gpt_image_prompt.get("quality", "medium")},
    )

    print(f"実行フォルダを作成しました: {output_dir}")
    print(f"Run ID: {run_id}")
    print("成果物: run_summary.json, banner_spec.yaml, banner_concepts.json, gpt_image_prompt.json, qa_report.md, phase_timings.json, brand_asset_cache.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
