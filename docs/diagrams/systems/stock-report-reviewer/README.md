# stock-report-reviewer

`stock-analysis-agent` が生成する株価分析レポートを CrewAI ベースで品質レビューするパイプラインの GCP 構成図。

設計詳細は [`docs/PROPOSALS/0013-stock-report-review-pipeline.md`](../../../PROPOSALS/0013-stock-report-review-pipeline.md) 参照。

## 図

![GCP architecture](gcp.png)

- `spec.gcp.mjs` — データ (このシステムの真実の出典)
- `gcp.svg` / `gcp.png` — 生成物
- `StockReportReviewerDiagram.tsx` — React コンポーネント (埋め込み SVG・依存ゼロ)

## データフロー概要

1. **Ingestion**: `stock-analysis-agent` がレポート生成完了時に SQLite と GCS (`raw/<ticker>/<dt>.md`) に dual-write
2. **Trigger**: GCS Object Notification → Pub/Sub topic `stock-report-created` → enqueue-svc が Pub/Sub push を受信 → Cloud Tasks に enqueue
3. **Review (CrewAI)**: Cloud Tasks dispatch → `review-worker` が起動
   - **6 reviewer (並列)**: Fact Checker / Logic Reviewer / Tone Reviewer / Bias Reviewer / Risk Reviewer / Style Editor → Vertex AI Gemini 2.5 (Pro / Flash 使い分け)
   - **Lead Manager**: 6 scoring を集約、verdict 判定 (`auto_publish` / `ai_improve_then_review` / `direct_human_review`)
   - **Improver** (条件付き): must_fix を反映して改稿版を生成
4. **Persist**: 結果を以下に書き出し
   - `gs://stock-reports/reviewed/<ticker>/<dt>.json` (scores + issues)
   - `gs://stock-reports/improved/<ticker>/<dt>.md` (verdict 次第)
   - Cloud SQL `stock_review_db.reviews` (人間レビュー queue)
   - BigQuery `stock_review.reviews` (時系列集計用、streaming insert)
5. **Human review**: `review-ui` で pending list 閲覧 → approve / reject / revise
   - approve → `gs://stock-reports/approved/<ticker>/<dt>.md` にコピー
   - reject → `gs://stock-reports/archived/`
   - revise → コメント付きで CrewAI Improver に再委託
6. **Auth**: Web UI は IAP で個人 / 家族 email allowlist

## 更新方法

spec を編集後:

```bash
cd docs/diagrams
node build-system.mjs systems/stock-report-reviewer  # gcp.svg + .tsx
python3 rasterize.py systems/stock-report-reviewer/gcp.svg  # gcp.png
```
