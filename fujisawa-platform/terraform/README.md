# fujisawa-platform terraform

GCP 配備の構成。Phase 4-2h で導入。

## 構成 (3 ステップで実装)

| step | 内容 | 状態 |
|---|---|---|
| step 1 | `etl/cli.py` + `Dockerfile` + `docs/SETUP.md` | ✅ 完了 (PR #129) |
| **step 2** | **terraform: Cloud SQL DB / Secret Manager / IAM / Artifact Registry / GCS bucket** | **🔶 本ディレクトリ** |
| step 3 | terraform: Cloud Run Jobs × 7 + Cloud Scheduler × 6 | ⏳ 未着手 |

## このディレクトリのリソース (step 2)

| ファイル | 内容 |
|---|---|
| `versions.tf` | terraform / provider バージョン pin |
| `backend.tf.example` | GCS state バケットのテンプレ (実 `backend.tf` は別途作成) |
| `variables.tf` | 入力変数 |
| `terraform.tfvars.example` | tfvars のサンプル (copy して `terraform.tfvars` を作る) |
| `locals.tf` | 命名規則の集約 |
| `apis.tf` | sqladmin / secretmanager / iam / storage / artifactregistry / aiplatform を有効化 |
| `cloudsql.tf` | 共有 instance に `fujisawa_kb_db` を追加 + ETL 用ユーザ |
| `secrets.tf` | DB password / User-Agent / Vertex project の Secret 枠 + IAM |
| `iam.tf` | `sa-fujisawa-etl` Service Account + プロジェクトレベル IAM |
| `gcs.tf` | `fujisawa-pdf-archive` bucket + IAM |
| `artifact_registry.tf` | Docker repo `fujisawa-etl` |
| `outputs.tf` | step 3 と consumer 側で参照する値 |

## 使い方 (step 2 単体)

```bash
cd fujisawa-platform/terraform

# 初回: backend を準備
cp backend.tf.example backend.tf
# backend.tf を編集して bucket / prefix を埋める (docs/SETUP.md §2)

# tfvars 設定
cp terraform.tfvars.example terraform.tfvars
# terraform.tfvars を編集

terraform init
terraform plan
terraform apply
```

## 配備後の手動ステップ

詳細は [`../docs/SETUP.md`](../docs/SETUP.md) 参照。要約:

1. **`init_schema.sql` 適用** (Cloud SQL Auth Proxy 経由で psql)
2. **PostgreSQL ROLE 設定**: `GRANT ... TO etl_role / consumer_role` を流す (proposal §4.5.3)
3. **Secret Manager の値投入**:
   - `db_password`: terraform で自動投入済 (random_password)
   - `user_agent`: `echo -n "fujisawa-etl/0.1 (https://example.com)" | gcloud secrets versions add ...`
   - `vertex_project`: `echo -n "<project-id>" | gcloud secrets versions add ...`
4. **Docker image build + push**: `docker push <artifact_registry_repo_url>/fujisawa-etl:<sha>`

## 設計判断

- **既存 Cloud SQL instance を共有**: proposal §4.5 の「月 ¥0 増」方針。terraform は instance を作成せず data source で参照
- **Secret 値の自動投入は password のみ**: User-Agent / Vertex project は機密度に応じて手動投入
- **bucket 名に project_id 付与**: GCS bucket 名はグローバル一意。`fujisawa-pdf-archive-<project>` で衝突回避
- **Artifact Registry の retention**: 直近 10 個保持 + 30 日以上前は削除 (`cleanup_policies` 2 段)
- **Workload Identity 配線は step 3 で**: Cloud Run Job リソースが必要なため、step 3 で完成

## 関連

- [`../docs/SETUP.md`](../docs/SETUP.md) — GCP 構築 runbook
- [`../docs/DESIGN.md`](../docs/DESIGN.md) — 設計
- [`../../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — proposal 本体
