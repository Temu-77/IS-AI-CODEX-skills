---
name: banner-design-production
description: 2-2. デザイン作成フローを日本語で2段階ゲート実行する。banner-proposalの後続工程として、採用構成案・採用案リスト・バナー案フィードバックをもとに本番寄りのデザイン画像を生成し、素材差し替え、Codex QA、SharePoint知見保存で一度停止し、人間のデザイン目視承認後にフィードバックをSharePoint保存するときに使う。
---

# Banner Design Production

## 目的

このSkillは `2-2. デザイン作成` フローを日本語で実行するためのもの。`banner-proposal` で作成・承認された構成案、採用案リスト、バナー案フィードバックをもとに、より本番寄りのデザイン画像を作成し、素材差し替え、Codex QA、SharePoint知見保存、人間目視フィードバック保存まで扱う。

このSkillは新規に4案を広げるSkillではない。2-1で選ばれた案を磨き込み、採用方向のデザイン画像へ仕上げる後続工程として扱う。

このSkillは、1回の入力でStep 11まで完全自動で進めるものではない。ExcelのStep 10「デザインチェック(目視)・承認」とStep 11「知見格納」は、バナー案作成Skillと同じく人間確認を挟むPhase 2として扱う。正規運用は以下の2段階ゲートとする。

- Phase 1: 採用構成案/フィードバック入力から、デザイン生成、素材差し替え領域の特定、素材差し替え、Codex QA、AI QA結果のSharePoint知見保存までは自動で進める。その後、ユーザーへデザイン目視チェックと承認/修正フィードバックを依頼して停止する。
- Phase 2: ユーザーからデザイン画像フィードバック、承認、修正指示を受け取った後だけ実行する。受け取った内容を `human_feedback.md` に保存し、SharePointへ知見保存する。

今回の初期Scopeでは、以下は実行しない。

- デザイン確認用PPT生成
- 確認依頼メール/メッセージ作成と送信
- クライアント側承認結果のメール受領処理

## 必須入力

実行前に、以下を収集または確認する。

- `client_name`
- `campaign_name`
- `adopted_concepts`: 採用構成案または採用案ID。例: `concept_1`
- `banner_feedback`: 2-1で得たバナー案フィードバック、採用理由、修正指示
- `source_banner_images`: 採用案または元になるバナー案画像
- `logos`: 企業/ブランドロゴ
- 任意: `source_banner_run_dir`: 2-1 `banner-proposal` のrunフォルダ
- 任意: `brand_guidelines`
- 任意: `replacement_assets`: 差し替え対象の商品/背景/人物/素材
- 任意: `past_creatives`
- 任意: `banner_final_size`, `generation_size`, `delivery_size`, `image_quality`

必須ファイルがない場合は、ユーザーが明示的に「仮置き」「スキップ」を許可したときだけ進める。採用案、フィードバック、ロゴ、商品/素材の扱いは推測で確定しない。

## 参照ファイル

必要なステップに応じて、該当する参照だけを読む。

- `references/flow_2_2_design_production.md`: Excel由来の正規フロー。
- `references/existing_prompt_node_map.md`: Node②の素材置換プロンプト意図。画像領域以外の固定要素を守るときに読む。
- `references/sharepoint_knowledge_policy.md`: このSkill用のSharePoint保存ルール。
- `references/regulated_tobacco_guardrails.md`: たばこ、加熱式たばこ、ニコチン等の年齢制限商材向けガードレール。

## 実行フロー

### Phase 1: デザイン生成からAI QA知見保存まで自動

1. ワークスペース内に実行フォルダを作る。例: `outputs/banner-design-production/<run_id>/`
2. `scripts/prepare_design_production_run.py` で入力と初期成果物を作る。この時点で `phase_timings.json` と `brand_asset_cache.json` も作成する。
3. 2-1の採用構成案、採用案リスト、バナー案フィードバックを読み、デザイン生成方針を `design_brief.json` に整理する。
   - `source_banner_run_dir` がある場合は、`banner_concepts.json`、`qa_report.md`、`human_feedback.md`、`generated_image_*.png` を必要に応じて参照する。
   - 2-1のコピー、構成、ロゴ、CTA、トーン&マナーを不用意に変えない。
4. GPT Image 2でデザイン画像を生成または編集する。複数の採用案がある場合は `scripts/generate_gpt_image2_batch.py` を使い、標準は `quality=medium`、`--concurrency 2` とする。
   - APIから返却された画像解像度を納品マスターとして保持し、自動で低解像度へ上書きリサイズしない。
   - 元画像を使う場合は `--mode edit` と `--source-image` を使う。
5. 素材差し替え領域と固定要素を特定し、必要に応じてGPT Image 2のedit/maskを使う。Node②の原文意図に従い、画像を差し替える以外は、レイアウト、メインコピー、サブコピー、その他コピー、ロゴ、トーン&マナー、カラー、CTA周り、非画像要素を固定する。
   - 特定結果は `fixed_elements_analysis.md` に残す。画像要素、代表的なオブジェクト要素、その他画像要素以外のオブジェクト要素、メインコピー、サブコピー、その他コピー、ロゴ、レイアウト、トーン&マナー、カラー、CTA周りを最低限確認する。
6. Codex QAを行い、`qa_report.md` を更新する。
   - 基本仕様チェック: 必ず通す。
   - ハルシネーションチェック: 必ず通す。
   - 規制カテゴリチェック: 該当時は必ず通す。
   - ブランドガイドラインチェック: 実質的に準拠していることを確認する。
   - 過去CR類似性チェック: 似すぎていないか、または意図的な踏襲として許容できるか確認する。
