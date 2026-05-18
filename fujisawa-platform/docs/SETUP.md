# fujisawa-platform セットアップ手順

| | |
|---|---|
| **対象** | `fujisawa-platform` を **本番 GCP** に配備する手順書 |
| **前提** | proposal 0003 / DESIGN.md / 実装済の Phase 4-2g までを把握していること |
| **このドキュメントの位置づけ** | terraform で 80% 自動化されるが、残り 20% (手動ステップ) を明示するための runbook |

---

## 0. 全体の流れ

```
[1] GCP プロジェクト準備 (bootstrap)
       ↓
[2] terraform state バケット作成
       ↓
[3] terraform apply (Phase 4-2h step 2/3 で書く)
       ↓
[4] Cloud SQL に init_schema.sql を適用 (1 回)
       ↓
[5] Secret Manager に値投入
       ↓
[6] Docker image build + push
       ↓
[7] Cloud Run Job smoke (dry-run で 1 Job 起動)
       ↓
[8] Cloud Scheduler の cron が走り始める
       ↓
[9] (任意、一度きり) wayback_backfill を手動 trigger
```

---

## 1. GCP プロジェクト準備 (bootstrap)

### 1.1 必要な準備

- GCP プロジェクト ID (新規 or 既存。driving-license-bot と同じ project 推奨)
- Billing 有効化
- Owner ロールを持つアカウント (terraform 実行者)

### 1.2 API 有効化 (terraform 内で `google_project_service` で網羅予定)

phase 4-2h step 2 の `apis.tf` でカバー予定:
- compute.googleapis.com
- run.googleapis.com
- cloudscheduler.googleapis.com
- sqladmin.googleapis.com
- artifactregistry.googleapis.com
- secretmanager.googleapis.com
- aiplatform.googleapis.com (Vertex AI)
- storage.googleapis.com (GCS bucket)
- iam.googleapis.com

初回は propagation に数分かかるので、`terraform apply` を 1 回失敗させてから再実行することもある。

---

## 2. terraform state バケット作成

`backend.tf` で参照する GCS バケットを **terraform 実行前に手動作成**:

```bash
gcloud storage buckets create gs://<terraform-state-bucket-name> \
    --project=<project-id> \
    --location=asia-northeast1 \
    --uniform-bucket-level-access
```

driving-license-bot と state バケットを共有しても良い (prefix を分ける)。

---

## 3. terraform apply (Phase 4-2h step 2/3)

```bash
cd fujisawa-platform/terraform
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars を編集して project_id / region / cloud_sql_instance などを設定

terraform init
terraform plan
terraform apply
```

これで以下が作成される (Phase 4-2h step 2/3 完了後):

- Cloud SQL Database `fujisawa_kb_db` (既存 instance に追加)
- Service Account `fujisawa-etl-sa@...`
- IAM bindings (etl_role / consumer_role 相当)
- Secret Manager リソース (値は §5 で投入)
- GCS bucket `fujisawa-pdf-archive`
- Cloud Run Jobs × 7
- Cloud Scheduler × 6 (定期 Job のみ、wayback_backfill は除く)
- Artifact Registry (image push 先)

---

## 4. Cloud SQL に init_schema.sql を適用 (1 回)

terraform で `fujisawa_kb_db` 自体は作成されるが、テーブル定義は別途。

```bash
# Cloud SQL Auth Proxy 経由で接続
cloud-sql-proxy <project-id>:asia-northeast1:<instance-name> &

# Postgres に schema を流す
psql "host=127.0.0.1 user=postgres dbname=fujisawa_kb_db" \
    -f fujisawa_platform/db/init_schema.sql
```

> 注意: pgvector extension がインスタンスに有効化されている必要あり。
> driving-license-bot で既に有効化されているはず (Phase 1 で `CREATE EXTENSION vector` 済)。

schema 適用後、IAM ロール (`etl_role` / `consumer_role`) も流す:

```bash
psql ... -c "GRANT INSERT, UPDATE, DELETE, SELECT ON ALL TABLES IN SCHEMA public TO etl_role;"
psql ... -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO consumer_role;"
```

(proposal 0003 §4.5.3 の責任分離。詳細 SQL は Phase 4-2h step 2 の `iam.tf` 同梱予定)

---

## 5. Secret Manager に値投入

terraform は Secret **リソース定義**を作るが、機密の値は別経路 (gcloud CLI など) で投入する:

```bash
# DB password (本番値を直接渡す)
echo -n "<actual-password>" | \
    gcloud secrets versions add fujisawa-etl-db-password --data-file=-

# User-Agent (連絡先 URL 込み)
echo -n "fujisawa-etl/0.1 (https://example.com/contact)" | \
    gcloud secrets versions add fujisawa-etl-user-agent --data-file=-

# Vertex AI project ID
echo -n "<gcp-project-id>" | \
    gcloud secrets versions add fujisawa-etl-vertex-project --data-file=-
```

Cloud Run Job 側は `FUJISAWA_ETL_DB_PASSWORD` 等を Secret Manager の `latest` バージョンから自動取得する (terraform で配線済み)。

---

## 6. Docker image build + push

### 6.1 Artifact Registry を terraform で用意

`terraform apply` 後、`docker-asia-northeast1.pkg.dev/<project-id>/fujisawa-etl` リポジトリが作成される。

### 6.2 イメージ build + push (推奨: Cloud Build)

リポジトリルートから:

