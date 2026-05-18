# Power Automate / SharePoint知見保存ルール

SharePoint保存と検索には、既存のPower Automateワークフローテンプレートを使う。

- 設定ファイル: 実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env`
- 設定テンプレート: `power_automate_config.template.json`
- 保存スクリプト: Skill側の `scripts/send_sharepoint_flow1.py` を標準にする。Power Automateテンプレート側の `scripts/send_flow1_save_run.py` は低レベル送信用で、Skillから直接呼ばない。
- 検索スクリプト: `scripts/send_flow2_search.py`

## SharePoint構成

最小PoC構成は以下。

- SharePoint List: `CreativeProductionRuns`
- Document Library / folder root: `CreativePoC`

List列:

- `Title`: run ID
- `ProjectName`: プロジェクト/キャンペーン/ブランド名
- `CreatedAt`: 実行日時
- `Status`: `success`, `failed`, `draft`
- `QAScore`: Codex QAスコア、0-100
- `ArtifactFolderUrl`: Flowが返す成果物フォルダURL
- `QASummary`: QA要約

詳細ファイルはList列に展開せず、artifactとして保存する。

## 保存payload

保存payloadは以下の形にする。

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

artifactはFlow 1仕様に固定し、ファイル名キーは `name` ではなく必ず `file_name` を使う。テキスト成果物は `content`、画像/バイナリ成果物は `content_base64` を使う。

## SharePointフォルダ名テンプレート

Flow 1が `run_id` を成果物フォルダ名に使う前提で、Skillの標準run IDは以下にする。

```text
banner-production__<client_name>__<campaign_name>__<YYYYMMDDTHHMMSSZ>
```

例:

```text
banner-production__JT__Ploom-CUBE-banner-proposal__20260515T031500Z
```

これにより、SharePoint上で「バナー制作であること」「クライアント/案件」「生成日時」がフォルダ名から分かる。ユーザーが明示的に `--run-id` を指定した場合は、そのrun IDを優先する。

## 保存対象ファイル

存在する場合に保存する。

- `run_summary.json`
- `banner_spec.yaml`
- `banner_concepts.json`
- `gpt_image_prompt.json`
- `qa_report.md`
- `phase_timings.json`
- `brand_asset_cache.json`
- `image_generation_batch_report.json`
- `generated_image_*.png`
- `generated_image_*.png.metadata.json`
- `canvas_outputs.json`
- `human_feedback.md`

## 自動保存タイミング

このSkillでは、以下をSharePoint知見保存対象とする。

- Phase 1完了時: 生成バナー案、画像生成プロンプト、生成画像、Codex QA結果、生成バナー案の良し悪し。
- Phase 2入力時: ユーザーの目視チェック結果、承認可否、バナー案画像フィードバック、修正指示。
- Phase 3実行時: Canvas受容性評価結果、評価スコア、評価理由、改善アドバイス、配信可否判定。配信可否判定は `canvas_acceptance_eval.v1` の正規化後の値を保存し、ユーザー表示は `配信可`、`修正後配信可`、`配信不可` に固定する。

Phase 1は、Power Automate `.env` がある場合、ユーザーへの追加確認なしでPOSTまで実行する。Phase 2は、ユーザーがフィードバックを入力した時点で保存対象とみなし、POSTまで実行する。Phase 3は、ユーザーが受容性評価を明示的に指示した後に実行し、結果保存する。

## 秘密情報ルール

- Power Automate URLと共有secretは実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env` からだけ読む。
- `.env` の値は表示しない。
- Flow URL、共有secret、OpenAI APIキー、Canvas APIキーを成果物本文に含めない。
- HTTP request headerの生値を保存しない。

## 実行

payload作成:

```bash
python3 ~/.codex/skills/banner-proposal/scripts/build_sharepoint_payload.py \
  --run-dir <run_dir> \
  --output <run_dir>/sharepoint_save_payload.json
```

POST実行:

```bash
python3 ~/.codex/skills/banner-proposal/scripts/send_sharepoint_flow1.py \
  <run_dir>/sharepoint_save_payload.json
```

`send_sharepoint_flow1.py` は `certifi` のCA bundleを明示してTLS検証する。ローカルPython 3.14の証明書ストアが未設定でも、`/usr/bin/python3` への手動切替なしでPOSTできるようにするため、Skill実行時は必ずこのラッパーを使う。

POSTは、Phase 1のQA完了後、Phase 2のフィードバック受領後、Phase 3のCanvas結果作成後に実行する。`.env` がない場合は、payload作成までを成功とし、POST未実行として `qa_report.md`、`human_feedback.md`、`run_summary.json` のいずれかに記録する。

Phase 2のフィードバック保存:

```bash
python3 ~/.codex/skills/banner-proposal/scripts/record_human_feedback.py \
  --run-dir <run_dir> \
  --approval-status approved \
  --selected-concept concept_1 \
  --feedback "<ユーザーのフィードバック>"
```

`human_feedback.md` は、フィードバックごとに `feedback-YYYYMMDDTHHMMSSZ`、受領日時(UTC)、受領日時(ローカル)、Run ID、案件名、承認ステータス、対象案を含める。複数回のフィードバックは `--append` で追記し、SharePoint保存時に履歴として残す。

## 動作確認

`scripts/check_external_integrations.py` で、テンプレートフォルダ、送信スクリプト、`.env` の有無を確認する。`.env` がない状態では「SharePoint payload作成可 / POST不可」が正しい状態。
