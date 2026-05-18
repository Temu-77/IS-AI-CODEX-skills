#!/usr/bin/env python3
"""Prepare or execute Canvas acceptance evaluation for a banner concept run."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from phase_timing_utils import record_phase_event, utc_now_iso
except ImportError:  # pragma: no cover - fallback for direct copies of this script.
    record_phase_event = None

    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


DEFAULT_CANVAS_CLI = Path(
    "/Users/powerly/Desktop/IoC/CANVAS/creative-production-workflow-integration/creative_production_chat.py"
)
DEFAULT_CANVAS_CSV = Path("/Users/powerly/Desktop/IoC/CANVAS/Canvas-APIKEY_for-CreativeProductionWorkflow.csv")
DEFAULT_CANVAS_PYTHON = Path("/usr/bin/python3")

CANVAS_OUTPUT_SCHEMA_VERSION = "canvas_acceptance_eval.v1"
PROMPT_MODE = "sanitized_json_v1_no_paths_or_urls"
DELIVERY_LABELS = {
    "deliver": "配信可",
    "revise": "修正後配信可",
    "reject": "配信不可",
}
SUMMARY_COLUMNS = ["バナー案", "AIペルソナ評価スコア", "配信可否判定", "評価理由", "改善アドバイス"]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(OPENAI_API_KEY\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(PA_WORKFLOW_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(FIREFLY_CLIENT_SECRET\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(access[_-]?token\s*[:=]\s*)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(r"(sig=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"(code=)[^\s\"'&]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]
LOCAL_PATH_OR_URL_RE = re.compile(
    r"(https?://[^\s\"'<>]+|file://[^\s\"'<>]+|/(?:Users|Volumes|private|tmp|var|opt|Applications|System|Library)/[^\s\"'<>]*)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="banner_concepts.jsonとQA出力を含むrunフォルダ。")
    parser.add_argument("--agent-name", default="AIグルイン v1.0", help="使用するCanvasエージェント名。")
    parser.add_argument("--campaign-goal", help="キャンペーン目的の上書き。")
    parser.add_argument("--canvas-cli", default=str(DEFAULT_CANVAS_CLI), help="Canvas CLIパス。")
    parser.add_argument(
        "--python-bin",
        default=str(DEFAULT_CANVAS_PYTHON),
        help="Canvas CLI実行に使うPython。標準はmacOS system Pythonの/usr/bin/python3。",
    )
    parser.add_argument("--csv", default=str(DEFAULT_CANVAS_CSV), help="Canvas認証CSVパス。")
    parser.add_argument("--output", help="Canvas出力JSONパス。未指定時は<run-dir>/canvas_outputs.json。")
    parser.add_argument("--execute", action="store_true", help="Canvas CLIを実行する。未指定時はプロンプト作成のみ。")
    parser.add_argument(
        "--approved-concepts",
        help="評価対象concept ID。カンマ区切りで指定。例: concept_1,concept_2",
    )
    parser.add_argument(
        "--include-local-paths",
        action="store_true",
        help="デバッグ用。Canvas送信プロンプトへローカル画像パスを含める。通常は使わない。",
    )
    parser.add_argument("--max-qa-chars", type=int, default=400, help="Canvasへ渡すQA抜粋の最大文字数。")
    parser.add_argument(
        "--max-prompt-bytes",
        type=int,
        default=6500,
        help="CloudFront/WAFブロック回避のためのCanvas送信プロンプト最大byte数。",
    )
    parser.add_argument("--max-attempts", type=int, default=2, help="Canvas CLI実行の最大試行回数。")
    parser.add_argument("--timeout", type=int, default=240, help="Canvas CLI実行タイムアウト秒数。")
    return parser.parse_args()


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("("):
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def sanitize_canvas_prompt(text: str) -> tuple[str, int]:
    """Remove local paths and URLs from the prompt before it is sent to Canvas.

    CloudFront/WAF can block POST bodies that contain filesystem paths or URLs.
    Canvas CLI cannot upload local images, so absolute paths add risk without
    adding evaluable image data.
    """
    return LOCAL_PATH_OR_URL_RE.subn("[LOCAL_PATH_OR_URL_REMOVED]", text)


def has_local_path_or_url(text: str) -> bool:
    return bool(LOCAL_PATH_OR_URL_RE.search(text))


def clean_canvas_output(text: str) -> str:
    """Remove transport/status lines emitted by the existing Canvas CLI."""
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[start]") or stripped.startswith("[end]"):
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                if payload.get("type") in {"agent_switch", "keepalive"}:
                    continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip() + ("\n" if cleaned_lines else "")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def collapse_inline_text(value: Any) -> str:
    text = safe_text(value)
    text = re.sub(r"(?<=[A-Za-z0-9ぁ-んァ-ン一-龥])\s*[\r\n]+\s*(?=[A-Za-z0-9ぁ-んァ-ン一-龥])", "", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def strip_quotes(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1].strip()
    return value


def load_concepts(run_dir: Path) -> list[dict[str, Any]]:
    raw = load_json(run_dir / "banner_concepts.json")
    if isinstance(raw, dict):
        candidates = raw.get("concepts") or raw.get("banner_concepts") or raw.get("evaluation") or []
    else:
        candidates = raw
    return [item for item in candidates if isinstance(item, dict)]


def get_campaign_goal(run_dir: Path, override: str | None) -> str:
    if override:
        return override
    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        return "キャンペーン目的に対する受容性評価"
    summary = load_json(summary_path)
    return (
        summary.get("inputs", {}).get("campaign_objective")
        or summary.get("campaign_objective")
        or "キャンペーン目的に対する受容性評価"
    )


def concept_id_for(concept: dict[str, Any], index: int) -> str:
    return safe_text(concept.get("concept_id") or concept.get("banner_id") or f"concept_{index + 1}")


def parse_concept_ids(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def filter_concepts(concepts: list[dict[str, Any]], approved_ids: set[str]) -> list[dict[str, Any]]:
    if not approved_ids:
        return concepts
    filtered = [
        concept
        for index, concept in enumerate(concepts)
        if concept_id_for(concept, index) in approved_ids
    ]
    if not filtered:
        available = ", ".join(concept_id_for(concept, index) for index, concept in enumerate(concepts)) or "(なし)"
        raise SystemExit(
            f"--approved-concepts に一致する案がありません。指定値={', '.join(sorted(approved_ids))} / 利用可能={available}"
        )
    return filtered


def concept_id_from_image(path: Path) -> str:
    match = re.search(r"generated_image_(concept_\d+)", path.name)
    if match:
        return match.group(1)
    return path.stem.replace("generated_image_", "")


def load_image_metadata(path: Path) -> dict[str, Any]:
    metadata_path = Path(str(path) + ".metadata.json")
    if not metadata_path.exists():
        return {}
    try:
        metadata = load_json(metadata_path)
    except (OSError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def build_image_refs(run_dir: Path, approved_ids: set[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("generated_image_*.png")):
        concept_id = concept_id_from_image(path)
        if approved_ids and concept_id not in approved_ids:
            continue
        metadata = load_image_metadata(path)
        size = metadata.get("saved_image_size") or metadata.get("output_size") or metadata.get("size") or ""
        refs.append(
            {
                "asset_id": concept_id,
                "file_name": path.name,
                "size": safe_text(size),
                "local_path": str(path),
            }
        )
    return refs


def output_template() -> dict[str, Any]:
    return {
        "schema_version": CANVAS_OUTPUT_SCHEMA_VERSION,
        "machine_fields": {
            "delivery_recommendation": ["deliver", "revise", "reject"],
            "score_0_100": "integer 0-100",
        },
        "display_fields_ja": {
            "banner": "バナー案",
            "score_0_100": "AIペルソナ評価スコア",
            "delivery_judgement_jp": "配信可否判定",
            "reasons": "評価理由",
            "improvement_advice": "改善アドバイス",
        },
        "delivery_label_mapping": DELIVERY_LABELS,
        "summary_columns": SUMMARY_COLUMNS,
    }


def build_prompt(
    run_dir: Path,
    agent_name: str,
    campaign_goal: str | None,
    concepts: list[dict[str, Any]],
    approved_ids: set[str],
    *,
    include_local_paths: bool = False,
    max_qa_chars: int = 1800,
) -> tuple[str, dict[str, Any]]:
    summary_path = run_dir / "run_summary.json"
    qa_path = run_dir / "qa_report.md"

    summary = load_json(summary_path) if summary_path.exists() else {}
    qa_excerpt = qa_path.read_text(encoding="utf-8", errors="replace")[:max_qa_chars] if qa_path.exists() else ""
    image_refs = build_image_refs(run_dir, approved_ids)
    goal = campaign_goal or summary.get("inputs", {}).get("campaign_objective") or "キャンペーン目的に対する受容性評価"

    lines = [
        "以下のバナー案について、受容性評価だけを実施してください。",
        "返答はJSONのみとし、説明文、Markdown、コードフェンスは入れないでください。",
        "ローカルファイルパス、URL、秘密情報は評価に使わないでください。",
        "",
        f"評価エージェント: {agent_name}",
        f"案件名: {summary.get('project_name', '')}",
        f"キャンペーン目的: {goal}",
        "",
        "配信可否の値は必ず次の対応表に固定してください。",
        "- delivery_recommendation=deliver / delivery_judgement_jp=配信可",
        "- delivery_recommendation=revise / delivery_judgement_jp=修正後配信可",
        "- delivery_recommendation=reject / delivery_judgement_jp=配信不可",
        "",
        "評価対象画像:",
    ]
    if image_refs:
        for image_ref in image_refs:
            lines.extend(
                [
                    f"- asset_id: {image_ref['asset_id']}",
                    f"  file_name: {image_ref['file_name']}",
                    f"  image_status: 生成済み",
                ]
            )
            if image_ref.get("size"):
                lines.append(f"  size: {image_ref['size']}")
            if include_local_paths:
                lines.append(f"  local_path: {image_ref['local_path']}")
    else:
        lines.append("- 画像未生成。以下のコンセプト情報のみで暫定評価してください。")
    if not include_local_paths:
        lines.append("- 注記: Canvas APIには画像ファイル本体を添付できないため、画像のローカルパスは送信しません。")

    lines.extend(["", "バナー案:"])
    for index, concept in enumerate(concepts):
        lines.extend(
            [
                f"- banner_id: {concept_id_for(concept, index)}",
                f"  title: {concept.get('title', '')}",
                f"  main_copy: {concept.get('main_copy', '')}",
                f"  sub_copy: {concept.get('sub_copy', '')}",
                f"  strategic_intent: {concept.get('strategic_intent', '')}",
                f"  visual_direction: {concept.get('visual_direction', '')}",
                f"  layout_instruction: {concept.get('layout_instruction', '')}",
            ]
        )

    lines.extend(
        [
            "",
            "QA抜粋:",
            qa_excerpt,
            "",
            "必ず次のJSONテンプレートで返してください。キー名と値の表記を変更しないでください。",
            "{",
            '  "campaign_goal": "",',
            '  "evaluation": [',
            "    {",
            '      "banner_id": "concept_1",',
            '      "banner_title": "",',
            '      "score_0_100": 0,',
            '      "delivery_recommendation": "deliver",',
            '      "delivery_judgement_jp": "配信可",',
            '      "reasons": [""],',
            '      "anxieties": [""],',
            '      "improvement_advice": [""],',
            '      "copy_feedback": "",',
            '      "visual_feedback": ""',
            "    }",
            "  ]",
            "}",
            "",
            "score_0_100は0から100の整数にしてください。",
            "delivery_recommendationはdeliver、revise、rejectのいずれかだけにしてください。",
            "delivery_judgement_jpは配信可、修正後配信可、配信不可のいずれかだけにしてください。",
        ]
    )
    prompt = "\n".join(lines) + "\n"
    sanitized_prompt, stripped_count = sanitize_canvas_prompt(prompt)
    if not include_local_paths:
        prompt = sanitized_prompt
    prompt_meta = {
        "approved_concepts": sorted(approved_ids) if approved_ids else [
            concept_id_for(concept, index) for index, concept in enumerate(concepts)
        ],
        "image_refs": [
            {key: value for key, value in image_ref.items() if key != "local_path"}
            for image_ref in image_refs
        ],
        "include_local_paths": include_local_paths,
        "stripped_path_or_url_count": stripped_count if not include_local_paths else 0,
        "contains_path_or_url": has_local_path_or_url(prompt),
    }
    return prompt, prompt_meta


def extract_json_candidate(text: str) -> str:
    cleaned = clean_canvas_output(text).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        return cleaned[start : end + 1].strip()
    return ""


def escape_control_chars_inside_json_strings(text: str) -> str:
    repaired: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if escaped:
            repaired.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            repaired.append(char)
            escaped = True
            continue
        if char == '"':
            repaired.append(char)
            in_string = not in_string
            continue
        if in_string and char == "\n":
            repaired.append("\\n")
            continue
        if in_string and char == "\r":
            repaired.append("\\r")
            continue
        if in_string and char == "\t":
            repaired.append("\\t")
            continue
        repaired.append(char)
    return "".join(repaired)


def parse_yaml_like_response(text: str) -> dict[str, Any] | None:
    data: dict[str, Any] = {"evaluation": []}
    current: dict[str, Any] | None = None
    list_key: str | None = None
    key_map = {
        "banner_id": "banner_id",
        "banner_title": "banner_title",
        "title": "banner_title",
        "score_0_100": "score_0_100",
        "delivery_recommendation": "delivery_recommendation",
        "delivery_judgement_jp": "delivery_judgement_jp",
        "reasons": "reasons",
        "anxieties": "anxieties",
        "improvement_advice": "improvement_advice",
        "copy_feedback": "copy_feedback",
        "visual_feedback": "visual_feedback",
        "バナー案": "banner_title",
        "AIペルソナ評価スコア": "score_0_100",
        "配信可否判定": "delivery_judgement_jp",
        "評価理由": "reasons",
        "改善アドバイス": "improvement_advice",
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        if line.startswith("campaign_goal:"):
            data["campaign_goal"] = strip_quotes(line.split(":", 1)[1].strip())
            continue
        if line in {"evaluation:", "評価:"}:
            continue
        if line.startswith("- "):
            after_dash = line[2:].strip()
            if ":" in after_dash and (after_dash.split(":", 1)[0].strip() in key_map):
                if current:
                    data["evaluation"].append(current)
                current = {}
                list_key = None
                key, value = after_dash.split(":", 1)
                current[key_map[key.strip()]] = strip_quotes(value.strip())
                continue
            if current is not None and list_key:
                current.setdefault(list_key, []).append(strip_quotes(after_dash))
            continue
        if current is None:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key_map.get(key.strip())
        if not normalized_key:
            continue
        stripped_value = strip_quotes(value.strip())
        if normalized_key in {"reasons", "anxieties", "improvement_advice"} and not stripped_value:
            current.setdefault(normalized_key, [])
            list_key = normalized_key
        else:
            current[normalized_key] = stripped_value
            list_key = None
    if current:
        data["evaluation"].append(current)
    return data if data.get("evaluation") else None


def parse_canvas_response(text: str) -> tuple[dict[str, Any] | None, str]:
    candidate = extract_json_candidate(text)
    if candidate:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed, ""
        except json.JSONDecodeError as exc:
            try:
                parsed = json.loads(escape_control_chars_inside_json_strings(candidate))
                if isinstance(parsed, dict):
                    return parsed, f"json_repaired_control_chars: {exc}"
            except json.JSONDecodeError:
                pass
            yaml_fallback = parse_yaml_like_response(text)
            if yaml_fallback:
                return yaml_fallback, f"json_parse_failed_yaml_fallback: {exc}"
            return None, str(exc)
    yaml_fallback = parse_yaml_like_response(text)
    if yaml_fallback:
        return yaml_fallback, "json_not_found_yaml_fallback"
    return None, "JSONまたは評価テンプレートを検出できませんでした。"


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [collapse_inline_text(item) for item in value if collapse_inline_text(item)]
    text = safe_text(value)
    if not text:
        return []
    lines = [collapse_inline_text(re.sub(r"^[-・*]\s*", "", line.strip())) for line in text.splitlines() if line.strip()]
    return lines if len(lines) > 1 else [collapse_inline_text(text)]


def first_value(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def normalize_score(value: Any) -> int:
    if isinstance(value, (int, float)):
        return max(0, min(100, int(round(value))))
    text = safe_text(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0
    return max(0, min(100, int(round(float(match.group(0))))))


def normalize_delivery(value: Any, score: int) -> tuple[str, str]:
    text = safe_text(value)
    compact = re.sub(r"\s+", "", text.lower())
    if any(token in compact for token in ["reject", "配信不可", "不可", "ng", "不適"]):
        return "reject", DELIVERY_LABELS["reject"]
    if any(token in compact for token in ["revise", "修正後配信可", "要修正", "要改善", "修正", "改善"]):
        return "revise", DELIVERY_LABELS["revise"]
    if any(token in compact for token in ["deliver", "配信可", "可", "ok", "pass"]):
        return "deliver", DELIVERY_LABELS["deliver"]
    if score >= 80:
        return "deliver", DELIVERY_LABELS["deliver"]
    if score >= 60:
        return "revise", DELIVERY_LABELS["revise"]
    return "reject", DELIVERY_LABELS["reject"]


def normalize_canvas_payload(
    payload: dict[str, Any] | None,
    concepts: list[dict[str, Any]],
    fallback_goal: str,
) -> dict[str, Any]:
    concept_by_id = {concept_id_for(concept, index): concept for index, concept in enumerate(concepts)}
    goal = fallback_goal
    raw_items: Any = []
    if isinstance(payload, dict):
        goal = safe_text(payload.get("campaign_goal") or payload.get("キャンペーン目的") or fallback_goal)
        raw_items = (
            payload.get("evaluation")
            or payload.get("evaluations")
            or payload.get("results")
            or payload.get("受容性評価")
            or []
        )
    if not isinstance(raw_items, list):
        raw_items = []

    normalized: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        fallback_concept = concepts[index] if index < len(concepts) else {}
        fallback_id = concept_id_for(fallback_concept, index) if fallback_concept else f"concept_{index + 1}"
        banner_id = safe_text(
            first_value(raw_item, ["banner_id", "concept_id", "id", "案ID"]) or fallback_id
        )
        concept = concept_by_id.get(banner_id, fallback_concept)
        title = safe_text(
            first_value(raw_item, ["banner_title", "title", "バナー案", "案名"]) or concept.get("title") or banner_id
        )
        score = normalize_score(first_value(raw_item, ["score_0_100", "score", "AIペルソナ評価スコア"]))
        delivery_raw = first_value(
            raw_item,
            ["delivery_recommendation", "delivery_judgement_jp", "配信可否判定", "配信可否", "recommendation"],
        )
        delivery_recommendation, delivery_judgement_jp = normalize_delivery(delivery_raw, score)
        normalized.append(
            {
                "banner_id": banner_id,
                "banner_title": title,
                "score_0_100": score,
                "delivery_recommendation": delivery_recommendation,
                "delivery_judgement_jp": delivery_judgement_jp,
                "reasons": listify(first_value(raw_item, ["reasons", "reason", "評価理由"])),
                "anxieties": listify(first_value(raw_item, ["anxieties", "concerns", "不安", "懸念点"])),
                "improvement_advice": listify(
                    first_value(raw_item, ["improvement_advice", "advice", "改善アドバイス", "改善提案"])
                ),
                "copy_feedback": collapse_inline_text(first_value(raw_item, ["copy_feedback", "コピー評価", "copy"])),
                "visual_feedback": collapse_inline_text(first_value(raw_item, ["visual_feedback", "ビジュアル評価", "visual"])),
            }
        )
    return {"campaign_goal": goal, "evaluation": normalized}


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def summarize_list(items: list[str], limit: int = 2) -> str:
    if not items:
        return "-"
    return "<br>".join(markdown_cell(item) for item in items[:limit])


def build_user_summary_markdown(standardized: dict[str, Any], empty_note: str | None = None) -> str:
    lines = [
        "## Canvas受容性評価結果",
        "",
        f"キャンペーン目的: {markdown_cell(safe_text(standardized.get('campaign_goal')))}",
        "",
        "| バナー案 | AIペルソナ評価スコア | 配信可否判定 | 評価理由 | 改善アドバイス |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for item in standardized.get("evaluation", []):
        banner = f"{item.get('banner_id', '')} / {item.get('banner_title', '')}".strip(" /")
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(banner),
                    str(item.get("score_0_100", 0)),
                    markdown_cell(safe_text(item.get("delivery_judgement_jp"))),
                    summarize_list(item.get("reasons", [])),
                    summarize_list(item.get("improvement_advice", [])),
                ]
            )
            + " |"
        )
    if not standardized.get("evaluation"):
        note = empty_note or "Canvas返却の構造化に失敗しました。"
        lines.append(f"| - | - | - | {markdown_cell(note)} | `canvas_output_clean` を確認してください。 |")
    return "\n".join(lines) + "\n"


def detect_canvas_error(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    if returncode == 0:
        return {
            "error_type": "",
            "error_summary": "",
            "likely_cause": "",
            "retryable": False,
        }
    combined = f"{stdout}\n{stderr}"
    if "CloudFront" in combined or "HTTP 403" in combined or "403 ERROR" in combined:
        return {
            "error_type": "cloudfront_403",
            "error_summary": "Canvas API POSTがCloudFrontでブロックされました。",
            "likely_cause": (
                "Canvasアプリ到達前にCloudFront/WAFで拒否されています。"
                "過去の失敗ではCanvas送信プロンプトにローカル絶対パスが含まれていたことに加え、"
                "8KB前後の長いPOST本文、ローカルPython 3.14実行系でのCanvas CLI呼び出しでもCloudFront 403が再現しました。"
                "Skillはデフォルトでパス/URLを送らないサニタイズ済みプロンプトを使い、"
                "QA抜粋を短くして送信本文を6500 bytes以下に抑え、"
                "Canvas CLIはmacOS system Pythonの/usr/bin/python3で実行する設定に変更しています。"
                "それでも継続する場合はCanvas側のCloudFront/WAF許可設定またはAPI提供元への確認が必要です。"
            ),
            "retryable": True,
        }
    if "CERTIFICATE_VERIFY_FAILED" in combined or "certificate verify failed" in combined.lower():
        return {
            "error_type": "tls_certificate_verify_failed",
            "error_summary": "TLS証明書検証でCanvas API POSTに失敗しました。",
            "likely_cause": "実行Pythonの証明書ストアが未設定、またはCA bundleを参照できていません。",
            "retryable": True,
        }
    if "timed out" in combined.lower() or "timeout" in combined.lower():
        return {
            "error_type": "timeout",
            "error_summary": "Canvas API応答がタイムアウトしました。",
            "likely_cause": "Canvas側の処理待ち、ネットワーク遅延、または一時的な混雑の可能性があります。",
            "retryable": True,
        }
    return {
        "error_type": "canvas_cli_failed",
        "error_summary": "Canvas CLI実行に失敗しました。",
        "likely_cause": "canvas_outputs.json の error と attempts を確認してください。",
        "retryable": False,
    }


def run_canvas_command(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: int,
    max_attempts: int,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    completed: subprocess.CompletedProcess[str] | None = None
    error_info: dict[str, Any] = {}
    attempts_count = max(1, max_attempts)
    for attempt_number in range(1, attempts_count + 1):
        completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=timeout, env=env)
        raw_output = redact(completed.stdout)
        raw_error = redact(completed.stderr)
        error_info = detect_canvas_error(raw_output, raw_error, completed.returncode)
        attempts.append(
            {
                "attempt": attempt_number,
                "returncode": completed.returncode,
                "error_type": error_info.get("error_type", ""),
                "error_summary": error_info.get("error_summary", ""),
                "stderr_preview": raw_error[:1200],
            }
        )
        if completed.returncode == 0:
            break
        if not error_info.get("retryable") or attempt_number >= attempts_count:
            break
        time.sleep(min(2 * attempt_number, 5))
    if completed is None:  # pragma: no cover
        raise RuntimeError("Canvas command was not executed.")
    return completed, attempts, error_info


def update_run_summary(run_dir: Path, output_path: Path, result: dict[str, Any], prompt_mode: str) -> None:
    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        return
    summary = load_json(summary_path)
    summary.setdefault("outputs", {})["canvas_outputs"] = str(output_path)
    summary["canvas_acceptance_eval"] = {
        "status": result.get("status"),
        "schema_version": CANVAS_OUTPUT_SCHEMA_VERSION,
        "file": str(output_path),
        "prompt_mode": prompt_mode,
        "evaluation_count": len(result.get("evaluation", [])),
        "parse_status": result.get("parse_status"),
        "error_type": result.get("error_type", ""),
        "updated_at": utc_now_iso(),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    started_at = utc_now_iso()
    run_dir = Path(args.run_dir).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else run_dir / "canvas_outputs.json"
    prompt_mode = "debug_local_path_json_v1" if args.include_local_paths else PROMPT_MODE
    prompt_path = run_dir / ("canvas_acceptance_prompt.txt" if args.include_local_paths else "canvas_acceptance_prompt_sanitized.txt")
    if not run_dir.exists():
        raise FileNotFoundError(run_dir)
    if not (run_dir / "banner_concepts.json").exists():
        raise FileNotFoundError(run_dir / "banner_concepts.json")

    campaign_goal = get_campaign_goal(run_dir, args.campaign_goal)
    approved_ids = parse_concept_ids(args.approved_concepts)
    concepts = filter_concepts(load_concepts(run_dir), approved_ids)
    prompt, prompt_meta = build_prompt(
        run_dir,
        args.agent_name,
        args.campaign_goal,
        concepts,
        approved_ids,
        include_local_paths=args.include_local_paths,
        max_qa_chars=args.max_qa_chars,
    )
    if len(prompt.encode("utf-8")) > args.max_prompt_bytes and args.max_qa_chars > 0:
        prompt, prompt_meta = build_prompt(
            run_dir,
            args.agent_name,
            args.campaign_goal,
            concepts,
            approved_ids,
            include_local_paths=args.include_local_paths,
            max_qa_chars=0,
        )
        prompt_meta["qa_excerpt_omitted_due_to_prompt_bytes"] = True
    if not args.include_local_paths and has_local_path_or_url(prompt):
        prompt, stripped_count = sanitize_canvas_prompt(prompt)
        prompt_meta["stripped_path_or_url_count"] = prompt_meta.get("stripped_path_or_url_count", 0) + stripped_count
        prompt_meta["contains_path_or_url"] = has_local_path_or_url(prompt)
    prompt_meta["prompt_bytes"] = len(prompt.encode("utf-8"))
    prompt_meta["max_prompt_bytes"] = args.max_prompt_bytes
    prompt_meta["prompt_bytes_over_limit"] = prompt_meta["prompt_bytes"] > args.max_prompt_bytes
    prompt_too_large_error = ""
    if prompt_meta["prompt_bytes_over_limit"]:
        prompt_too_large_error = (
            f"Canvas送信プロンプトが大きすぎます: {prompt_meta['prompt_bytes']} bytes "
            f"(limit={args.max_prompt_bytes}). --max-qa-chars を下げるか、入力情報を要約してください。"
        )
    execute_allowed = args.execute and not prompt_too_large_error
    prompt_path.write_text(redact(prompt), encoding="utf-8")

    result: dict[str, Any] = {
        "schema_version": CANVAS_OUTPUT_SCHEMA_VERSION,
        "status": "prompt_too_large" if args.execute and prompt_too_large_error else "prompt_prepared",
        "executed": False,
        "agent_name": args.agent_name,
        "canvas_python": args.python_bin,
        "prompt_file": str(prompt_path),
        "prompt_mode": prompt_mode,
        "prompt_sanitization": prompt_meta,
        "canvas_output": "",
        "canvas_output_clean": "",
        "parse_status": "not_executed",
        "parse_error": "",
        "campaign_goal": campaign_goal,
        "evaluation": [],
        "parsed_evaluation": {"campaign_goal": campaign_goal, "evaluation": []},
        "user_summary_markdown": build_user_summary_markdown(
            {"campaign_goal": campaign_goal, "evaluation": []},
            empty_note=prompt_too_large_error
            or "Canvasは未実行です。ユーザー承認後に受容性評価を実行してください。",
        ),
        "output_template": output_template(),
        "attempts": [],
        "error_type": "prompt_too_large" if args.execute and prompt_too_large_error else "",
        "error_summary": prompt_too_large_error,
        "likely_cause": (
            "CloudFront/WAFのPOST本文検査に引っかかる可能性があるため、Canvas APIへ送信しませんでした。"
            if args.execute and prompt_too_large_error
            else ""
        ),
        "error": prompt_too_large_error,
        "created_at": utc_now_iso(),
    }

    if execute_allowed:
        canvas_cli = Path(args.canvas_cli).expanduser().resolve()
        csv_path = Path(args.csv).expanduser().resolve()
        python_bin_arg = Path(args.python_bin).expanduser()
        python_command = str(python_bin_arg.resolve()) if python_bin_arg.is_absolute() else args.python_bin
        use_system_python = False
        if python_bin_arg.is_absolute():
            if not python_bin_arg.exists():
                raise FileNotFoundError(python_bin_arg)
            try:
                use_system_python = python_bin_arg.resolve().samefile(DEFAULT_CANVAS_PYTHON)
            except OSError:
                use_system_python = False
        if not canvas_cli.exists():
            raise FileNotFoundError(canvas_cli)
        if not csv_path.exists():
            raise FileNotFoundError(csv_path)

        command = [
            python_command,
            str(canvas_cli),
            "--csv",
            str(csv_path),
            "--key-name",
            args.agent_name,
            "--yes",
            "--message-file",
            str(prompt_path),
        ]
        env = os.environ.copy()
        if use_system_python:
            env.pop("SSL_CERT_FILE", None)
            env.pop("REQUESTS_CA_BUNDLE", None)
        else:
            try:
                import certifi  # type: ignore

                env.setdefault("SSL_CERT_FILE", certifi.where())
                env.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
            except ImportError:
                pass

        completed, attempts, error_info = run_canvas_command(
            command,
            env=env,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
        )
        raw_output = redact(completed.stdout)
        raw_error = redact(completed.stderr)
        clean_output = redact(clean_canvas_output(completed.stdout))
        parsed_payload, parse_error = parse_canvas_response(clean_output)
        standardized = normalize_canvas_payload(parsed_payload, concepts, campaign_goal)
        empty_note = (
            error_info.get("error_summary")
            or "Canvas返却の構造化に失敗しました。"
        )
        result.update(
            {
                "status": "completed" if completed.returncode == 0 else "failed",
                "executed": True,
                "returncode": completed.returncode,
                "canvas_output": raw_output,
                "canvas_output_clean": clean_output,
                "parse_status": "parsed" if parsed_payload is not None else "failed",
                "parse_error": parse_error,
                "campaign_goal": standardized["campaign_goal"],
                "evaluation": standardized["evaluation"],
                "parsed_evaluation": standardized,
                "user_summary_markdown": build_user_summary_markdown(
                    standardized,
                    empty_note=None if standardized["evaluation"] else empty_note,
                ),
                "attempts": attempts,
                "error_type": error_info.get("error_type", ""),
                "error_summary": error_info.get("error_summary", ""),
                "likely_cause": error_info.get("likely_cause", ""),
                "retryable": error_info.get("retryable", False),
                "error": raw_error,
                "finalized_at": utc_now_iso(),
            }
        )

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_run_summary(run_dir, output_path, result, prompt_mode)
    if record_phase_event:
        record_phase_event(
            run_dir,
            phase="phase3",
            step="canvas_acceptance_eval",
            status=result.get("status", "completed"),
            started_at=started_at,
            extra={
                "executed": result.get("executed", False),
                "output": str(output_path),
                "schema_version": CANVAS_OUTPUT_SCHEMA_VERSION,
                "prompt_mode": prompt_mode,
                "parse_status": result.get("parse_status"),
                "error_type": result.get("error_type", ""),
            },
        )
    print(f"Canvas受容性評価ファイルを書き出しました: {output_path}")
    print(f"プロンプトファイル: {prompt_path}")
    if result.get("executed"):
        print("ユーザー向け要約:")
        print(result["user_summary_markdown"])
    elif result.get("status") == "prompt_too_large":
        print(result["error_summary"])
    else:
        print("Canvasは未実行です。ユーザー承認後に --execute 付きで再実行してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
