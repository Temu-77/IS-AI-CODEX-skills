---
name: banner-proposal
description: バナー案作成フローを3段階ゲートで実行する。クライアント/案件情報、オリエン資料、参考バナー、背景素材、ロゴ、ブランドガイドラインをもとに4案を作成し、画像生成、Codex QA、SharePoint知見保存、人間目視フィードバック保存、ユーザー指示後のCanvas受容性評価まで進めるときに使う。
---

# Banner Proposal

## 目的

このSkillは `2-1. バナー案作成` フローを日本語で実行するためのもの。4案のバナー案を作成し、GPT Image 2用プロンプトを作り、画像生成/素材差し替え、Codex QA、Power Automate/SharePoint知見保存、人間フィードバック保存、ユーザー指示後のCanvas受容性評価まで扱う。

このSkillは、1回の入力で「受容性評価結果の確認・承認」まで完全自動で進めるものではない。正規運用は以下の3段階ゲートとする。

- Phase 1: 初回入力から、企業/ブランド情報取得、オリエン分析、4案作成、画像生成/編集、Codex QA、生成バナー案とQAのSharePoint知見保存までは自動で進める。
- Phase 2: いったん停止し、ユーザーへ「バナー案チェック(目視)・承認」と画像フィードバックを依頼する。フィードバックを受け取ったら、`human_feedback.md` とSharePointへ保存する。
- Phase 3: ユーザーがVS Code/Codex上で受容性評価実行を指示した場合だけ、Codex/Canvasで受容性評価を実施し、結果を返して確認・承認を依頼する。

原則として、ユーザーへの説明、成果物内の説明文、バナーコピー、評価コメント、参考プロンプトの解釈は日本語で行う。JSONキーやスクリプト引数など、機械処理に必要な識別子は英語のままでよい。

## 必須入力

実行前に、以下を収集または確認する。

- `client_name`
- `campaign_name`
- `orientation_file`: PDF、Excel、PPTX、またはテキスト抽出
- 参考バナー画像
- 背景/商品/素材画像
- ロゴ画像
- 任意: `service_target`、キャンペーン目的、求めるトーン、ブランドガイドライン、禁止表現、過去CR

必須ファイルがない場合は、ユーザーが明示的に「仮置き」「スキップ」を許可したときだけ進める。クライアント、キャンペーン、法務/ブランド情報は推測で確定しない。

## 参照ファイル

必要なステップに応じて、該当する参照だけを読む。

- `references/flow_2_1_banner_concept.md`: Excel由来の正規フロー。
- `references/existing_prompt_node_map.md`: `既存プロンプト` シートとノードYAML由来のノード対応表。Node①/Node②の原文プロンプト意図、絶対条件、固定要素、出力形式はこのファイルを優先し、日本語の言い回しと強調条件をできるだけ保持する。
- `references/canvas_acceptance_eval.md`: Canvas受容性評価の実行ルール。
- `references/sharepoint_knowledge_policy.md`: Power Automate/SharePoint保存ルール。
- `references/regulated_tobacco_guardrails.md`: たばこ、加熱式たばこ、ニコチン等の年齢制限商材向けガードレール。

## 実行フロー

### Phase 1: 初回入力からAI QA知見保存まで自動

1. ワークスペース内に実行フォルダを作る。例: `outputs/banner-concept/<run_id>/`
2. `scripts/prepare_banner_concept_run.py` で入力と初期成果物を作る。この時点で `phase_timings.json` と `brand_asset_cache.json` も必ず作成する。
3. Codexで調査/分析する。Node①-#1からNode①-#6までは、`references/existing_prompt_node_map.md` の原文プロンプト意図を参照し、各ノードの調査/分析結果を後続のNode①-#7で使えるテキストとして整理する。
   - 企業、ブランド、キャンペーン、タレント/アーティスト、サービス情報をWeb検索する。
   - オリエン資料を要約する。
   - 案件に使えるバナーCRセオリーを調査する。
   - 参考バナー、背景素材、ロゴを分析する。