7. QA完了後、生成されたデザインの良し悪しを今後再利用される知見としてSharePointへ格納する。
   - payload作成は `scripts/build_sharepoint_payload.py` を使う。
   - payloadはPower Automate Flow 1仕様に固定する。
   - SharePoint上の成果物フォルダ名は、Flowが `run_id` を使う前提で `banner-design-production__<client_name>__<campaign_name>__<YYYYMMDDTHHMMSSZ>` を標準にする。
   - 実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env` に `PA_SAVE_RUN_URL` と `PA_WORKFLOW_SECRET` がある場合は、`scripts/send_sharepoint_flow1.py` でPOSTまで実行する。
   - `.env` がない、またはPOSTが失敗した場合は、`sharepoint_save_payload.json` まで作成し、未保存状態をユーザーへ明示する。
8. Phase 1の最後に、生成画像、QA結果、保存結果を提示し、ユーザーへ「デザインチェック(目視)・承認」と画像フィードバックを依頼して必ず停止する。ユーザーの承認/フィードバックなしにPhase 2へ進まない。

### Phase 2: 人間目視フィードバックの保存

Phase 2はExcelのStep 10/11に対応する必須ゲート。Phase 1の続きとして、ユーザーからデザイン画像フィードバック、承認、修正指示を受け取った場合だけ開始する。

1. ユーザーからデザイン画像フィードバック、承認、修正指示を受け取る。
2. `scripts/record_design_feedback.py` で `human_feedback.md` に保存する。各フィードバックには `feedback-YYYYMMDDTHHMMSSZ`、受領日時(UTC)、受領日時(ローカル)、Run ID、案件名、承認ステータス、対象デザインを必ず入れる。
3. `scripts/build_sharepoint_payload.py` で `human_feedback.md` を含むpayloadを再作成し、`.env` がある場合は `scripts/send_sharepoint_flow1.py` でPOSTする。これはExcel Step 11の「生成されたデザインの良し悪しを今後再利用される知見としてSPへ格納」に対応する。
4. 修正指示がある場合は、該当デザインだけ修正し、必要に応じて画像生成/編集、Codex QA、SharePoint保存を再実行する。その後、再び目視チェックを依頼する。

## `banner-proposal` から流用する部分

以下は `banner-proposal` と同じ考え方・スクリプトを流用する。

- GPT Image 2生成/編集: `scripts/generate_gpt_image2.py`
- 複数画像の並列生成: `scripts/generate_gpt_image2_batch.py`
- SharePoint Flow 1 payload作成: `scripts/build_sharepoint_payload.py`
- SharePoint POST: `scripts/send_sharepoint_flow1.py`
- 資料/素材キャッシュ: `scripts/cache_brand_assets.py`
- フェーズ記録: `scripts/phase_timing_utils.py`
- 規制カテゴリチェック: `references/regulated_tobacco_guardrails.md`
- Node②の素材置換方針: `references/existing_prompt_node_map.md`

## GPT Image 2ルール

- まず環境変数 `OPENAI_API_KEY` を使う。なければ `scripts/generate_gpt_image2.py` が実行cwdの `.env`、Skill packの `.env`、`~/.config/acrc-codex-skills/.env`、さらに `~/.config/jt-codex/openai.env` を読める。秘密情報ファイルの権限は `600` にする。
- APIキーはSkillファイル、ログ、Markdown成果物、SharePoint payload本文に入れない。
- Excel上の媒体指定サイズが `600x500` の場合も、GPT Image 2には直接そのサイズを要求しない。入力テンプレートの `generation_size` を優先する。
- デフォルトは `quality=medium` とする。最終候補のみ、ユーザー指示がある場合に `high` で再生成する。

## セッション運用

同じCodexセッション内で、このSkillの続きだと分かる場合は同じrunのPhase 2または修正依頼として扱う。新しいセッション、文脈が曖昧な場合、または別案件を始める場合は、ユーザーに `$banner-design-production` の指定または対象runフォルダの指定を求める。

## 出力成果物

実行フォルダごとに、以下を作成または更新する。

- `run_summary.json`
- `design_spec.yaml`
- `design_brief.json`
- `fixed_elements_analysis.md`
- `gpt_image_prompt.json`
- `qa_report.md`
- `generated_image_*.png`
- `generated_image_*.png.metadata.json`
- `image_generation_batch_report.json`、並列画像生成時
- `phase_timings.json`
- `brand_asset_cache.json`
- `human_feedback.md`、Phase 2実行時
- `sharepoint_save_payload.json`、SharePoint保存時またはpayload作成時

## 秘密情報ルール

- Power Automate `.env`、OpenAI認証情報の値を読んで表示、要約、保存しない。
- ユーザー向け要約ではURLやsecretを伏せる。
- APIキーをSkillフォルダ、プロジェクト成果物、プロンプト、ログ、SharePoint payload本文へ保存しない。

## 安全な検証

```bash
python3 ~/.codex/skills/banner-design-production/scripts/prepare_design_production_run.py \
  --input ~/.codex/skills/banner-design-production/assets/design_production_input.template.yaml \
  --output-dir /tmp/banner-design-production-dry-run \
  --dry-run
```

```bash
python3 ~/.codex/skills/banner-design-production/scripts/build_sharepoint_payload.py \
  --run-dir /tmp/banner-design-production-dry-run \
  --output /tmp/banner-design-production-dry-run/sharepoint_save_payload.json
```

```bash
python3 ~/.codex/skills/banner-design-production/scripts/send_sharepoint_flow1.py \
  /tmp/banner-design-production-dry-run/sharepoint_save_payload.json \
  --dry-run
```
