# Phase 2 実装プラン

> Phase 1（手動キュレーション 30 問プールで LINE Bot 最小公開）完了後の実装計画。
> [DESIGN.md §11](./DESIGN.md) に対応。レビュー Web UI は当初 Phase 0.5 として切り出していたが、
> 自動生成 pipeline と密結合するため **Phase 2-C** に再分類した。

## 0. 現状サマリ

`/Users/shotasakamoto/development/python/agent_monorepo/driving-license-bot/` 配下を確認した時点で、
**Phase 2-A〜2-B のアプリケーションコードはほぼ実装済み**:

| 領域 | 状態 |
|---|---|
| `app/agent/{question_generator,fact_checker,quality_reviewer,pipeline,embedding,llm_client}.py` | 実装済み + ユニットテスト完備 |
| `app/repositories/question_bank/{protocol,in_memory,pgvector_impl}.py` | 実装済み + テスト済（pgvector 実機は未） |
| `app/batch/{plan,generation_runner}.py` + `scripts/run_batch.py` | 実装済み + テスト済 |
| `workflows/generation_pipeline.yaml` + `scripts/deploy_batch.sh` | 実装済み（shell ベース、未 TF 化） |
| `app/integrations/egov_law_client.py` + `proxied_http_client.py` | 実装済み |
| `terraform/` | Phase 1 のみ（line-bot service / Firestore / Secrets / WIF）。Cloud SQL / sa-agent / sa-batch / Cloud Run Job / Workflows / Scheduler は **未** |

→ Phase 2 の残作業は **「インフラ TF 化 + 実環境結線 + 実機品質確認 + Phase 2-C の review-admin-ui 新規構築」**。

## 1. PR 単位の分割サマリ

| サブ | PR# | タイトル | 主目的 | 依存 |
|---|---|---|---|---|
| 2-A | A1 | TF: Cloud SQL Postgres + pgvector | DB 基盤 | Phase 1 TF |
| 2-A | A2 | スキーマ bootstrap スクリプト + サービス側 wiring 検証 | Cloud SQL を実利用可能に | A1 |
| 2-A | A3 | TF: sa-agent / sa-batch / 関連 IAM + API 有効化 (aiplatform / sqladmin) | バッチが本番権限で叩ける | A1 |
| 2-B | B1 | Vertex AI 利用承認確認 + 実機 smoke (Claude / Gemini / embedding) | 生成パイプを実 LLM で 1 周 | A3 |
| 2-B | B2 | TF: Cloud Run Job + Workflows + Scheduler（既存 deploy_batch.sh の TF 化） | 夜間バッチが GCP 上で稼働 | A3, B1 |
| 2-B | B3 | バッチ運用 hardening (alert / pool_low_alert→LINE Push) | 失敗・枯渇に気付ける | B2 |
| 2-C | C1 | review-admin-ui スケルトン (FastAPI + HTMX + IAP-ready) | レビュー UI の土台 | B2 |
| 2-C | C2 | レビュー API (list / approve / reject / edit) + Firestore + Cloud SQL 連携 | 実レビュー操作が可能 | C1 |
| 2-C | C3 | TF: review-admin-ui Cloud Run + IAP + sa-admin-ui | 本番公開 | C2 |
| 共通 | X1 | quiz_service ↔ question_bank 出題プール繋ぎ込み | Phase 1→2 のループ完成 | C2 |

全 10 PR。X1 は Phase 1 への影響があるため最後に分離。

## 2. 各 PR の詳細

### Sub 2-A: Cloud SQL pgvector + IAM 基盤

#### PR A1: TF Cloud SQL Postgres + pgvector
- **目的**: 重複検査用 DB を Terraform で再現可能に立てる
- **deliverable**:
  - `terraform/cloudsql.tf`: `google_sql_database_instance` (db-f1-micro, asia-northeast1, pg15)、`google_sql_database` (`question_bank`)、`google_sql_user` (`app`、Secret Manager の `driving-license-bot-cloudsql-password` を参照)
  - `terraform/secrets.tf` に `driving-license-bot-cloudsql-password` 枠を追加
  - `terraform/apis.tf` に `sqladmin.googleapis.com` を追加
  - `terraform/variables.tf` に `cloudsql_tier`, `cloudsql_disk_size_gb`, `cloudsql_deletion_protection`
  - `terraform/outputs.tf` に `cloudsql_instance_connection_name`
  - `terraform/README.md` に Cloud SQL セクション + `make teardown-app` の挙動方針追記
