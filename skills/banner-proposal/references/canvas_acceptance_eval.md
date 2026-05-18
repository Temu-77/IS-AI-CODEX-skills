# Canvas受容性評価

このSkillでのCanvas利用は、バナー画像生成とユーザー目視チェック後、ユーザーが受容性評価の実行を明示した後の「受容性評価」に限定する。初回入力だけでCanvasまで自動実行しない。

## ローカル参照先

- Canvas連携フォルダ: `/Users/powerly/Desktop/IoC/CANVAS/creative-production-workflow-integration/`
- Canvas CLI: `/Users/powerly/Desktop/IoC/CANVAS/creative-production-workflow-integration/creative_production_chat.py`
- 既存ツールが期待する認証CSV: `Canvas-APIKEY_for-CreativeProductionWorkflow.csv`
- テストレポート: `/Users/powerly/Documents/Codex/2026-05-11/new-chat/canvas_all_agents_production_test_report.md`

CSV内のCanvas APIキーは、表示、引用、要約、保存しない。ユーザー向けにはエージェント名だけを出す。

## 推奨評価エージェント

本番テストレポートに基づき、受容性評価では以下を優先する。

- `AIグルイン v1.0`: 複数参加者風の反応、訴求軸比較、案ごとの受け止めを比較する。
- `AIデプスインタビュー v1.0`: 1人のペルソナ視点で、理由、不安、改善ヒントを深掘りする。
- `【デモAIペルソナ】50代女性損保契約者（CXAI用）` などのペルソナQA: 消費者/ペルソナ視点で案を評価する。

Skill 1では、ターゲット選定やコピー生成の上流工程にCanvasをデフォルト利用しない。それらは将来拡張扱い。

## 評価プロンプト形式

簡潔な日本語で送る。Canvas CLIは画像ファイルを直接送れないため、各バナーの説明、コンセプト項目、asset ID、ファイル名だけを渡す。ローカル絶対パス、URL、秘密情報はCanvas送信プロンプトに含めない。

過去の失敗では、送信プロンプトに `/Users/.../generated_image_*.png` のようなローカル絶対パスが含まれ、Canvasアプリ到達前にCloudFrontでHTTP 403としてブロックされた。さらに、ローカルPython 3.14でCanvas CLIを呼んだ場合、約8KB以上の長いPOST本文でもCloudFront 403が再現し、`/usr/bin/python3` かつ約5.4KBの短い本文では同じエージェントへのPOSTが成功した。したがって、標準プロンプトは `sanitized_json_v1_no_paths_or_urls` とし、`canvas_acceptance_prompt_sanitized.txt` を `/usr/bin/python3` から送信する。QA抜粋は短くし、送信本文は標準で6500 bytes以下に抑える。ローカルパス入り送信は `--include-local-paths` を明示したデバッグ時だけ許可する。

返却形式はJSONに固定する。Canvasには「JSONのみ、説明文、Markdown、コードフェンスなし」と指示する。

```json
{
  "campaign_goal": "",
  "evaluation": [
    {
      "banner_id": "concept_1",
      "banner_title": "",
      "score_0_100": 0,
      "delivery_recommendation": "deliver",
      "delivery_judgement_jp": "配信可",
      "reasons": [""],
      "anxieties": [""],
      "improvement_advice": [""],
      "copy_feedback": "",
      "visual_feedback": ""
    }
  ]
}
```

`delivery_recommendation` と `delivery_judgement_jp` は必ず以下の対応にする。

| delivery_recommendation | delivery_judgement_jp | ユーザー表示 |
| --- | --- | --- |
| `deliver` | `配信可` | 配信可 |
| `revise` | `修正後配信可` | 修正後配信可 |
| `reject` | `配信不可` | 配信不可 |

Canvas返却に表記ゆれがあっても、`run_canvas_acceptance_eval.py` は `canvas_outputs.json` に保存する前に `canvas_acceptance_eval.v1` として正規化する。ユーザー向けのまとめは `user_summary_markdown` を使い、列名は `バナー案`、`AIペルソナ評価スコア`、`配信可否判定`、`評価理由`、`改善アドバイス` に固定する。

## 実行ルール

Canvasは、ユーザーが受容性評価を依頼または承認した後だけ実行する。SkillのPhase 3として扱い、Phase 1のバナー案作成やPhase 2の目視フィードバック保存とは分ける。Skillの補助スクリプトを使う。

```bash
python3 ~/.codex/skills/banner-proposal/scripts/run_canvas_acceptance_eval.py \
  --run-dir <run_dir> \
  --agent-name "AIグルイン v1.0" \
  --approved-concepts concept_1,concept_2,concept_3,concept_4 \
  --execute
```

直接CLIを使う場合:

```bash
/usr/bin/python3 /Users/powerly/Desktop/IoC/CANVAS/creative-production-workflow-integration/creative_production_chat.py \
  --csv /Users/powerly/Desktop/IoC/CANVAS/Canvas-APIKEY_for-CreativeProductionWorkflow.csv \
  --key-name "<agent name>" \
  --yes \
  --message-file <canvas_acceptance_prompt_sanitized.txt>
```

結果は `canvas_outputs.json` に保存する。補助スクリプトは、CLIのkeepalive/status行を除去した `canvas_output_clean` も保存する。credentialらしい値は保存しない。

`canvas_outputs.json` の主要項目:

- `schema_version`: `canvas_acceptance_eval.v1`
- `prompt_mode`: `sanitized_json_v1_no_paths_or_urls`
- `prompt_sanitization`: 評価対象、画像参照、パス/URL除去数、残存チェック
- `evaluation`: 正規化済みの配列
- `parsed_evaluation`: 後方互換用の正規化済み評価オブジェクト
- `output_template`: 固定enum、表示名、列名の定義
- `user_summary_markdown`: ユーザーへ返す日本語まとめ
- `error_type`: 失敗時の分類。CloudFront 403は `cloudfront_403`
- `attempts`: Canvas CLI実行試行の概要

## 動作確認

`scripts/check_external_integrations.py` で、Canvas CLI、CSV、利用可能エージェント一覧の取得可否を確認する。実評価の疎通は `run_canvas_acceptance_eval.py --execute` で確認する。
