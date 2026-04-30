# バックアップ / リストア（Phase 2-Y1）

`make teardown-app` で Cloud SQL pgvector の問題プールや Firestore のユーザー回答履歴が
消失するのを避けるため、teardown 前に GCS へバックアップ → 再 apply 後に
復元できる仕組み。

## 構成

```
GCS bucket: gs://<PROJECT>-driving-license-bot-backups
  ├─ firestore/<TS>/                 # Firestore export (default database)
  │     <TS>.overall_export_metadata
  │     all_namespaces/...
  ├─ cloudsql/<TS>/dump.sql          # gcloud sql export (pg_dump 互換)
  └─ LATEST                          # 最新 TS が書かれたテキスト 1 行
```

- versioning ON、lifecycle で current 90 日 / archived 14 日で自動削除
- `force_destroy=false` で空でない bucket は terraform destroy で残る
- `make teardown` でも bucket は残る（完全削除したい場合は
  `terraform.tfvars` に `backup_bucket_force_destroy=true` を設定して再 apply）

## 必要な権限

operator (`gcloud auth login` で使う Google アカウント) に以下が必要:

| 権限 | 用途 |
|---|---|
| `roles/datastore.importExportAdmin` | Firestore export / import |
| `roles/cloudsql.admin` (or editor) | Cloud SQL export / import |
| `roles/storage.objectAdmin` on backup bucket | GCS 読み書き |

Owner 相当があれば全部含まれる。Cloud SQL / Firestore service agent への
bucket アクセス権限は terraform/backup_bucket.tf で自動付与済（手動操作不要）。

## バックアップ

```bash
make backup
```

- `gcloud firestore export` (asynchronous、サーバー側で完了)
- `gcloud sql export sql --offload` (Cloud SQL 側で実行、本番への影響を最小化)
- 完了後 `LATEST` pointer を新しい TS に更新

`make teardown-app` の最初のステップとして自動実行される（取れなかった場合は
ユーザー確認を求めて中断可）。

## 復元

```bash
make tf-apply         # 1. インフラを再生成
make restore          # 2. 最新 backup から復元 (なければ skip)
```

- `LATEST` を読み、TS から該当の export を探して import
- backup が無い場合は `exit 0` で skip（初回 apply 時の冪等性）
- Firestore は `import` で全 namespace 上書き、Cloud SQL は SQL dump 実行

> Cloud SQL restore 注意: `make cloudsql-init` を先に走らせると DDL 衝突する可能性。
> 復元シナリオでは init をスキップし、`restore` のみ実行する（dump に DDL が含まれるため）。

## 運用 sequence (teardown → 再構築)

```bash
# 1. destroy 前に backup (teardown_app.sh が自動で呼ぶ)
make teardown-app
#   → backup_data.sh が走る → bucket に新しい TS で export
#   → terraform destroy で line-bot / Cloud SQL 等が消える
#   → backup bucket は force_destroy=false で残る

# 2. 再構築
make tf-apply
#   → 新しい Cloud SQL instance / app user (random new password) が立つ

# 3. 復元
make restore
#   → LATEST から最新 TS を読む
#   → Firestore に import (default database に流し込む)
#   → Cloud SQL に dump を import (テーブル定義 + データ)

# 4. line-bot を再起動 (必要なら)
make image-build
make tf-apply  # line_bot_image を埋めて
```

## 手動バックアップ (任意)

`teardown-app` 以外でも、たとえばリリース前のスナップショットを取りたい場合:

```bash
make backup
# → 任意のタイミングで履歴を残せる (90 日 retention)
```

## 制限事項

- **Firestore import は default database に対して行う**。Database が空なら問題なし、
  既存データがあると ID 重複時に上書きされる
- **Cloud SQL export は async ではない (offload は内部処理のみ)**。バッチ走行中は
  パフォーマンス影響あり
- **pgvector extension の dump 互換性**: `gcloud sql export sql` は CREATE EXTENSION
  を含む形で dump する。restore 時に extension が無くてもインスタンス内で自動作成される
- **GCS の埋め込み権限**: terraform で Firestore service agent (`service-...@gcp-sa-firestore`)
  と Cloud SQL service account に bucket への objectAdmin を付与しているが、初回 apply 後に
  service agent が created されるまで遅延あり。1〜2 分待ってから backup を試行
