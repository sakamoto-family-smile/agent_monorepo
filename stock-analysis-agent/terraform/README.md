# stock-analysis-agent terraform (PROPOSAL-0011 P1)

`stock-analysis-line` Cloud Run Service を `sakamomo-family-agent` に配備する。
MVP は **ephemeral SQLite**（永続化は Phase 2 で shared Cloud SQL）。Cloud SQL /
Vertex AI は使わない（LLM は Anthropic OAuth token 経由の claude-agent-sdk）。

作成リソース:
- Cloud Run Service `stock-analysis-line`（`var.image` が空なら作らない）
- Service Account `sa-stock-analysis-line` + Logging/Artifact Reader
- Secret Manager 4 件（**値は手動投入**）:
  - `stock-analysis-line-line-channel-secret`
  - `stock-analysis-line-line-channel-access-token`
  - `stock-analysis-line-claude-code-oauth-token`
  - `stock-analysis-line-brave-api-key`
- Artifact Registry repo `stock-analysis-line`

## デプロイ手順（chicken-and-egg: 基盤 → image → service）

### 0. 準備

```bash
cd stock-analysis-agent/terraform
cp terraform.tfvars.example terraform.tfvars
# project_id / 各種スペックを確認（image は空のまま）
terraform init
```

### 1. 基盤だけ作る（image="" のまま）

```bash
terraform apply   # SA / IAM / secrets(空) / Artifact Registry を作成
```

### 2. Secret 値を投入

LINE Developers Console で Messaging API チャネルを作成 → 値を取得して投入:

```bash
gcloud secrets versions add stock-analysis-line-line-channel-secret --data-file=- <<<'＜channel secret＞'
gcloud secrets versions add stock-analysis-line-line-channel-access-token --data-file=- <<<'＜channel access token＞'

# Claude OAuth token（`claude setup-token` で取得、有効期限 1 年）
gcloud secrets versions add stock-analysis-line-claude-code-oauth-token --data-file=- <<<'＜oauth token＞'

# Brave Search API key
gcloud secrets versions add stock-analysis-line-brave-api-key --data-file=- <<<'＜brave api key＞'
```

> 値はシェル履歴に残さないよう注意（`--data-file=` でファイル経由が安全）。

### 3. image を build & push

```bash
# リポジトリルートから
gcloud builds submit \
  --config=stock-analysis-agent/cloudbuild.yaml \
  --ignore-file=stock-analysis-agent/cloudbuild.gcloudignore \
  --substitutions=_SHA=$(git rev-parse --short=7 HEAD) \
  .
```

### 4. image を指定して Cloud Run Service を作る

```bash
# terraform.tfvars の image を push した tag に更新
#   image = "asia-northeast1-docker.pkg.dev/sakamomo-family-agent/stock-analysis-line/stock-analysis-line:<sha>"
terraform apply
terraform output service_url   # → https://stock-analysis-line-xxxx-an.a.run.app
```

### 5. PUBLIC_BASE_URL を反映（チャート画像 / 全文 DL に必要）

```bash
# terraform.tfvars の public_base_url に service_url を設定して再 apply
#   public_base_url = "https://stock-analysis-line-xxxx-an.a.run.app"
terraform apply
```

> `public_base_url` 未設定でも要約 Flex は届くが、チャート画像と全文 .md リンクは出ない。

### 6. LINE Webhook 登録 + allow-list

- LINE Developers Console > Messaging API > Webhook URL に
  `<service_url>/api/line/webhook` を登録し、Webhook 利用を ON。
- `terraform.tfvars` の `family_user_ids` に家族の LINE userId（`U...`）を CSV で設定 →
  `terraform apply`（**本番では必須**。未設定だと誰でも Opus 分析を叩ける）。

### 7. 疎通

LINE で `ヘルプ` → コマンド一覧、`分析 トヨタ` → ack 後に要約 Flex + チャート画像 +
「📄 全文(.md)」ボタンが届けば OK。

## analytics → Pub/Sub 入口 (PROPOSAL-0011 P2-A)

本番イベント（llm_call / tool_invocation / business_event 等）を **Pub/Sub → GCS → BQ**
で永続化する（`ANALYTICS_STORAGE_BACKEND=pubsub`）。Cloud Run env は terraform で設定済
（`analytics_pubsub_topic` / `ANALYTICS_GCP_PROJECT`）だが、**publish 権限は
analytics-platform 側で付与**する必要がある:

```bash
# 1. stock の SA email を確認
terraform output service_account_email
#   → sa-stock-analysis-line@sakamomo-family-agent.iam.gserviceaccount.com

# 2. analytics-platform/terraform/terraform.tfvars の publisher_service_account_emails に
#    上記 SA を追記して apply（events topic への roles/pubsub.publisher を付与）
cd ../../analytics-platform/terraform
#   publisher_service_account_emails = [ ..., "sa-stock-analysis-line@..." ]
terraform apply
```