4. `banner_concepts.json` に4案だけ作る。Node①-#7をベースにし、提供素材/ロゴを前提に、元バナーから意味のある絵替わりを作り、メインコピー、サブコピー、その他コピー、ビジュアル方向性、レイアウト、素材/ロゴ利用方針、画像生成プロンプトまで1案ごとにまとめる。
   - コピーがユーザー指定されている場合は指定コピーを優先し、勝手に別コピーへ置き換えない。
   - コピーが未指定の場合は、Node①-#7の原文意図に従い、Codexが各案のメインコピー/サブコピー/その他コピーを提案してよい。
   - 「価格優位性」はオリエン/キャンペーン情報に価格訴求がある場合だけ使う。ない場合はキャンペーン主訴求、商品/体験価値、ブランド訴求に置き換える。
   - たばこ、加熱式たばこ、ニコチン、酒類、医療、金融など規制カテゴリの場合は、コピーや画像プロンプト作成前に該当ガードレールを読む。
5. 実行が要求され、OpenAI APIキーが使える場合のみ、GPT Image 2で画像生成する。4案生成は `scripts/generate_gpt_image2_batch.py` を使い、デフォルトは `quality=medium`、`--concurrency 4` とする。APIから返却された画像解像度を納品マスターとして保持し、自動で `600x500` へ上書きリサイズしない。
6. 素材差し替え領域と固定要素を特定し、必要に応じてGPT Image 2のedit/maskを使う。Node②の原文意図に従い、画像を差し替える以外は、レイアウト、メインコピー、サブコピー、その他コピー、ロゴ、トーン&マナー、カラー、CTA周り、非画像要素を固定する。ユーザーが変更を求めない限り、固定要素は維持する。編集後もAPI返却解像度を保持する。
7. Codex QAを行い、`qa_report.md` を作る。
   - 基本仕様チェック: 必ず通す。
   - ハルシネーションチェック: 必ず通す。
   - 規制カテゴリチェック: 該当時は必ず通す。
   - ブランドガイドラインチェック: 実質的に準拠していることを確認する。
   - 過去CR類似性チェック: 似すぎていないか、または意図的な踏襲として許容できるか確認する。
8. QA完了後、生成バナー案の良し悪しを今後再利用される知見としてSharePointへ格納する。
   - payload作成は `scripts/build_sharepoint_payload.py` を使う。
   - payloadはPower Automate Flow 1仕様に固定し、artifactは必ず `file_name`、`content_type`、`content` または `content_base64` を持つ。
   - SharePoint上の成果物フォルダ名は、Flowが `run_id` を使う前提で `banner-production__<client_name>__<campaign_name>__<YYYYMMDDTHHMMSSZ>` のテンプレートを標準にする。
   - 実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env` に `PA_SAVE_RUN_URL` と `PA_WORKFLOW_SECRET` がある場合は、`scripts/send_sharepoint_flow1.py` でPOSTまで実行する。ローカルPythonの証明書ストア差分を避けるため、直接 `power_automate_workflow_template/scripts/send_flow1_save_run.py` は呼ばない。
   - `.env` がない、またはPOSTが失敗した場合は、`sharepoint_save_payload.json` まで作成し、未保存状態をユーザーへ明示する。
9. Phase 1の最後に、生成画像、QA結果、保存結果を提示し、ユーザーへ「バナー案チェック(目視)・承認」と画像フィードバックを依頼して停止する。

### Phase 2: 人間目視フィードバックの保存

1. ユーザーからバナー案画像フィードバック、承認、修正指示を受け取る。
2. 受け取った内容を `scripts/record_human_feedback.py` で `human_feedback.md` に保存する。各フィードバックには `feedback-YYYYMMDDTHHMMSSZ`、受領日時(UTC)、受領日時(ローカル)、Run ID、案件名、承認ステータス、対象案を必ず入れる。画像ごとの良し悪し、採用可否、修正希望、承認状況を明確に分ける。
3. フィードバックをSharePointへ保存する。
   - `scripts/build_sharepoint_payload.py` で `human_feedback.md` を含むpayloadを再作成する。
   - 実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env` にPower Automate設定がある場合は `scripts/send_sharepoint_flow1.py` でPOSTまで実行する。
4. 修正指示がある場合は、該当案だけ修正し、必要に応じて画像生成/編集、Codex QA、SharePoint保存を再実行する。その後、再び目視チェックを依頼する。
5. ユーザーが承認したら、Phase 3の受容性評価実行指示を待つ。

