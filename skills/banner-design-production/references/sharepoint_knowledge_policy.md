# Power Automate / SharePoint知見保存ルール

SharePoint保存と検索には、既存のPower Automateワークフローテンプレートを使う。

- 設定ファイル: 実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env`
- 保存スクリプト: Skill側の `scripts/send_sharepoint_flow1.py` を標準にする。
- SharePoint List: `CreativeProductionRuns`
- Document Library / folder root: `CreativePoC`

## 保存payload

Power Automate Flow 1仕様に固定する。

```json
{
  "run_id": "",
  "project_name": "",
  "created_at": "",
  "status": "success",
  "qa_score": 0,
  "qa_summary": "",
  "artifacts": []
}
```

artifactは必ず `file_name` を使う。テキスト成果物は `content`、画像/バイナリ成果物は `content_base64` を使う。

## SharePointフォルダ名テンプレート

Flow 1が `run_id` を成果物フォルダ名に使う前提で、このSkillの標準run IDは以下にする。

```text
banner-design-production__<client_name>__<campaign_name>__<YYYYMMDDTHHMMSSZ>
```

## 保存対象ファイル

存在する場合に保存する。

- `run_summary.json`
- `design_spec.yaml`
- `design_brief.json`
- `fixed_elements_analysis.md`
- `gpt_image_prompt.json`
- `qa_report.md`
- `phase_timings.json`
- `brand_asset_cache.json`
- `image_generation_batch_report.json`
- `generated_image_*.png`
- `generated_image_*.png.metadata.json`
- `human_feedback.md`

## 自動保存タイミング

- Phase 1完了時: デザイン生成方針、画像生成プロンプト、デザイン画像、Codex QA結果、生成デザインの良し悪し。
- Phase 2入力時: ユーザーの目視チェック結果、承認可否、デザイン画像フィードバック、修正指示。

Phase 2保存は、Excel Step 10「デザインチェック(目視)・承認」でユーザーからフィードバックを受け取った後にだけ実行する。Phase 1から自動でStep 11へ進めない。

PPT生成、メール作成、メール送信、クライアント承認結果の受領は今回のScope外のため、保存対象にしない。

## 秘密情報ルール

- Power Automate URLと共有secretは実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env` からだけ読む。
- `.env` の値は表示しない。
- Flow URL、共有secret、OpenAI APIキーを成果物本文に含めない。

## 実行

payload作成:

```bash
python3 ~/.codex/skills/banner-design-production/scripts/build_sharepoint_payload.py \
  --run-dir <run_dir> \
  --output <run_dir>/sharepoint_save_payload.json
```

POST実行:

```bash
python3 ~/.codex/skills/banner-design-production/scripts/send_sharepoint_flow1.py \
  <run_dir>/sharepoint_save_payload.json
```