- **テスト**: `terraform plan`（既存 CI で plan-only）→ apply 後に `gcloud sql instances describe` で疎通
- **完了判定**: `terraform output cloudsql_instance_connection_name` 表示 / `cloudsql_password` secret に値投入手順が README にある

#### PR A2: スキーマ bootstrap + 接続検証
- **目的**: pgvector extension・テーブル・index を作り、`PgvectorQuestionBank` が実 Cloud SQL で動くことを確認
- **deliverable**:
  - `scripts/init_question_bank_schema.py`: Cloud SQL Auth Proxy 経由で `CREATE EXTENSION vector; CREATE TABLE questions(...); CREATE INDEX ivfflat ...`
  - `scripts/verify_question_bank.py`: dummy embedding を `add` → `find_similar` → `count` → cleanup の smoke
  - `Makefile` に `cloudsql-init` / `cloudsql-verify` ターゲット
  - `docs/SETUP.md` に Cloud SQL Auth Proxy 起動 + bootstrap 手順
- **完了判定**: 1 件 add → find_similar で 0.999 を返す

#### PR A3: SA + IAM + 追加 API
- **目的**: agent / batch 用の Service Account と必要 IAM を Terraform で揃える
- **deliverable**:
  - `terraform/iam.tf` に `sa-agent` / `sa-batch` / `sa-workflow` / `sa-scheduler` / `sa-cloudtasks-invoker`
  - role binding: `sa-batch` に `roles/aiplatform.user`, `roles/cloudsql.client`, `roles/secretmanager.secretAccessor`、`sa-scheduler` は `roles/workflows.invoker`、`sa-workflow` は `roles/run.developer`
  - `terraform/apis.tf` に `aiplatform.googleapis.com` / `workflows.googleapis.com` / `cloudscheduler.googleapis.com` / `cloudtasks.googleapis.com`
  - `terraform/secrets.tf` の `cloudsql_password` に `sa-batch` / `sa-agent` accessor を付与
- **完了判定**: README に SA 一覧 + 付与 role を追記、`terraform output` に SA emails

### Sub 2-B: Cloud Run Job + Workflows + Scheduler を本番化

#### PR B1: Vertex AI 実機 smoke
- **目的**: Marketplace 経由で Claude / Gemini を有効化し、`build_llm_client()` / `build_reviewer_llm_client()` / `build_embedding_client()` が本物のレスポンスを返すことを 1 度は確認
- **deliverable**:
  - `scripts/verify_vertex_models.py`: 各クライアントを `agent_llm_mock=false` で 1 回呼ぶ最小スクリプト
  - `docs/VERTEX_ENABLEMENT.md`: Claude / Gemini Marketplace 承認手順、リージョン制約、prompt caching 確認、Model Armor の Tokyo 対応
  - `docs/INFRA_DECISIONS.md §1` の残 TODO（prompt caching / Model Armor Tokyo）にチェックを付ける
- **完了判定**: Claude / Gemini / embedding それぞれ 200 OK + token 数を README に記録
- **ブロック条件**: Marketplace 承認が間に合わなければ B1 を一時スキップ → B2 まで `agent_llm_mock=true` で apply 進める道は残す

#### PR B2: TF 化 Cloud Run Job + Workflows + Scheduler
- **目的**: `scripts/deploy_batch.sh` を Terraform に正規化し、再現性 + plan 差分検知 + WIF CI に乗せる
- **deliverable**:
  - `terraform/batch.tf`: `google_cloud_run_v2_job` (`driving-license-bot-batch`)、Cloud SQL 接続は `volume_mounts` / `cloudsql_instances` で表現、`count = local.deploy_batch ? 1 : 0` で image 未指定時 skip
  - `terraform/workflows.tf`: `google_workflows_workflow` で `workflows/generation_pipeline.yaml` を埋め込み
  - `terraform/scheduler.tf`: `google_cloud_scheduler_job` (HTTP, 02:00 JST cron)
  - `terraform/variables.tf` に `batch_image`, `batch_schedule_cron`
  - `Makefile` に `image-build-batch` / `tf-apply-batch` を追加
  - `cloudbuild.yaml` を line-bot / batch 両 image を build できるよう拡張
  - 既存 `scripts/deploy_batch.sh` を deprecated 注記