```bash
gcloud builds submit \
    --config=fujisawa-platform/cloudbuild.yaml \
    --ignore-file=fujisawa-platform/cloudbuild.gcloudignore \
    --substitutions=_SHA=$(git rev-parse --short=7 HEAD) \
    .
```

- 同梱の `cloudbuild.gcloudignore` で他 agent ディレクトリを除外しており、 upload は数 MiB 程度に収まる
- ローカル docker が古い場合の buildx frontend pull 詰まりを回避できる
- 完了すると `asia-northeast1-docker.pkg.dev/<project-id>/fujisawa-etl/fujisawa-etl:<sha>` が push される

### 6.2b (代替) ローカル docker build + push

ローカル docker が新しく cross build できる環境ならこちらでも可。

```bash
gcloud auth configure-docker asia-northeast1-docker.pkg.dev
DOCKER_BUILDKIT=1 docker buildx build \
    --platform linux/amd64 \
    -f fujisawa-platform/Dockerfile \
    -t asia-northeast1-docker.pkg.dev/<project-id>/fujisawa-etl/fujisawa-etl:$(git rev-parse --short=7 HEAD) \
    --push \
    .
```

### 6.4 Cloud Run Job を新 image に更新

```bash
gcloud run jobs update fujisawa-weekly-crawl \
    --image asia-northeast1-docker.pkg.dev/<project-id>/fujisawa-etl/fujisawa-etl:<sha> \
    --region=asia-northeast1
```

(Phase 4-2h step 3 では terraform の `image` 変数を更新 → `terraform apply` で全 Job を一括更新できる構成にする予定)

---

## 7. Cloud Run Job smoke (dry-run)

実際に走らせる前に dry-run で smoke:

```bash
gcloud run jobs execute fujisawa-monthly-stats-compute \
    --region=asia-northeast1 \
    --args="monthly_stats_compute,--current-year=2026,--dry-run" \
    --wait
```

Log を Cloud Logging で確認、`run_etl_job` の started/finished/status="success" が記録されるかチェック。

---

## 8. Cloud Scheduler の cron が走り始める

terraform apply 後、自動で以下のスケジュールが有効化される:

| Job | cron (JST) | trigger |
|---|---|---|
| weekly_crawl | 毎週日曜 03:00 | `0 18 * * 6` (UTC) |
| half_yearly_facility | 4/10 月 1 日 03:00 | `0 18 30 3,9 *` (UTC、JST 翌日) |
| biyearly_admission | 2 月・3 月の指定日 | (要詳細決定) |
| monthly_vacancy | 毎月 22 日 03:00 | `0 18 21 * *` (UTC) |
| monthly_stats_compute | 毎月 23 日 03:00 | `0 18 22 * *` (UTC) |
| yearly_navi | 4/10 月 1 日 03:00 | `0 18 30 3,9 *` (UTC) |

`wayback_backfill` は **Scheduler に登録しない** (一度きり実行のため)。

---

## 9. (任意、一度きり) wayback_backfill を手動 trigger

過去データ (令和 4-6 年) のバックフィルが必要なら、明示的に有効化して 1 度だけ叩く:

```bash
# Step 1: enabled フラグを ON
gcloud run jobs update fujisawa-wayback-backfill \
    --update-env-vars=FUJISAWA_ETL_WAYBACK_BACKFILL_ENABLED=true \
    --region=asia-northeast1

# Step 2: 手動実行
gcloud run jobs execute fujisawa-wayback-backfill \
    --region=asia-northeast1 \
    --args="wayback_backfill" \
    --wait

# Step 3 (推奨): enabled フラグを再 OFF (誤発火防止)
gcloud run jobs update fujisawa-wayback-backfill \
    --update-env-vars=FUJISAWA_ETL_WAYBACK_BACKFILL_ENABLED=false \
    --region=asia-northeast1
```

> **NOTE**: 本 PR (Phase 4-2h step 1) では `cli.py` の `wayback_backfill` は `items=[]` で fallback している。実 BackfillItem リスト (令和 4-6 年の URL + timestamp) は Phase 4-2h step 3 で `wayback_items.py` モジュールに切り出すか、Cloud Run Job 起動時の `--args` で渡す想定。詳細は同 PR で確定。

---

## 10. Troubleshooting

| 症状 | 対処 |
|---|---|
| `psql: FATAL: password authentication failed` | Secret Manager の値が古い。`gcloud secrets versions add` で再投入 |
| Cloud Run Job が `Permission denied` で起動失敗 | SA に Cloud SQL Client / Secret Accessor / GCS Object Admin が付いているか確認 |
| `pgvector extension not installed` | Cloud SQL instance に `CREATE EXTENSION vector;` を流す必要あり |
| 5 連敗で `fail-fast` | `etl_runs` テーブルの直近 5 件を `WHERE status='failed'` で確認、根本原因を fix してから `etl_runs` を `UPDATE status='skipped_unchanged'` で前進させる |
| Cloud Scheduler が trigger しない | scheduler の SA に `run.invoker` ロールが付いているか確認 |

---

## 11. 関連ドキュメント

- [`docs/DESIGN.md`](DESIGN.md) — 設計詳細
- [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — proposal 本体
- [`../docs/PROPOSALS/notes/fujisawa-platform-etl-framework-evaluation-2026-05-12.md`](../../docs/PROPOSALS/notes/fujisawa-platform-etl-framework-evaluation-2026-05-12.md) — フレームワーク評価ノート
- driving-license-bot の `docs/SETUP.md` — Cloud SQL / IAM 設定のリファレンス実装
