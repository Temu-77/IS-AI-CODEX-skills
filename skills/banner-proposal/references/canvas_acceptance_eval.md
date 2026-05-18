# Canvas受容性評価

このSkillでのCanvas利用は、バナー画像生成とユーザー目視チェック後、ユーザーが受容性評価の実行を明示した後の「受容性評価」に限定する。初回入力だけでCanvasまで自動実行しない。

## Canvas API設定

このSkillはCanvas CLIや認証CSVを呼ばず、Canvas外部エージェントAPIを直接呼ぶ。ユーザーは `.env` または環境変数に以下を設定する。

- `CANVAS_API_BASE_URL`: 既定は `https://mugen-ai-chat.jp`
- `CANVAS_API_KEY`: Canvas外部エージェントAPI key
- `CANVAS_COMPANY_ID`: API本文の `company_id`
- `CANVAS_AGENT_ID`: URL pathの対象エージェントID
- `CANVAS_EXTERNAL_USER_ID`: 既定は `creative-production-user-001`
- 任意: `CANVAS_CONVERSATION_ID`: 会話継続時だけ使う

Canvas API keyは、表示、引用、要約、保存しない。ユーザー向けにはエージェント名だけを出す。

## 推奨評価エージェント

本番テストレポートに基づき、受容性評価では以下を優先する。

- `AIグルイン v1.0`: 複数参加者風の反応、訴求軸比較、案ごとの受け止めを比較する。
- `AIデプスインタビュー v1.0`: 1人のペルソナ視点で、理由、不安、改善ヒントを深掘りする。
- `【デモAIペルソナ】50代女性損保契約者（CXAI用）` などのペルソナQA: 消費者/ペルソナ視点で案を評価する。

Skill 1では、ターゲット選定やコピー生成の上流工程にCanvasをデフォルト利用しない。それらは将来拡張扱い。

## 評価プロンプト形式

簡潔な日本語で送る。Canvas APIには画像ファイル本体を直接添付しないため、各バナーの説明、コンセプト項目、asset ID、ファイル名だけを渡す。ローカル絶対パス、URL、秘密情報はCanvas送信プロンプトに含めない。

過去の失敗では、送信プロンプトに `/Users/.../generated_image_*.png` のようなローカル絶対パスが含まれ、Canvasアプリ到達前にCloudFrontでHTTP 403としてブロックされた。さらに、約8KB以上の長いPOST本文でもCloudFront 403が再現した。したがって、標準プロンプトは `sanitized_json_v1_no_paths_or_urls` とし、QA抜粋は短くし、送信本文は標準で6500 bytes以下に抑える。ローカルパス入り送信は `--include-local-paths` を明示したデバッグ時だけ許可する。

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

内部では以下に相当するCanvas API呼び出しを行う。

```text
POST {CANVAS_API_BASE_URL}/api/v1/external/agent/{CANVAS_AGENT_ID}/chat
Accept: text/event-stream
Content-Type: application/json
X-API-Key: ${CANVAS_API_KEY}

{
  "company_id": "${CANVAS_COMPANY_ID}",
  "message": "<canvas_acceptance_prompt_sanitized.txt>",
  "external_user_id": "${CANVAS_EXTERNAL_USER_ID}",
  "conversation_id": "${CANVAS_CONVERSATION_ID}" // optional
}
```

Canvas APIはServer-Sent Eventsを返す。補助スクリプトは `delta.text` を連結して `canvas_output` / `canvas_output_clean` に保存し、`start` の `conversation_id` と `end` のtoken/point概要をcredentialなしで保存する。credentialらしい値は保存しない。

`canvas_outputs.json` の主要項目:

- `schema_version`: `canvas_acceptance_eval.v1`
- `prompt_mode`: `sanitized_json_v1_no_paths_or_urls`
- `prompt_sanitization`: 評価対象、画像参照、パス/URL除去数、残存チェック
- `evaluation`: 正規化済みの配列
- `parsed_evaluation`: 後方互換用の正規化済み評価オブジェクト
- `output_template`: 固定enum、表示名、列名の定義
- `user_summary_markdown`: ユーザーへ返す日本語まとめ
- `error_type`: 失敗時の分類。CloudFront 403は `cloudfront_403`
- `attempts`: Canvas API実行試行の概要

## 動作確認

`scripts/check_external_integrations.py` で、Canvas API用env設定の有無を確認する。実評価の疎通は `run_canvas_acceptance_eval.py --execute` で確認する。