> 権限付与前に pubsub backend で稼働すると publish が `7 PermissionDenied` になる。
> 不安なら一旦 `analytics_storage_backend = "local"` で deploy し、publisher 追記後に
> pubsub へ切替える。確認: BigQuery で
> `SELECT COUNT(*) FROM analytics_raw.agent_events_external WHERE service_name='stock-analysis-agent'`。

## Cloud SQL 永続化 (PROPOSAL-0011 P2-B)

`reports` / `price_cache` / `ticker_dictionary` を共有 Cloud SQL (`shared-pg`) に
永続化する。terraform が shared-pg 上に `stock_analysis_db` + `stock_analysis_user`
（password は自動生成 → Secret Manager）を作り、Cloud Run に connector + DB env を配線
する。スキーマは **alembic** が管理し、prod はコンテナ起動時に `alembic upgrade head`
を実行する（`RUN_MIGRATIONS=true` / `DB_AUTO_CREATE=false`）。

### 必須: DB/スキーマ権限の付与（apply 後 1 回）

`stock_analysis_user` は新規 DB のテーブルを作成できる必要がある（alembic が作成する）。
Postgres 15+ は `public` schema の CREATE が制限されるため、apply 後に admin で 1 回 GRANT する:

```bash
# cloud-sql-proxy で shared-pg に接続 (admin user)
cloud-sql-proxy sakamomo-family-agent:asia-northeast1:shared-pg &

psql "host=127.0.0.1 user=postgres dbname=stock_analysis_db" <<'SQL'
ALTER DATABASE stock_analysis_db OWNER TO stock_analysis_user;
GRANT ALL ON SCHEMA public TO stock_analysis_user;
ALTER SCHEMA public OWNER TO stock_analysis_user;
SQL
```

> これを忘れると起動時の `alembic upgrade head` が `permission denied for schema public`
> で失敗する。

### 確認

```bash
# 起動ログに alembic upgrade のログ + init_db seed
gcloud run services logs read stock-analysis-line --region=asia-northeast1 --limit=50

# LINE で `分析 トヨタ` 後、reports が増えるか
psql "host=127.0.0.1 user=stock_analysis_user dbname=stock_analysis_db" \
  -c "SELECT ticker, created_at FROM reports ORDER BY created_at DESC LIMIT 5;"
```

> 再起動で履歴が消えなくなる（P1 の ephemeral SQLite から脱却）。ローカル/dev は
> `DB_AUTO_CREATE=true`（既定）で SQLite に create_all + seed され、alembic は任意。

## Cloud Tasks 分散非同期 + GCS media (PROPOSAL-0011 P3-A)

分析を webhook の in-process BackgroundTasks から **Cloud Tasks + 別 worker run** に
委譲する。これで複数依頼の流量制御・自動リトライ・タスク永続化が入り、webhook /
worker とも **min_instances=0** にできる。

`terraform apply`（image 指定済）で以下が**1回で**作られる（worker URL は terraform が
webhook env に自動配線）:

- Cloud Tasks queue `stock-analysis`（`tasks_max_concurrent_dispatches` で並列度制御）
- worker Cloud Run `stock-analysis-worker`（webhook と同一イメージ、public、min=0）
- media 配信用 GCS バケット `stock-analysis-line-media`（public read / 1 日で自動削除）
- invoker SA `sa-stock-tasks-invoker`（Cloud Tasks→worker の OIDC identity）

構成:

```
LINE → webhook(/api/line/webhook, min=0) → Cloud Tasks queue
          → OIDC POST → worker(/api/tasks/analyze, min=0)
              → 分析 → チャート/全文を GCS へ → LINE Push (画像/全文URLはGCS)
```

- worker は media を LINE が取得するため public。`/api/tasks/analyze` は app 内で
  Cloud Tasks の OIDC token（invoker SA）を検証して保護する。
- スキーマ migration は webhook 側のみ（`RUN_MIGRATIONS=true`）。worker は false。
  タスクは webhook 経由でしか生まれないため、migration 実行順は自然に満たされる。
- 並列度を上げたいときは `worker_max_instances` と `tasks_max_concurrent_dispatches`
  を揃えて増やす。

### 確認

```bash
terraform output worker_url tasks_queue media_bucket
# LINE で `分析 トヨタ` → ack 即返し → 数十秒〜数分後にチャート画像 + 全文リンクが届く
gcloud run services logs read stock-analysis-worker --region=asia-northeast1 --limit=50
```

> 失敗タスクは Cloud Tasks が自動リトライ（`tasks_max_attempts`）。試行を使い切ると
> worker がユーザにエラー通知して ack する。

## 更新（image 入れ替え）

```bash
gcloud builds submit --config=stock-analysis-agent/cloudbuild.yaml \
  --ignore-file=stock-analysis-agent/cloudbuild.gcloudignore \
  --substitutions=_SHA=$(git rev-parse --short=7 HEAD) .
gcloud run services update stock-analysis-line --region=asia-northeast1 \
  --image=asia-northeast1-docker.pkg.dev/sakamomo-family-agent/stock-analysis-line/stock-analysis-line:<sha>
```

terraform は `image` の drift を無視する（`ignore_changes`）ので、上記 `gcloud run
services update` 直叩きで OK。
