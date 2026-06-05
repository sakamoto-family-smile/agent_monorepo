# PROPOSAL-0009 P1: `shared-pg` 集約マイグレーション手順書（案②: 完全準拠）

| | |
|---|---|
| **対象** | PROPOSAL-0009 P1（Cloud SQL 2台 → 1台集約 + `shared-pg` 改名） |
| **作成** | 2026-06-05 |
| **方針** | 案②（proposal 完全準拠）: 共有インスタンスを `driving-license-bot-pg` → `shared-pg` に改名し、3 DB を新インスタンスへ集約、旧2台を撤去 |
| **状態** | **実行完了（2026-06-05 メンテ）**。shared-pg に 3DB 集約・検証 OK。旧 driving-license-bot-pg 削除 / 旧 piyolog stop 保持。詳細は proposal §8 |

> ⚠️ **これは破壊的・有ダウンタイムの本番移行**。Cloud SQL は instance 名を後から変えられないため、
> 改名は「**旧インスタンス destroy → 新名称で create**」＝ 稼働中インスタンス（pgvector を含む）の作り直し。
> 移行中は driving-license-bot / fujisawa 2系 / piyolog の DB 接続が一時断する。

---

## 0. 確定済みの実環境ファクト（2026-06-05 時点、read-only 確認済み）

| 項目 | 値 |
|---|---|
| PROJECT | `sakamomo-family-agent` |
| REGION | `asia-northeast1` |
| 旧インスタンス #1 | `driving-license-bot-pg`（db-f1-micro / public IP / deletion_protection=**false** / backup=on / PITR=off） |
| └ DB | `question_bank`（driving-license）, `fujisawa_kb_db`（**pgvector**） |
| └ user | `app`, `fujisawa_etl_user`, `fujisawa_info_bot_user`, `postgres` |
| 旧インスタンス #2 | `piyolog`（db-f1-micro / public IP / deletion_protection=**false** / backup=on） |
| └ DB | `piyolog` |
| └ user | `piyolog`, `postgres` |
| 新インスタンス | `shared-pg`（**db-g1-small** / autoresize+limit / deletion_protection は移行後 true 化推奨） |
| backup bucket（driving/fujisawa） | `gs://sakamomo-family-agent-driving-license-bot-backups` |
| backup bucket（piyolog） | `gs://sakamomo-family-agent-piyolog-backups` |
| 影響 Cloud Run サービス | `driving-license-bot-line-bot`, `driving-license-bot-admin-ui`, `fujisawa-info-bot`, `piyolog-analytics` |
| 影響 Cloud Run Jobs | fujisawa-platform ETL（`fujisawa_kb_db` へ upsert） |

> connection name は改名で `sakamomo-family-agent:asia-northeast1:driving-license-bot-pg`
> → `sakamomo-family-agent:asia-northeast1:shared-pg` に変わる。全 consumer の再 apply / 再デプロイが必須。

---

## 1. 事前準備（メンテ前日まで）

- [ ] メンテ時間帯を確定（低トラフィック帯）。LINE 連携サービスは即時 200 を返すが処理は失敗し得るので告知/許容を確認。
- [ ] 全 terraform module の `terraform.tfvars`（未コミット）が `shared-pg` を指す値になっているか確認:
  - driving-license-bot: `cloudsql_instance_name = "shared-pg"`, `cloudsql_tier = "db-g1-small"`, `cloudsql_max_connections = 100`
  - fujisawa-platform / fujisawa-info-bot: `shared_cloudsql_instance_name = "shared-pg"`,
    `shared_cloudsql_instance_connection_name = "sakamomo-family-agent:asia-northeast1:shared-pg"`
  - piyolog-analytics: `cloud_sql_use_shared_instance = true`, `shared_cloudsql_instance_name = "shared-pg"`
- [ ] 各 module で `terraform plan` を取り、**destroy/create 対象を必ず目視**（特に driving-license-bot で
      「`driving-license-bot-pg` destroy → `shared-pg` create」、piyolog で「専用インスタンス destroy」）。
- [ ] pgvector の対象テーブル/拡張が dump に含まれることを確認（`fujisawa_kb_db`）。
- [ ] `gcloud config set project sakamomo-family-agent` を確認。

```bash
export PROJECT=sakamomo-family-agent
export REGION=asia-northeast1
export STAMP=$(date +%Y%m%d-%H%M)
export DLB_BUCKET=gs://sakamomo-family-agent-driving-license-bot-backups
export PIYO_BUCKET=gs://sakamomo-family-agent-piyolog-backups
```

---

## 2. バックアップ（最重要・ロールバックの生命線）

