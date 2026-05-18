# 2-1. バナー案作成 正規フロー

正: `JT_ToBe制作フロー&モンゴル合宿討議ポイント_v0.1.xlsx` > `新TOBE(ワークフローAI用)` シート > `2-1. バナー案作成`。

## 入力

- クライアント/案件: `client_name`, `campaign_name`
- オリエン資料: PDF、Excel、PPTX、またはテキスト抽出
- 追加素材
- 参考バナー画像
- 背景/商品/素材画像
- ロゴ画像
- 任意のターゲット/目的: `service_target`、キャンペーン目的、KPIなど

## 正規ステップ

| Step | 操作 | ツール | 入力 | 出力 |
| --- | --- | --- | --- | --- |
| 1 | クライアント名・案件名の設定 | VS Code / Codex | client/campaign names | なし |
| 2 | オリエンシートのアップロード | VS Code / Codex | orientation PDF / Excel / PPTX | なし |
| 3 | 素材のアップロード | VS Code / Codex | 追加素材 | なし |
| 4 | 企業/ブランド情報の取得 | Codex Web検索 | client/campaign names | クライアント/サービス/タレント/キャンペーン概要 |
| 5 | オリエン情報の取得 | Codex | orientation file | 企画要約、重要ポイント |
| 6 | バナーCRセオリー情報の取得 | Codex Web検索 | client/campaign names | 適用可能なデザイン理論、レイアウト示唆 |
| 7 | 参考画像の分析 | Codex画像分析 | reference banners | レイアウト、トーン分析 |
| 8 | 背景画像の分析 | Codex画像分析 | background assets | 背景/商品/素材分析 |
| 9 | ロゴの分析 | Codex画像分析 | logo images | ロゴ分析 |
| 10 | バナー案を作成、4パターン | Codex | ここまでの全分析 | `banner_concepts.json` |
| 11 | バナー案を元に画像生成、4パターン | GPT Image 2 | concept prompts | API返却解像度の初期バナー画像 |
| 12 | 素材差し替え領域の特定 | Codex画像分析 | 生成画像、差し替え素材 | 差し替え領域/固定要素分析 |
| 13 | 素材差し替え | GPT Image 2 edit/mask | 領域分析、素材 | API返却解像度の差し替え完了バナー画像 |
| 14 | 基本仕様チェック | Codex | 差し替え完了画像 | QA結果、必ず通過 |
| 15 | ブランドガイドラインチェック | Codex | 差し替え完了画像 | QA結果、実質準拠を確認 |
| 16 | ハルシネーションチェック | Codex | 差し替え完了画像 | QA結果、必ず通過 |
| 17 | 過去CRとの類似性チェック | Codex | 差し替え完了画像、過去CR | QA結果、実質準拠を確認 |
| 18 | AI QA知見格納 | Codex / SharePoint | QA結果 | SharePoint知見データ |
| 19 | 目視チェック・承認 | VS Code / Codex | 画像、QA結果 | 人間フィードバック |
| 20 | 目視フィードバック知見格納 | Codex / SharePoint | 人間フィードバック | SharePoint知見データ |
| 21 | 受容性評価実行指示 | VS Code / Codex | 差し替え完了画像 | 実行指示 |
| 22 | 受容性評価実施 | Codex / Canvas | 承認済み画像、目的 | 受容性評価 |
| 23 | 受容性評価結果の確認・承認 | VS Code / Codex | 評価結果 | 承認 |

## 実行ゲート

このフローは、1入力からStep 23まで完全自動で進めない。運用上は次の3段階に分ける。

### Phase 1: 自動実行

Step 4「企業/ブランド情報の取得」からStep 18「AI QA知見格納」までは、初回入力後に一時的に自動で行う。

- Web検索、オリエン分析、素材/ロゴ/参考バナー分析、4案作成、画像生成/編集、Codex QAを連続実行する。
- 画像生成/編集では、GPT Image 2から返却された画像を同じ解像度の納品マスターとして保存する。`600x500` などの媒体指定サイズは比率/表示想定として参照し、自動上書きリサイズはしない。
- QA後、生成されたバナー案の良し悪しを今後再利用される知見としてSharePointへ格納する。
- Power Automate `.env` がある場合はPOSTまで実行する。ない場合やPOST失敗時は、payload作成までで止め、未保存状態を明示する。
- Phase 1完了後は、画像とQA結果を提示し、ユーザーの目視チェックを待つ。

### Phase 2: ユーザー目視チェックとフィードバック保存

Step 19「目視チェック・承認」とStep 20「目視フィードバック知見格納」は、人間の判断を挟む。

- ユーザーに「バナー案チェック(目視)・承認」を依頼する。
- バナー案画像フィードバックを受け取ったら、`human_feedback.md` に保存する。
- Codex/SharePointでフィードバックを知見保存する。
- 修正指示がある場合は該当案を修正し、必要に応じてQAとSharePoint保存を再実行する。

### Phase 3: 指示後のCanvas受容性評価

Step 21以降は、ユーザーがVS Code/Codex上で受容性評価実行を入力または指定してから行う。

- Codex/Canvasで受容性評価を実施する。
- 返す項目は、バナー案、AIペルソナ評価スコア、配信可否判定、評価理由、改善アドバイス。
- 配信可否判定は、ユーザー表示では `配信可`、`修正後配信可`、`配信不可` に固定する。機械処理用の `delivery_recommendation` は `deliver`、`revise`、`reject` のいずれかに固定する。
- 結果を `canvas_outputs.json` に保存し、ユーザーへ確認・承認を依頼する。

## Skill 1では任意/範囲外

- Step 24: バナー確認用PPT生成
- Step 25: 確認依頼メール/メッセージ作成と送信
- Step 26: クライアントのバナーフィードバックと採用案決定
- Step 27: フィードバック/採用案の受領

これらは将来拡張扱いとし、Skill 1のデフォルト実行には含めない。

## ループルール

- 基本仕様チェックが落ちた場合は、案/プロンプト調整または画像生成へ戻る。
- ハルシネーションチェックが落ちた場合は、画像生成または編集へ戻る。
- ブランドガイドラインや過去CR類似性が部分NGの場合は、重要度とユーザー目的に応じて修正要否を判断する。

## 必須成果物

- `run_summary.json`
- `banner_spec.yaml`
- `banner_concepts.json`
- `gpt_image_prompt.json`
- `qa_report.md`
- `generated_image_*.png`
- `canvas_outputs.json`、Canvas実行時
- `sharepoint_save_payload.json`、SharePoint保存時またはpayload作成時