### Phase 3: ユーザー指示後のCanvas受容性評価

1. Canvas受容性評価は、ユーザーが「受容性評価を実行して」など明示した後だけ実行する。
2. このSkillではCanvasを受容性評価に限定し、上流のターゲット設計やコピー作成にはデフォルトで使わない。
3. `scripts/run_canvas_acceptance_eval.py` を使い、承認済みまたは評価対象のバナー案をCanvas APIへ直接POSTする。ローカルのCanvas CLIや認証CSVは呼ばない。
4. Canvas送信プロンプトはデフォルトで `canvas_acceptance_prompt_sanitized.txt` とし、ローカル絶対パス、URL、秘密情報を本文に含めない。Canvas APIには画像ファイル本体を添付しないため、画像は `concept_1` などのasset ID、ファイル名、コンセプト要約で参照する。
   - CloudFront/WAFのPOST本文検査を避けるため、Canvas送信プロンプトは標準で6500 bytes以下に抑える。QA抜粋は短くし、必要な場合だけ `--max-qa-chars` を明示して増やす。
5. `canvas_outputs.json` は `schema_version=canvas_acceptance_eval.v1` のテンプレートに固定する。機械処理用には `delivery_recommendation` を `deliver`、`revise`、`reject` のいずれかで保存し、ユーザー表示用には `delivery_judgement_jp` を `配信可`、`修正後配信可`、`配信不可` のいずれかに正規化する。
6. Canvas POSTがHTTP 403かつCloudFrontのHTMLを返した場合は、Canvasエージェント処理失敗ではなくCloudFront/WAFでブロックされた通信失敗として扱う。`canvas_outputs.json` には `error_type=cloudfront_403`、`attempts`、`error_summary`、`likely_cause` を保存し、SharePoint payloadにも失敗ログとして残す。
7. ユーザーへ返す受容性評価結果は、`canvas_outputs.json` の `user_summary_markdown` をもとに、以下の日本語項目名で返す。
   - バナー案
   - AIペルソナ評価スコア
   - 配信可否判定
   - 評価理由
   - 改善アドバイス
8. 結果を `canvas_outputs.json` に保存し、ユーザーへ確認・承認を依頼して停止する。

## GPT Image 2ルール

- まず環境変数 `OPENAI_API_KEY` を使う。なければ `scripts/generate_gpt_image2.py` が実行cwdの `.env`、Skill packの `.env`、`~/.config/acrc-codex-skills/.env`、さらに `~/.config/jt-codex/openai.env` を読める。秘密情報ファイルの権限は `600` にする。
- APIキーはSkillファイル、ログ、Markdown成果物、SharePoint payload本文に入れない。
- Excel上の媒体指定サイズが `600x500` の場合も、GPT Image 2には直接そのサイズを要求しない。`1200x1008` などGPT Image 2で有効な高解像度サイズで生成し、API返却画像を同じ解像度のまま納品マスターとして保存する。
- `600x500` は媒体上の想定表示サイズ/比率の参照値として扱う。明示的に必要な場合だけ、納品マスターとは別名でリサイズ版を作る。
- デフォルトは `quality=medium` とする。4案の初回生成は `scripts/generate_gpt_image2_batch.py` で並列化する。最終候補のみ、ユーザー指示がある場合に `high` で再生成する。
- 並列生成の標準コマンド:

```bash
python3 ~/.codex/skills/banner-proposal/scripts/generate_gpt_image2_batch.py \
  --prompt-file <run_dir>/gpt_image_prompt.json \
  --output-dir <run_dir> \
  --mode edit \
  --quality medium \
  --concurrency 4 \
  --source-image <asset_path>
```

- `scripts/generate_gpt_image2.py` は、`--resize-to-final-size` を明示した場合だけ `--final-size` へトリミング/リサイズする。通常実行では `final_size` が指定されていても自動リサイズしない。
- 生成画像ごとに `<image>.metadata.json` を保存し、要求サイズ、保存サイズ、リサイズ有無を確認できるようにする。
- 画像内テキストは読みやすく指示するが、生成後に必ず目視/QAで確認する。

## ブランド資料解析キャッシュ