> 案②では旧インスタンスを **terraform が destroy** するため、ロールバックは原則「バックアップからの復元」。
> （旧インスタンスを stop で残す安全策は §6.2 参照。残す場合はこの章の後に state 操作を行う。）

```bash
# 2-1. オンデマンドバックアップ（インスタンス丸ごと、念のため二重化）
gcloud sql backups create --instance=driving-license-bot-pg --project=$PROJECT
gcloud sql backups create --instance=piyolog --project=$PROJECT

# 2-2. 論理ダンプ（DB 単位）を GCS へ export
#   export 用 SA に bucket への objectAdmin が要る（Cloud SQL の service account に付与済みか確認）
for db in question_bank fujisawa_kb_db; do
  gcloud sql export sql driving-license-bot-pg \
    "$DLB_BUCKET/migrate/${db}_${STAMP}.sql" --database="$db" --project=$PROJECT
done
gcloud sql export sql piyolog \
  "$PIYO_BUCKET/migrate/piyolog_${STAMP}.sql" --database=piyolog --project=$PROJECT

# 2-3. export 成果物を確認
gcloud storage ls -l "$DLB_BUCKET/migrate/" "$PIYO_BUCKET/migrate/"
```

- [ ] 3 つの dump（question_bank / fujisawa_kb_db / piyolog）が生成されたことを確認。
- [ ] 可能なら手元にも `gcloud storage cp` で1部退避。

---

## 3. 移行実行（terraform apply + データ import）

> 順序が重要。**インスタンス作成 → DB/user 作成（terraform）→ データ import** の順にする
> （import 時に owner role が存在している必要があるため）。

### 3-1. 共有インスタンス本体を作成（driving-license-bot module）

```bash
cd driving-license-bot/terraform
terraform plan    # 「driving-license-bot-pg destroy / shared-pg create」「question_bank,app 再作成」を目視
terraform apply   # ここで旧 driving-license-bot-pg は破棄される（fujisawa_kb_db データも消える=2章で退避済）
```

この時点で `shared-pg`（db-g1-small）が作成され、`question_bank` DB と `app` user は **空** で再作成される。
fujisawa_kb_db / piyolog はまだ無い。

### 3-2. consumer の DB/user を `shared-pg` 上に再作成（fujisawa 2系）

```bash
cd ../../fujisawa-platform/terraform
terraform plan    # fujisawa_kb_db / fujisawa_etl_user が shared-pg 上に create されることを確認
terraform apply

cd ../../fujisawa-info-bot/terraform
terraform plan    # fujisawa_info_bot_user が shared-pg 上に create されることを確認
terraform apply
```

### 3-3. データ import（question_bank / fujisawa_kb_db）

```bash
# question_bank
gcloud sql import sql shared-pg \
  "$DLB_BUCKET/migrate/question_bank_${STAMP}.sql" --database=question_bank --project=$PROJECT

# fujisawa_kb_db（pgvector）。dump に CREATE EXTENSION vector が含まれる前提。
# 含まれない場合は import 前に手動で拡張作成:
#   gcloud sql connect shared-pg --user=postgres --database=fujisawa_kb_db
#   => CREATE EXTENSION IF NOT EXISTS vector;
gcloud sql import sql shared-pg \
  "$DLB_BUCKET/migrate/fujisawa_kb_db_${STAMP}.sql" --database=fujisawa_kb_db --project=$PROJECT
```

- [ ] import 後、pgvector 検索が効く（拡張・index・データ件数）を psql で確認。

### 3-4. piyolog を集約（piyolog module）

```bash
cd ../../piyolog-analytics/terraform

# count 化に伴う state アドレス移動（専用インスタンスが piyolog -> piyolog[0] になる）
terraform state mv 'google_sql_database_instance.piyolog' 'google_sql_database_instance.piyolog[0]' || true

terraform plan    # 「piyolog[0] destroy」「shared-pg に piyolog DB/user create」を目視
terraform apply   # 旧 piyolog インスタンス破棄、shared-pg に piyolog DB/user 作成

# piyolog データ import
gcloud sql import sql shared-pg \
  "$PIYO_BUCKET/migrate/piyolog_${STAMP}.sql" --database=piyolog --project=$PROJECT
```

---

## 4. 再デプロイ & 動作確認

接続先（connection name / DATABASE_URL）が `shared-pg` 向けに変わるため、全サービスを再デプロイする。

```bash
# 各 module の deploy 手順に従う（例）
#   driving-license-bot: terraform 経由で Cloud Run 更新 or scripts/deploy
#   fujisawa-info-bot / piyolog-analytics: scripts/deploy_cloud_run.sh
#   fujisawa-platform ETL: Job の再デプロイ
```