- **完了判定**: 02:00 JST cron が翌朝動いた痕跡（Cloud Logging + Langfuse spans）

#### PR B3: バッチ運用 hardening
- **目的**: バッチが落ちた / プール枯渇に気付けるようにする
- **deliverable**:
  - `terraform/monitoring.tf`: alert policy（Job 失敗、`question_pool_size` 閾値割れ）
  - `app/handlers/operator_notify.py`: `pool_low_alert` を受けて運営者 LINE Push（既存 `secret operator_user_ids` を使う）
  - `app/batch/generation_runner.py` の `pool_low_alert=True` 時に operator_notify を呼ぶフック
- **完了判定**: 運営者 LINE に「プール残 N」通知が届く実機ログ

### Sub 2-C: Review Web UI

#### PR C1: review-admin-ui スケルトン
- **目的**: 別 Cloud Run service として最小起動できる土台
- **deliverable**:
  - 新ディレクトリ `review_admin_ui/`（既存 `app/` と分離。同 repo 内、別パッケージ）
    - `review_admin_ui/main.py`: FastAPI + Jinja2 + HTMX、`GET /healthz`, `GET /` (空のキュー一覧)
    - `review_admin_ui/auth.py`: IAP の `X-Goog-IAP-JWT-Assertion` 検証 + email allowlist
  - `review_admin_ui/Dockerfile`
  - `review_admin_ui/pyproject.toml`（path dep で analytics-platform、軽量に）
- **完了判定**: ローカルで起動し、空のレビュー一覧が描画される

#### PR C2: レビュー API + データ連携
- **目的**: `needs_review` 問題を実際に approve/reject/edit できる
- **deliverable**:
  - `app/repositories/question_bank/protocol.py` に `update_status` / `list_by_status` を追加
  - `review_admin_ui/routes/queue.py`: `GET /queue?status=needs_review`、`POST /questions/{id}/approve`、`POST /questions/{id}/reject` (with `reason_tag`)、`POST /questions/{id}/edit`
  - approve 時に `business_event=question_published`、reject 時に `human_review_decided`
  - **本文の格納先決定**: pgvector は dedup メタ専用に保ち、本文・解説・sources は Firestore `/questions/{id}` に集約（INFRASTRUCTURE.md §3.11 と整合）
- **完了判定**: ローカルで needs_review → published 遷移を UI 上で実行 → BigQuery に `human_review_decided` が落ちる

#### PR C3: TF 公開 (Cloud Run + IAP + sa-admin-ui)
- **目的**: 運営者 1 人が本番 URL で操作できる
- **deliverable**:
  - `terraform/admin_ui.tf`: Cloud Run service (`review-admin-ui`)、ingress=INTERNAL_AND_CLOUD_LOAD_BALANCING
  - `terraform/iap.tf`: HTTPS LB + backend service + IAP enable、`google_iap_web_iam_member` で `roles/iap.httpsResourceAccessor` を `var.review_admin_allowed_emails` に付与
  - `terraform/iam.tf` に `sa-admin-ui`
  - `docs/DEPLOY.md` に IAP brand / OAuth consent screen の手動準備手順
- **完了判定**: 運営者の Google アカウントで本番 URL にアクセス → ログイン → キュー表示 → 1 件 approve

### Sub 共通: X1 quiz_service ↔ question_bank 結線
- **目的**: published 問題を実際に LINE Bot から出題できるようにする
- **deliverable**:
  - `app/repositories/question_pool.py` に `BankBackedQuestionPool`（`QuestionPool` Protocol を満たす別実装）
  - feature flag: `QUESTION_POOL_SOURCE = seed | bank`、既定 `seed`
  - `app/services/quiz_service.py` 自体は変更なし（プール差し替えで対応）
- **完了判定**: LINE で実際に bank 由来の問題（id prefix で識別可能）が出る

### Sub 追加: Y1 GCS バックアップ / リストア（teardown-app との両立）

