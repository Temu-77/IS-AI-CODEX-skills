#!/usr/bin/env python3
"""安全なデザイン作成runフォルダを準備する。

このヘルパーは外部APIを呼ばない。2-1の採用案・フィードバックを正規化し、
後続ステップで画像生成/編集、QA、SharePoint保存payloadを埋められるように
主要成果物を作成する。
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


def coerce_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
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


def quote_yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def sanitize_run_id_part(value: Any) -> str:
    text = str(value or "unknown").strip()
    text = re.sub(r'[\\/:*?"<>|#%&{}~]+', "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-_. ")
    return text[:64] or "unknown"


def build_default_run_id(inputs: dict[str, Any], timestamp: str) -> str:
    client = sanitize_run_id_part(inputs.get("client_name", "client"))
    campaign = sanitize_run_id_part(inputs.get("campaign_name", inputs.get("project_name", "campaign")))
    return f"banner-design-production__{client}__{campaign}__{timestamp}"


def load_text_or_inline(inputs: dict[str, Any], text_key: str, file_key: str) -> str:
    inline_value = str(inputs.get(text_key, "") or "").strip()
    if inline_value:
        return inline_value

    file_value = str(inputs.get(file_key, "") or "").strip()
    if file_value:
        path = Path(file_value).expanduser()
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            marker = "## フィードバック本文"
            if marker in text:
                text = text.split(marker, 1)[1].strip()
            return text
    return ""


def write_design_spec(path: Path, run_id: str, created_at: str, inputs: dict[str, Any]) -> None:
    ordered_keys = [
        "client_name",
        "campaign_name",
        "project_name",
        "source_banner_run_dir",
        "adopted_concepts",
        "banner_feedback",
        "banner_feedback_file",
        "source_banner_images",
        "logos",
        "replacement_assets",
        "brand_guidelines",
        "past_creatives",
        "service_target",
        "campaign_objective",
        "regulated_category",
        "adult_only",
        "banner_final_size",
        "generation_size",
        "delivery_size",
        "image_quality",
        "iteration",
        "fixed_elements_policy",
        "required_assets_policy",
        "compliance_notes",
        "banned_expressions",
        "notes",
    ]
    lines = [
        f"run_id: {quote_yaml(run_id)}",
        f"created_at: {quote_yaml(created_at)}",
        'workflow: "2-2-banner-design-production"',
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


def build_design_brief(inputs: dict[str, Any], feedback: str, dry_run: bool) -> dict[str, Any]:
    adopted = normalize_list(inputs.get("adopted_concepts")) or ["design_1"]
    return {
        "workflow": "2-2-banner-design-production",
        "client_name": str(inputs.get("client_name", "")),
        "campaign_name": str(inputs.get("campaign_name", "")),
        "project_name": str(inputs.get("project_name", "")),
        "source_banner_run_dir": str(inputs.get("source_banner_run_dir", "")),
        "adopted_concepts": adopted,
        "banner_feedback": feedback,
        "source_banner_images": normalize_list(inputs.get("source_banner_images")),
        "logos": normalize_list(inputs.get("logos")),
        "replacement_assets": normalize_list(inputs.get("replacement_assets")),
        "fixed_elements_policy": str(inputs.get("fixed_elements_policy", "")),
        "required_assets_policy": str(inputs.get("required_assets_policy", "")),
        "qa_focus": [
            "サイズ/解像度など基本仕様",
            "ブランドガイドライン",
            "ハルシネーション",
            "過去CRとの類似性",
            "規制カテゴリ該当時の表現",
        ],
        "scope_excluded": [
            "デザイン確認用PPT生成",
            "確認依頼メール/メッセージ作成と送信",
            "クライアント側承認結果のメール受領処理",
        ],
        "dry_run": dry_run,
    }


def build_gpt_image_prompt(inputs: dict[str, Any], feedback: str, dry_run: bool) -> dict[str, Any]:
    adopted = normalize_list(inputs.get("adopted_concepts")) or ["design_1"]
    generation_size = str(inputs.get("generation_size", "1200x1008"))
    delivery_size = str(inputs.get("delivery_size", generation_size))
    design_target_size = str(inputs.get("banner_final_size", "600x500"))
    client_name = str(inputs.get("client_name", "クライアント"))
    campaign_name = str(inputs.get("campaign_name", "キャンペーン"))
    objective = str(inputs.get("campaign_objective", "キャンペーン目的"))
    target = str(inputs.get("service_target", "ターゲット"))
    fixed_policy = str(inputs.get("fixed_elements_policy", "コピー、ロゴ、レイアウト、CTA、トーン&マナーを不用意に変えない。"))
    asset_policy = str(inputs.get("required_assets_policy", "提供素材とロゴを使う。"))
    regulated_category = str(inputs.get("regulated_category", "none")).lower()
    adult_only = bool(inputs.get("adult_only", False))
    regulated_note = ""
    if regulated_category in {"tobacco", "heated tobacco", "nicotine"} or adult_only:
        regulated_note = "対象は成人のみ。若年層訴求、健康/安全/禁煙/リスク低減訴求、未確認の価格/販売条件を避ける。"

    prompts = []
    for index, adopted_id in enumerate(adopted, start=1):
        concept_id = adopted_id if adopted_id.startswith("design_") else f"design_{index}_{adopted_id}"
        prompt = (
            f"{client_name} / {campaign_name} の採用バナー案を、本番寄りの日本語Web広告デザイン画像として仕上げる。"
            f"採用案ID: {adopted_id}。目的: {objective}。ターゲット: {target}。"
            f"ユーザーフィードバック: {feedback or '未指定'}。"
            f"固定要素方針: {fixed_policy}。素材方針: {asset_policy}。"
            f"生成サイズと納品マスターサイズは {delivery_size}。媒体上の想定表示サイズは {design_target_size}。"
            "Node②の素材置換プロンプトに従い、元バナー内の画像領域を認識し、必要な場合だけ提供素材へ差し替える。"
            "画像を差し替える以外は、極力元バナーのデザインレイアウトや要素の一切を変更しない。"
            "固定要素として、画像要素以外のオブジェクト要素、メインコピー、サブコピー、その他コピー要素、ロゴ、レイアウト、トーン&マナー、カラー、CTA周りを維持する。"
            "画像素材以外のベクターオブジェクト的な内容はそのまま活用し、手を入れない。"
            "代表的なオブジェクト要素は元バナーからデザイン的な調整をかけず、可能な限りそのまま画像で再現する。"
            "指定された素材は可能な限り正確に描写し、素材側をトリミングする場合も全体のバナーサイズは変えない。"
            "ただし文字の可読性が悪い場合だけ調整し、文字の大きさは12ポイント以上を目安にする。"
            "ロゴと商品/素材は歪ませず、根拠のない訴求や未提供素材を追加しない。"
            f"{regulated_note}"
        )
        if dry_run:
            prompt += " これはdry-run用の仮プロンプト。実素材と採用案確認後に置き換える。"
        prompts.append(
            {
                "concept_id": concept_id,
                "title": f"デザイン仕上げ: {adopted_id}",
                "prompt": prompt,
                "negative_constraints": [
                    "採用案のコピー、ロゴ、CTA、主要レイアウトを勝手に変えない。",
                    "未提供の人物、商品、ブランド資産の写真素材を使わない。",
                    "読めない小さな日本語テキストを作らない。",
                    "根拠のない価格、ランキング、効果保証、販売条件を追加しない。",
                ],
            }
        )

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
            "PPT生成とメール送付は今回のScope外。",
        ],
        "prompts": prompts,
    }


def write_fixed_elements_analysis(path: Path, inputs: dict[str, Any], feedback: str) -> None:
    source_images = normalize_list(inputs.get("source_banner_images"))
    replacement_assets = normalize_list(inputs.get("replacement_assets"))
    logos = normalize_list(inputs.get("logos"))
    path.write_text(
        "\n".join(
            [
                "# 素材差し替え領域・固定要素の特定結果",
                "",
                "このファイルはExcelの `2-2. デザイン作成` Step 3、およびNode②-#1/#3の分析結果を残すためのもの。",
                "初期生成時点では入力情報に基づくチェックリストとして作成し、Codex画像分析後に具体内容へ更新する。",
                "",
                "## 入力",
                "",
                f"- 採用案画像: {', '.join(source_images) if source_images else '未指定'}",
                f"- 差し替え素材: {', '.join(replacement_assets) if replacement_assets else '未指定'}",
                f"- ロゴ: {', '.join(logos) if logos else '未指定'}",
                f"- フィードバック要約: {feedback or '未指定'}",
                "",
                "## 最低限確認する分析項目",
                "",
                "- 画像要素: 未分析",
                "- 代表的なオブジェクト要素: 未分析",
                "- その他画像要素以外のオブジェクト要素: 未分析",
                "- メインコピー: 採用案から不用意に変更しない",
                "- サブコピー: 採用案から不用意に変更しない",
                "- その他コピー要素: 採用案から不用意に変更しない",
                "- ロゴ: 変形、改色、差し替えを勝手に行わない",
                "- レイアウト: 採用案の主要構成を維持する",
                "- トーン&マナー: 採用案とブランドガイドラインに合わせる",
                "- カラー: 採用案とブランドガイドラインに合わせる",
                "- CTA周り: フィードバックに基づく視認性改善のみ許可",
                "",
                "## Node②固定条件",
                "",
                "- 画像を差し替える以外は、極力元バナーのデザインレイアウトや要素の一切を変更しない。",
                "- 画像領域を特定する際は、この分析結果を参考にする。",
                "- バナーサイズは指定サイズのままとし、素材側をトリミングするなどして合わせる。",
                "- 指定された素材は、可能な限り正確に描写する。",
                "- 画像素材以外のベクターオブジェクト的な内容はそのまま活用し、手を入れない。",
                "- 代表的なオブジェクト要素は、元バナーからデザイン的な調整をかけず、そのまま画像で再現する。",
                "- 文字の可読性が悪い場合だけ調整し、文字の大きさは12ポイント以上を目安にする。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_qa_report(path: Path, dry_run: bool) -> None:
    status = "dry-run開始チェックリスト" if dry_run else "開始チェックリスト"
    path.write_text(
        "\n".join(
            [
                "# デザイン画像 Codex QAレポート",
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
                "- dry-run内容を、採用案、フィードバック、提供ファイルに基づくデザインへ置き換える。",
                "- 生成された文字、ロゴ、商品/素材、CTAを採用案と照合する。",
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
    feedback = load_text_or_inline(inputs, "banner_feedback", "banner_feedback_file")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or build_default_run_id(inputs, timestamp)
    created_at = datetime.now(timezone.utc).isoformat()
    project_name = str(inputs.get("project_name") or f"{inputs.get('client_name', '')} - {inputs.get('campaign_name', '')}").strip(" -")

    init_phase_timings(output_dir, run_id)
    brand_cache = build_cache(input_path, output_dir, default_cache_root())

    design_spec_path = output_dir / "design_spec.yaml"
    design_brief_path = output_dir / "design_brief.json"
    fixed_elements_path = output_dir / "fixed_elements_analysis.md"
    image_prompt_path = output_dir / "gpt_image_prompt.json"
    qa_report_path = output_dir / "qa_report.md"
    run_summary_path = output_dir / "run_summary.json"

    design_brief = build_design_brief(inputs, feedback, args.dry_run)
    gpt_image_prompt = build_gpt_image_prompt(inputs, feedback, args.dry_run)
    write_design_spec(design_spec_path, run_id, created_at, inputs)
    design_brief_path.write_text(json.dumps(design_brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_fixed_elements_analysis(fixed_elements_path, inputs, feedback)
    image_prompt_path.write_text(json.dumps(gpt_image_prompt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_qa_report(qa_report_path, args.dry_run)

    run_summary = {
        "run_id": run_id,
        "project_name": project_name,
        "created_at": created_at,
        "status": "draft",
        "workflow": "2-2-banner-design-production",
        "inputs": inputs,
        "outputs": {
            "design_spec": str(design_spec_path),
            "design_brief": str(design_brief_path),
            "fixed_elements_analysis": str(fixed_elements_path),
            "gpt_image_prompt": str(image_prompt_path),
            "qa_report": str(qa_report_path),
            "generated_images": [],
            "phase_timings": str(output_dir / "phase_timings.json"),
            "brand_asset_cache": str(output_dir / "brand_asset_cache.json"),
        },
        "sharepoint": {
            "folder_name_template": "banner-design-production__<client_name>__<campaign_name>__<YYYYMMDDTHHMMSSZ>",
            "artifact_folder_name": run_id,
        },
        "brand_asset_cache": {
            "file": "brand_asset_cache.json",
            "cache_root": brand_cache.get("cache_root", ""),
            "entries": len(brand_cache.get("entries", [])),
        },
        "qa": {
            "score": 0,
            "summary": "ドラフト実行フォルダを作成。デザインQAは未実行。",
            "must_fix": [
                "dry-run内容を、採用案とフィードバックに基づくデザインへ置き換える。",
                "納品前にデザイン画像を生成し、QAを実行する。",
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
    print("成果物: run_summary.json, design_spec.yaml, design_brief.json, fixed_elements_analysis.md, gpt_image_prompt.json, qa_report.md, phase_timings.json, brand_asset_cache.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