確認チェック（proposal §4.5 E2E）:

- [ ] driving-license-bot: LINE webhook 応答、pgvector 重複検査が動作
- [ ] fujisawa-platform ETL Job が `shared-pg` の `fujisawa_kb_db` に upsert 成功
- [ ] fujisawa-info-bot: `fujisawa_kb_db` への SELECT 系が成功
- [ ] piyolog-analytics: LINE で `.txt` 取込 → サマリ表示成功
- [ ] Cloud Monitoring で `shared-pg` の CPU/メモリ/接続数が想定内（飽和なし）

---

## 5. 仕上げ（移行成功の確定）

- [ ] `shared-pg` の `deletion_protection = true` を tfvars で有効化して apply（誤削除防止）。
- [ ] `shared-pg` の自動バックアップ + PITR 設定を確認/有効化。
- [ ] 1〜2 週間問題が無いことを確認したら、（旧インスタンスを §6.2 で stop 保持していた場合は）削除。
- [ ] ローカル開発設定の旧名参照を更新:
  - `.claude/settings.local.json` / `driving-license-bot/.claude/settings.local.json` の
    cloud-sql-proxy 対象を `driving-license-bot-pg` → `shared-pg` に変更（ローカル設定・gitignore 対象）。
- [ ] piyolog terraform の `TODO(PROPOSAL-0009 P1)`（専用インスタンス用変数の簡約）を別 PR で整理。
- [ ] PROPOSAL-0009 §8 Implementation History に移行完了を追記。

---

## 6. ロールバック

### 6.1 標準（バックアップ復元ベース）

切替後に問題が出た場合:

1. consumer の tfvars を旧名へ戻す（`cloudsql_instance_name`/`shared_cloudsql_instance_name` を
   `driving-license-bot-pg` に、piyolog は `cloud_sql_use_shared_instance=false`）。
2. ただし旧インスタンスは destroy 済のため、まず旧インスタンスを再作成（terraform apply）し、
   §2 の dump から `gcloud sql import sql` で復元 → 再デプロイ。
3. これは時間がかかるため、**切替直後の動作確認を厚くして「戻さない」体制が望ましい**。

### 6.2 安全策（旧インスタンスを stop で残す変種・推奨オプション）

破棄を避けてロールバックを軽くしたい場合、§3-1 / §3-4 の apply 前に、旧インスタンスを
terraform 管理から外して GCP 上に残す:

```bash
# driving-license-bot: 旧インスタンスを state から除外（GCP 上には残る）
cd driving-license-bot/terraform
terraform state rm google_sql_database_instance.main
#   → 同 module 内の google_sql_database / google_sql_user（question_bank, app）も
#     旧インスタンス参照のため、合わせて state rm するか、計画を精査して再作成扱いにする。
#   → その後 apply で shared-pg を「新規 create」として作成（destroy は発生しない）。
# 移行・検証完了後に旧インスタンスを停止:
gcloud sql instances patch driving-license-bot-pg --activation-policy=NEVER --project=$PROJECT
# 問題なければ後日削除:
# gcloud sql instances delete driving-license-bot-pg --project=$PROJECT
```

> ⚠️ `state rm` 方式は state とリソースの対応を手作業で整える必要があり、誤るとドリフトの原因になる。
> 実施するなら plan 差分を1行ずつ確認すること。piyolog 側も同様に `piyolog[0]` を残す場合は同手順。

---

## 7. リスクチェックリスト（実行前最終確認）

- [ ] 3 DB の dump が GCS にあり、サイズが 0 でない
- [ ] オンデマンドバックアップが両インスタンスで成功している
- [ ] driving-license-bot の plan が「shared-pg create / 旧 destroy（or §6.2 で残す）」になっている
- [ ] fujisawa 2系・piyolog の plan が shared-pg 上の DB/user create になっている
- [ ] import 前に各 owner role（app / fujisawa_etl_user / fujisawa_info_bot_user / piyolog）が
      shared-pg 上に存在する（= 各 module apply 済）
- [ ] pgvector 拡張が `fujisawa_kb_db` に作成される（dump 内 or 手動）
- [ ] メンテ時間帯で、接続断が許容される

---

## 8. 補足：本手順に含めない P2 以降

- **public IP のハードニング / Private IP 化（P2）** は本移行に含めない（コスト目的では割に合わないと proposal が結論）。
  まず authorized networks 全廃 + SSL 必須 + IAM DB 認証で安全性確保、Private IP は将来判断。
- AR cleanup（P3）/ region 整理（P4）/ LLM 最適化（P5）/ min instances（P6）は独立 PR。
