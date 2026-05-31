# fujisawa-info-bot deploy runbook (Phase 7)

Cloud Run Service + LINE Messaging API Channel の **本番デプロイ手順**。
ローカル開発手順は [`../README.md`](../README.md) を参照。

---

## 1. 前提

| ツール | バージョン | 備考 |
|---|---|---|
| gcloud CLI | 最新 | `gcloud auth login` + `gcloud auth application-default login` 済 |
| terraform | >= 1.7 | provider google >= 5.45 |
| docker | (任意) | 直接 build しない場合は不要、 Cloud Build で代替可能 |

- GCP project: `sakamomo-family-agent` (or 任意)
- fujisawa-platform が同 project にデプロイ済 (共有 Cloud SQL `shared-pg` 上の `fujisawa_kb_db` に `pages` テーブルが存在する状態)
- weekly_crawl が 1 回以上完走済 (pages に row が入っている状態)

---

## 2. 初回 apply (リソース基盤を作る)

terraform.tfvars を作成:

```bash
cd fujisawa-info-bot/terraform
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
```

`image = ""` のまま **基盤リソースだけ作る** (Cloud Run Service はこの時点では作らない):

```bash
terraform init
terraform plan -out=initial.tfplan
terraform apply initial.tfplan
```

これで以下が作成される:
- Service Account (`sa-fujisawa-info-bot@...`)
- IAM bindings (Cloud SQL Client / Vertex AI User / Secret Accessor 等)
- Secret Manager リソース (LINE 値は次節で投入)
- Artifact Registry repo (`fujisawa-info-bot`)
- Cloud SQL user (`fujisawa_info_bot_user` + 自動生成 password)

---

## 3. Cloud SQL に consumer 権限を流す (1 回)

terraform は user を作るだけで、 `GRANT` は別途 psql で流す (proposal 0003 §4.5.3 の責任分離):

```bash
# Cloud SQL Auth Proxy 経由で接続
cloud-sql-proxy sakamomo-family-agent:asia-northeast1:shared-pg &

# pages テーブルに SELECT 権限を付与
psql "host=127.0.0.1 user=postgres dbname=fujisawa_kb_db" \
  -c "GRANT SELECT ON pages TO fujisawa_info_bot_user;"

# (将来) consumer_role を使う場合
# psql ... -c "GRANT consumer_role TO fujisawa_info_bot_user;"
```

> 注意: pgvector extension は driving-license-bot Phase 1 / fujisawa-platform で
> 既に有効化済のはずだが、 万が一未有効なら
> `CREATE EXTENSION IF NOT EXISTS vector;` を流す。

---

## 4. LINE Channel を作成して secret に投入

### 4.1 LINE Developer Console で Channel 作成

1. <https://developers.line.biz/console/> にアクセス
2. Provider を作成 (or 既存を選択)
3. **Messaging API Channel** を作成 (Channel 名: `fujisawa-info-bot` 等)
4. 「Channel basic settings」 から **Channel secret** を copy
5. 「Messaging API settings」 から **Channel access token (long-lived)** を発行 → copy

### 4.2 Secret Manager に投入

```bash
# Channel secret
echo -n "<channel-secret-value>" | \
  gcloud secrets versions add fujisawa-info-bot-line-channel-secret --data-file=-

# Channel access token
echo -n "<channel-access-token-value>" | \
  gcloud secrets versions add fujisawa-info-bot-line-channel-access-token --data-file=-
```

---

## 5. Cloud Build で image を push

```bash
# リポジトリルートから (path dep のため context は root)
cd /path/to/agent_monorepo
SHA=$(git rev-parse --short=7 HEAD)
gcloud builds submit \
  --config=fujisawa-info-bot/cloudbuild.yaml \
  --ignore-file=fujisawa-info-bot/cloudbuild.gcloudignore \
  --substitutions=_SHA=${SHA} \
  .
```

出力される image URI:
```
asia-northeast1-docker.pkg.dev/sakamomo-family-agent/fujisawa-info-bot/fujisawa-info-bot:<SHA>
```

---

## 6. 2 回目 apply (Cloud Run Service を deploy)

`terraform.tfvars` の `image` を先ほどの URI に書き換える:

```bash
$EDITOR fujisawa-info-bot/terraform/terraform.tfvars
# image = "asia-northeast1-docker.pkg.dev/.../fujisawa-info-bot:<SHA>"

cd fujisawa-info-bot/terraform
terraform plan -out=deploy.tfplan
terraform apply deploy.tfplan
```

`terraform output service_url` で Cloud Run URL を取得:
```
https://fujisawa-info-bot-xxxxx-an.a.run.app
```

---

## 7. LINE webhook URL を登録

LINE Developer Console > Messaging API settings > Webhook settings:

- **Webhook URL**: `<service_url>/webhook`
  - 例: `https://fujisawa-info-bot-xxxxx-an.a.run.app/webhook`
- **Use webhook**: ON
- 「Verify」 ボタンで疎通確認 (200 が返るはず)

---

## 8. 動作確認

1. LINE アプリで自分の Bot を友だち追加
2. 質問を送る (例: 「ゴミの日はいつ？」)
3. 出典 URL 付きで返事が来ることを確認

ログ確認:
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="fujisawa-info-bot"' \
  --limit 20 --freshness=10m
```

---

## 9. image 更新の運用 (CI/CD 化前の手動)

コード変更後の deploy フロー:

```bash
SHA=$(git rev-parse --short=7 HEAD)

# 1. Cloud Build で新 image を push
gcloud builds submit \
  --config=fujisawa-info-bot/cloudbuild.yaml \
  --ignore-file=fujisawa-info-bot/cloudbuild.gcloudignore \
  --substitutions=_SHA=${SHA} .

# 2. Cloud Run Service の image だけ差し替え (terraform は image ignore_changes)
gcloud run services update fujisawa-info-bot \
  --region=asia-northeast1 \
  --image=asia-northeast1-docker.pkg.dev/sakamomo-family-agent/fujisawa-info-bot/fujisawa-info-bot:${SHA}
```

---

## 10. fujisawa-platform 側で GCS bucket viewer を付与 (任意)

将来 PDF アーカイブ参照する場合のみ。 fujisawa-platform/terraform/terraform.tfvars に:

```hcl
consumer_service_account_emails = [
  "sa-fujisawa-info-bot@sakamomo-family-agent.iam.gserviceaccount.com",
]
```

を追加して `terraform apply`。 Phase 7 範囲では不要 (RAG は pages テーブルのみ参照)。

---

## トラブルシューティング

| 症状 | 原因 / 対処 |
|---|---|
| Cloud Run startup で 503 | LINE secrets が未投入 → §4.2 を実行 |
| webhook で 401 | LINE Channel secret 値の不一致 → §4.1 で再取得して投入 |
| `psycopg.OperationalError: connection failed` | Cloud SQL connector が動いていない or consumer user の GRANT 未実行 → §3 確認 |
| Vertex AI 401/403 | SA に `aiplatform.user` 権限が無い → terraform apply で iam.tf を反映 |
| LINE Verify で 200 が返らない | webhook URL の末尾 `/webhook` 抜け、 もしくは Cloud Run 公開設定 (allUsers invoker) 未反映 |