- **目的**: `make teardown-app` 時に Firestore（ユーザー / 回答履歴 / セッション）と
  Cloud SQL pgvector（生成済み問題）を **自動で GCS にバックアップ**、再 apply 時に
  **自動でリストア** することで「課金停止 ↔ 再開」サイクルを非破壊化する
- **背景**: 現状の teardown-app では Firestore / Cloud SQL のデータが消失。
  Phase 2-A1 README で「重複検査用 DB のため再生成可」と記したが、Phase 2-B 以降で
  生成済み問題が蓄積される + Phase 1 から既にユーザー回答履歴が蓄積されている。
  個人運用でも消失コストが大きくなったため自動バックアップを追加する
- **deliverable**:
  - `terraform/backup_bucket.tf`: 専用 GCS bucket
    `${PROJECT}-driving-license-bot-backups`（versioning 有効、lifecycle 30 日 retention）
  - `scripts/backup_data.sh`:
    - Firestore: `gcloud firestore export gs://...backups/firestore/$(date)`
    - Cloud SQL: `gcloud sql export sql ... gs://...backups/cloudsql/$(date)/dump.sql`
  - `scripts/restore_data.sh`:
    - 最新 backup を検索 → Firestore import / Cloud SQL import
    - **存在しなければ skip**（初回 apply 時の冪等性）
  - `scripts/teardown_app.sh` を修正: terraform destroy 前に backup_data.sh を実行
  - `Makefile`: `tf-apply` 後に restore のヒント表示、`make backup` / `make restore` 単独実行可
  - `terraform/iam.tf`: sa-batch / sa-line-bot に bucket 書き込み権限
  - 復旧手順は `docs/BACKUP_RESTORE.md` に整理
- **テスト**:
  - 1 件 add → backup → teardown-app → tf-apply → restore → 1 件 read で同じ data 取得
  - backup 不在時の restore が exit 0 で skip
- **完了判定**: teardown-app 後の再 apply で **回答履歴と問題プールが完全に復元** される
- **着手タイミング**: C 系列マージ後、X1 と同等優先度。**既存ユーザーの履歴を消したくない**
  ので teardown-app の本格運用開始前に必須化する候補

## 3. インフラ追加分の Terraform リソース概要

| カテゴリ | リソース | PR |
|---|---|---|
| API 有効化 | `sqladmin`, `aiplatform`, `workflows`, `cloudscheduler`, `cloudtasks`, `iap` | A1, A3, C3 |
| Cloud SQL | instance (db-f1-micro, pg15), database, user | A1 |
| Secret | `driving-license-bot-cloudsql-password` 枠 + accessor binding | A1, A3 |
| IAM | `sa-agent` / `sa-batch` / `sa-workflow` / `sa-scheduler` / `sa-cloudtasks-invoker` / `sa-admin-ui` + 各 role | A3, C3 |
| Cloud Run Job | `driving-license-bot-batch` | B2 |
| Workflows | `generation_pipeline` (yaml 埋込) | B2 |
| Scheduler | `cron 0 17 * * *` (= 02:00 JST) | B2 |
| Monitoring | alert policy 2 件 + custom metric | B3 |
| Cloud Run | `review-admin-ui` service (ingress INTERNAL_AND_LB) | C3 |
| Networking / IAP | HTTPS LB, backend, IAP brand/client | C3 |

## 4. コスト見積もり（Phase 2 完了時点 / 月額）

| 項目 | 内訳 | 月額 |
|---|---|---|
| Cloud SQL db-f1-micro + 10GB SSD | 24/7 稼働 | $10〜13 |
| Cloud Run line-bot min=1 (既存) | 既存 | $5〜10 |
| Cloud Run agent / admin-ui / batch (min=0) | リクエスト時のみ | $1〜3 |
| Cloud Run Job 実行 | 30 問/日 × 30 日 ≒ 900 問、1 問あたり 5〜10 sec → 90 分/月 | <$1 |
| Vertex AI Claude (生成) | 30 問/日 × 入力 ~6k tok (cached) + 出力 ~1k tok = 1 問あたり ~$0.02、月 ~$15〜20 | $15〜25 |
| Vertex AI Gemini (cross-check) | Pro: 1 問あたり ~$0.01、月 ~$10 | $5〜10 |
| Vertex Embedding (text-embedding-004) | 1 問あたり 1 call、$0.000025/1k chars × 1k chars × 900 = ~$0.02 | <$1 |
| Cloud Workflows / Scheduler | 月 30 起動 | <$1 |
| IAP / LB | 軽量 | $2〜5 |
| **Phase 2 合計** | | **$40〜70 / 月** |

