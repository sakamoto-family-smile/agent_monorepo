# fujisawa-platform terraform

GCP 配備の構成。Phase 4-2h で導入。

## 構成

| step | 内容 | 状態 |
|---|---|---|
| step 1 | `etl/cli.py` + `Dockerfile` + `docs/SETUP.md` | ✅ 完了 (PR #129) |
| step 2 | terraform: Cloud SQL DB / Secret Manager / IAM / Artifact Registry / GCS bucket | ✅ 完了 (PR #130) |
| **step 3** | **terraform: Cloud Run Jobs × 7 + Cloud Scheduler × 6** | **🔶 本ディレクトリ (step 2 含む)** |

## このディレクトリのリソース

| ファイル | 内容 | step |
|---|---|---|
| `versions.tf` | terraform / provider バージョン pin | 2 |
| `backend.tf.example` | GCS state バケットのテンプレ (実 `backend.tf` は別途作成) | 2 |
| `variables.tf` | 入力変数 | 2 + 3 |
| `terraform.tfvars.example` | tfvars のサンプル (copy して `terraform.tfvars` を作る) | 2 + 3 |
| `locals.tf` | 命名規則 + 7 Job 定義の集約 | 2 + 3 |
| `apis.tf` | sqladmin / secretmanager / iam / storage / artifactregistry / aiplatform / run / cloudscheduler | 2 + 3 |
| `cloudsql.tf` | 共有 instance に `fujisawa_kb_db` を追加 + ETL 用ユーザ | 2 |
| `secrets.tf` | DB password / User-Agent / Vertex project の Secret 枠 + IAM | 2 |
| `iam.tf` | `sa-fujisawa-etl` + `sa-fujisawa-scheduler` SA + プロジェクト IAM | 2 + 3 |
| `gcs.tf` | `fujisawa-pdf-archive` bucket + IAM | 2 |
| `artifact_registry.tf` | Docker repo `fujisawa-etl` | 2 |
| `cloud_run_jobs.tf` | Cloud Run Jobs × 7 (for_each、Cloud SQL connector + Secret env) | 3 |
| `scheduler.tf` | Cloud Scheduler × 6 (wayback_backfill 除く、Run Job invoker) | 3 |
| `outputs.tf` | step 3 と consumer 側で参照する値 | 2 + 3 |

## 使い方 (2 段階 apply)

`etl_image` が空文字列だと Cloud Run Jobs と Scheduler の deploy がスキップされる
(chicken-and-egg: image が無い状態で Cloud Run Job リソースを作れないため)。

### 1 回目: GCP 基盤を apply (image なし)

```bash
cd fujisawa-platform/terraform
cp backend.tf.example backend.tf      # bucket / prefix を埋める
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars: project_id / shared_cloudsql_instance_name 等を埋める
# etl_image は "" のまま (Cloud Run / Scheduler はまだ deploy しない)

terraform init
terraform plan
terraform apply
```

これで Cloud SQL DB / Secret Manager / IAM / GCS bucket / Artifact Registry が作成される。

### Docker image を build & push

```bash
DOCKER_BUILDKIT=1 docker build -f fujisawa-platform/Dockerfile \
    -t asia-northeast1-docker.pkg.dev/<project>/fujisawa-etl/fujisawa-etl:$(git rev-parse --short HEAD) .
gcloud auth configure-docker asia-northeast1-docker.pkg.dev
docker push asia-northeast1-docker.pkg.dev/<project>/fujisawa-etl/fujisawa-etl:<sha>
```

### 2 回目: Cloud Run Jobs + Scheduler を apply

```bash
# terraform.tfvars の etl_image に↑で push した URI を書く
# 例: etl_image = "asia-northeast1-docker.pkg.dev/<project>/fujisawa-etl/fujisawa-etl:<sha>"

terraform apply
```

これで Cloud Run Job × 7 + Cloud Scheduler × 6 が deploy される。

## 配備後の手動ステップ

詳細は [`../docs/SETUP.md`](../docs/SETUP.md) 参照。要約:

1. **`init_schema.sql` 適用** (Cloud SQL Auth Proxy 経由で psql)
2. **PostgreSQL ROLE 設定**: `GRANT ... TO etl_role / consumer_role` を流す (proposal §4.5.3)
3. **Secret Manager の値投入**:
   - `db_password`: terraform で自動投入済 (random_password)
   - `user_agent`: `echo -n "fujisawa-etl/0.1 (https://example.com)" | gcloud secrets versions add fujisawa-etl-user-agent --data-file=-`
   - `vertex_project`: `echo -n "<project-id>" | gcloud secrets versions add fujisawa-etl-vertex-project --data-file=-`
4. **(任意) Job 単体 smoke**: `gcloud run jobs execute fujisawa-monthly-stats-compute --args="monthly_stats_compute,--current-year=2026,--dry-run" --region=asia-northeast1 --wait`
5. **(一度きり) wayback_backfill**: enabled フラグを ON にして手動 invoke (SETUP.md §9)

## 設計判断

- **既存 Cloud SQL instance を共有**: proposal §4.5 の「月 ¥0 増」方針。data source で参照
- **Secret 値の自動投入は password のみ**: User-Agent / Vertex project は手動
- **bucket 名に project_id 付与**: GCS bucket 名はグローバル一意
- **Artifact Registry の retention**: 直近 10 個保持 + 30 日以上前は削除
- **chicken-and-egg を 2 段 apply で解決**: `etl_image=""` のときは Run Job / Scheduler を skip
- **image 更新時の drift**: `lifecycle.ignore_changes = [containers[0].image]` で `gcloud run jobs update` による image 差し替えを許容
- **Cloud SQL は Unix socket 接続**: `/cloudsql/<connection_name>` をマウント、asyncpg は host が `/` 始まりだと socket と認識
- **wayback_backfill は Scheduler 登録なし**: 一度きり実行 (proposal §4.5.4)、手動 `gcloud run jobs execute`

## 関連

- [`../docs/SETUP.md`](../docs/SETUP.md) — GCP 構築 runbook
- [`../docs/DESIGN.md`](../docs/DESIGN.md) — 設計
- [`../../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — proposal 本体