- `prepare_banner_concept_run.py` は `orientation_file`、`brand_guidelines`、`logos`、`background_assets`、`reference_banners`、`past_creatives` をhash化し、`brand_asset_cache.json` をrunフォルダへ作る。
- 実体キャッシュは `$BANNER_PROPOSAL_CACHE_DIR` があればそこを使い、なければ実行cwd配下の `.cache/banner-proposal/brand-assets/` を使う。
- PPTXはスライドXMLからテキストを抽出する。PDFは `pypdf` が使える場合のみ抽出し、使えない場合はmetadata cacheまでで止める。
- 同じ資料を再利用する場合は `brand_asset_cache.json` とcache内 `metadata.json` / `extracted_text.txt` を優先し、同じPDF/PPTXを毎回全文再解析しない。

## Canvas / SharePoint確認

外部連携の状態確認には、必要に応じて以下を実行する。

```bash
python3 ~/.codex/skills/banner-proposal/scripts/check_external_integrations.py
```

- Canvasは、`CANVAS_API_KEY`、`CANVAS_COMPANY_ID`、`CANVAS_AGENT_ID` が環境変数または `.env` にあれば受容性評価プロンプト作成と実行が可能。
- SharePointは、Power Automate設定と送信スクリプトがあればpayload作成は可能。実POSTには実行cwdの `.env`、Skill packの `.env`、または `~/.config/acrc-codex-skills/.env` に `PA_SAVE_RUN_URL` と `PA_WORKFLOW_SECRET` が必要。
- SharePoint POSTは `scripts/send_sharepoint_flow1.py` を使う。このスクリプトは `certifi` のCA bundleを明示してTLS検証するため、ローカルPython 3.14の証明書ストア未設定による初回POST失敗を避ける。
- 状態確認時も、APIキー、Canvasキー、Power Automate URL/secretは表示しない。

## セッション運用

同じCodexセッション内で一度このSkillを使い始めた後は、後続の入力がPhase 2のフィードバック、Phase 3の受容性評価指示、または同じrunの修正依頼だと分かる場合、このSkillの続きとして扱う。新しいセッション、文脈が曖昧な場合、または別案件を始める場合は、ユーザーに `$banner-proposal` の指定または対象runフォルダの指定を求める。

## 出力成果物

実行フォルダごとに、以下を作成または更新する。

- `run_summary.json`
- `banner_spec.yaml`
- `banner_concepts.json`
- `gpt_image_prompt.json`
- `qa_report.md`
- `generated_image_*.png`
- `generated_image_*.png.metadata.json`
- `image_generation_batch_report.json`、並列画像生成時
- `phase_timings.json`
- `brand_asset_cache.json`
- `canvas_outputs.json`、Canvas実行時
- `sharepoint_save_payload.json`、SharePoint保存時またはpayload作成時

## 秘密情報ルール

- Canvas API key、Power Automate `.env`、OpenAI認証情報の値を読んで表示、要約、保存しない。
- ユーザー向け要約ではURLやsecretを伏せる。
- OpenAI APIキーをSkillフォルダ、プロジェクト成果物、プロンプト、ログ、SharePoint payload本文へ保存しない。
- 生成成果物は、ユーザーが明示的に依頼しない限りコミット対象にしない。

## 安全な検証

```bash
python3 ~/.codex/skills/banner-proposal/scripts/prepare_banner_concept_run.py \
  --input ~/.codex/skills/banner-proposal/assets/banner_concept_input.template.yaml \
  --output-dir /tmp/banner-proposal-dry-run \
  --dry-run
```

```bash
python3 ~/.codex/skills/banner-proposal/scripts/build_sharepoint_payload.py \
  --run-dir /tmp/banner-proposal-dry-run \
  --output /tmp/banner-proposal-dry-run/sharepoint_save_payload.json
```

```bash
python3 ~/.codex/skills/banner-proposal/scripts/send_sharepoint_flow1.py \
  /tmp/banner-proposal-dry-run/sharepoint_save_payload.json \
  --dry-run
```

```bash
python3 ~/.codex/skills/banner-proposal/scripts/record_human_feedback.py \
  --run-dir /tmp/banner-proposal-dry-run \
  --approval-status approved \
  --selected-concept concept_1 \
  --feedback "concept_1を承認。CTAの視認性は良い。"
```