INFRA_DECISIONS.md の目標（月数千円規模）内に収まる見込み。

## 5. リスクと先送り判断

### R1: Vertex AI Marketplace 承認が未完
- **影響**: B1 がブロック → B2 で本番バッチを Job として動かせない
- **回避**:
  - 2-A は完全に独立して進められる（Vertex 不要）
  - 2-B は B2 (TF) を `AGENT_LLM_MOCK=true` でデプロイ → 承認後に env 更新で本番化
  - C1〜C3 も独立（review UI 自体は LLM を呼ばない）
- **判断**: 承認待ち中は **A1→A2→A3→C1→C2→C3** を先行、B1 解禁後に B2/B3

### R2: 生成品質が 30 問シードに届かない
- **緩和策（既に実装側で対応）**:
  - `auto_approve_overall_score=None` 既定で「常に人間レビュー」フローに退避
  - reject reasons を `business_event=quality_review_rejected.reasons[]` に積み prompt 改善ネガティブ例として活用
  - PR B3 の pool_low_alert で枯渇前に運営者通知
- **fallback**: `app/data/seed_questions.json` から不足分を複製

### R3: Cloud SQL Auth Proxy / VPC Connector の追加コスト
- Phase 1〜2 はパブリック IP + Cloud SQL Auth Proxy で済ます
- VPC Connector は Phase 3+ に先送り（INFRASTRUCTURE.md §5 の Phase 3+ で記載済）

### R4: IAP の Brand 作成が手動
- GCP IAP brand は project に 1 度だけ手動作成（OAuth consent screen 必須）
- C3 の README で「terraform apply 前に Console で 1 step 必要」と明記

### R5: question_bank の本文をどこに置くか（C2 で決定）
- **推奨**: 本文・解説・sources は Firestore `/questions/{id}` に集約、pgvector は dedup メタ専用に保つ（INFRASTRUCTURE.md §3.11 と整合）

## 6. 既存 Phase 1 への破壊的変更

| 領域 | 変更内容 | 破壊性 |
|---|---|---|
| `app/repositories/question_bank/protocol.py` | `update_status` / `list_by_status` を追加 | 非破壊（実装追加のみ） |
| `app/services/quiz_service.py` | 変更なし | なし |
| `app/repositories/question_pool.py` | `BankBackedQuestionPool` を新規追加 | 非破壊 |
| `app/config.py` | `QUESTION_POOL_SOURCE` env 追加（既定 `seed`） | 非破壊 |
| Terraform | 新規 `.tf` 追加のみ、既存ファイルは変数追加程度 | 非破壊（teardown-app との整合は A1 / B2 で必ず確認） |
| Cloud Run line-bot service の env | C2 で `bank` に切替時に挙動変化 | 段階的切替: bank プール ≥ 100 件で切替 |

## 7. 推奨実装順序

```
A1 → A2 → A3 ──┬──→ B1 → B2 → B3
               │
               └──→ C1 → C2 → C3 → X1
```

A3 完了時点で **B 系列と C 系列は並列着手可**。Marketplace 承認の進捗で「B 先か C 先か」を切り替える。

## 8. 完了判定（Phase 2 全体の DoD）

- [ ] Cloud SQL 上で `find_similar` が < 200ms で返る
- [ ] 夜間バッチが連続 7 日間自動実行され、毎日 ≥ 10 問が `needs_review` に積まれる
- [ ] 運営者が IAP 経由で review-admin-ui にログイン → 1 日 30 問レビューできる
- [ ] LINE Bot が bank 由来の published 問題を出題でき、analytics-platform の `mart_quiz_metrics` に流れる
- [ ] BigQuery に `batch_started/completed`, `fact_check_*`, `dedup_*`, `quality_review_*`, `question_published`, `human_review_decided` の 7 種以上が日次で蓄積
- [ ] 月額 < $70 で運用できている
