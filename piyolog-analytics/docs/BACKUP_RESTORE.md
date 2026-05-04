# バックアップ / リストア（Phase 4-A）

`make tf-destroy` で Cloud SQL を削除すると、ぴよログのイベントログ / 相談履歴 /
会話メッセージが消失する。これを避けるため、destroy 前に GCS にバックアップ →
再 apply 後に復元できる仕組み。

## 構成

```
GCS bucket: gs://<PROJECT>-piyolog-backups
  ├─ cloudsql/<TS>/dump.sql    # 全テーブルの SQL dump
  └─ LATEST                    # 最新 TS が書かれたテキスト 1 行
```

- versioning ON、lifecycle で current 90 日 / archived 14 日で自動削除
- `force_destroy=false` で空でない bucket は terraform destroy で残る
- 完全削除したい場合は `terraform.tfvars` に `backup_bucket_force_destroy=true` を設定

## バックアップ対象（Cloud SQL `piyolog` database 内の全テーブル）

| テーブル | 内容 |
|---|---|
| `piyolog_events` | ぴよログイベント（授乳・睡眠・排泄・体重等）|
| `import_batches` | .txt 取り込み履歴（ロールバック判定用）|
| `sessions` | LINE user 単位の現在モード（normal / consulting）|
| `conversations` | 1 つの相談セッション |
| `conversation_messages` | 各メッセージ（user / assistant / tool_use / tool_result）|

## 必要な権限

operator (`gcloud auth login` で使う Google アカウント) に以下が必要:

| 権限 | 用途 |
|---|---|
| `roles/cloudsql.admin` (or editor) | Cloud SQL export / import |
| `roles/storage.objectAdmin` on backup bucket | GCS 読み書き |

Owner 相当があれば全部含まれる。Cloud SQL service account への bucket アクセス
権限は `terraform/backup_bucket.tf` で自動付与済（手動操作不要）。

## バックアップ

```bash
make backup
```

- `gcloud sql export sql --offload`（Cloud SQL 側で実行、本番への影響を最小化）
- 完了後 `LATEST` pointer を新しい TS に更新

任意のタイミングで実行可能（リリース前のスナップショット用途等）。

## 復元

```bash
make tf-apply         # 1. インフラを再生成
make migrate          # スキーマだけ作る場合 (restore のみで十分なら不要)
make restore          # 2. 最新 backup から復元 (なければ skip)
```

- `LATEST` を読み、TS から該当の dump.sql を import
- backup が無い場合は `exit 0` で skip（初回 apply 時の冪等性）
- dump には DDL も含まれる → migration 後に restore すると衝突するので注意

> **fresh DB への restore を推奨**。`make migrate` は不要（restore で DDL 含む）。

## 運用 sequence (tf-destroy → 再構築)

```bash
# 1. destroy 前に backup
make backup
#   → bucket に新しい TS で export

# 2. インフラ削除
make tf-destroy
#   → Cloud SQL 含めてリソース削除
#   → backup bucket は force_destroy=false で残る

# 3. 再構築
make tf-apply
#   → Cloud SQL instance / DB / user (random new password) が立つ

# 4. 復元
make restore
#   → LATEST から最新 TS を読む → SQL dump を import (DDL + DML)

# 5. Cloud Run を再 deploy (image があれば)
make deploy-cloud-run
```

## 手動バックアップ（任意）

`make tf-destroy` 以外でも、たとえばリリース前のスナップショットを取りたい場合:

```bash
make backup
# → 任意のタイミングで履歴を残せる (90 日 retention)
```

## 制限事項

- **Cloud SQL export は async ではない (`--offload` は内部処理のみ)**。バッチ走行中は
  パフォーマンス影響あり
- **Postgres dump 互換性**: `gcloud sql export sql` は CREATE TABLE / INDEX を含む形で
  dump する。restore 時に既存スキーマがあると `relation "..." already exists` 等の
  DDL 衝突エラー → fresh DB への restore を推奨
- **GCS の埋め込み権限**: terraform で Cloud SQL service account に bucket への
  objectAdmin を付与しているが、初回 apply 後に service agent が created される
  までやや遅延あり。1〜2 分待ってから backup を試行
