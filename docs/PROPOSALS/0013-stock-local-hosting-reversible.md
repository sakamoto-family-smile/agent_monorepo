# PROPOSAL-0013: stock-analysis-agent をローカル (Mac mini) へ移行し、GCP へ戻せる状態を保つ

| | |
|---|---|
| **Status** | Draft |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-11-15 |
| **Updated** | 2026-11-15 |
| **Target** | stock-analysis-agent |
| **Related PRs** | (none yet) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

PROPOSAL-0011 で GCP (Cloud Run + Cloud Tasks + shared Cloud SQL + GCS + Pub/Sub) に
配備した stock-analysis-agent を、security-platform と同じく **Mac mini 上の Docker
Compose** で常駐させる。LINE のコマンド (`分析 X` / `おすすめ` / マイリスト等) と
Push 通知はそのまま使い続け、Cloud SQL にあるこれまでの分析レポート・マイリストは
すべてローカルの SQLite に移す。

あわせて、**ローカル ⇄ GCP をどちら向きにもすぐ切り替えられる**よう、移行スクリプト・
切替手順 (cutover) の自動化・Terraform の待機モード (standby) を用意する。GCP 側の
インフラコードは消さずに残し、定期的にリハーサルして「戻せる」ことを保証する。

## 2. Motivation

- モノレポ内でローカル常駐のもの (security-platform / hotcook / lifeplanner /
  tech-news) は Docker Compose + SQLite で運用が揃っている。stock だけ GCP の
  5 種類のサービスにまたがっており、運用・障害調査の手間が大きい。
- 利用者は家族のみで負荷は小さく、Cloud Tasks / 複数 worker / GCS 署名付き URL などの
  分散構成は過剰になっている。
- 一方で、Mac mini の故障・長期不在・回線障害などで **GCP に戻したくなる場面**は
  ありうる。一方通行の移行にすると、戻すときに構成を思い出して作り直すことになる。

### 2.1 Goals

- [ ] Mac mini 上で LINE の全コマンドと Push 通知 (チャート画像・全文レポートリンク含む) が動く
- [ ] Cloud SQL の `stock_analysis_db` の全テーブルをローカル SQLite に移し、件数・内容の一致を検証できる
- [ ] EDINET の日次 index batch (02:00 JST) と書類 cache がローカルで動く
- [ ] `make cutover-to-local` / `make cutover-to-gcp` の 1 コマンド (+確認) で切替でき、どちら向きも **停止時間 15 分以内**
- [ ] GCP 側は standby (待機) で残し、戻す手順を月 1 回程度リハーサルできる

### 2.2 Non-Goals

- 他エージェント (driving-license-bot / fujisawa-* / piyolog / kanie-lab) のローカル移行。
  本提案のスクリプトは stock 専用に作り、汎用化は需要が出てから別提案で行う
- analytics の BigQuery 相当の集計をローカルで再現すること (ローカルは JSONL + DuckDB で見る)
- ローカルの冗長化 (2 台構成・自動フェイルオーバー)。切替は手動トリガーとする
- `shared-pg` インスタンス自体の撤去 (driving-license-bot の Terraform が管理し、他 DB も同居)

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 普段の利用
> 家族が LINE で `分析 トヨタ` と送ると、Mac mini 上の backend が受けて分析し、
> 要約 Flex・チャート画像・全文リンクが届く。過去に GCP で作ったレポートもマイリストも
> そのまま残っている。

#### 3.1.2 Mac mini が使えなくなったとき
> Mac mini を修理に出すことになった。`make cutover-to-gcp` を実行すると、ローカルの
> SQLite が Cloud SQL にコピーされ、LINE の Webhook URL が Cloud Run に切り替わる。
> 戻ってきたら `make cutover-to-local` で元に戻す。

### 3.2 方針: 「動いている側 (active)」と「待機している側 (standby)」

| 状態 | ローカル | GCP |
|---|---|---|
| local active (通常) | backend 稼働、Webhook 受信、EDINET batch 実行 | リソースは残す。Scheduler は一時停止、Webhook は向いていない (Cloud Run は min=0 なのでほぼ無料) |
| gcp active (退避中) | backend 停止 (データは保持) | 現状と同じ構成で稼働 |

- データの正 (source of truth) は常に active 側の DB の 1 つだけ。切替時に「旧 active を
  止める → 新 active へコピー → 検証 → Webhook を切り替える」の順で行う。
- standby 側の DB は切替時に**上書き**する (差分マージはしない)。

### 3.3 Notes / Constraints / Caveats

- LINE の ImageMessage と全文リンクは HTTPS の公開 URL が必要。ローカルでは
  Tailscale Funnel で `/api/line` 配下だけを公開する (`/health` などは出さない)。
- ローカルの media は `MEDIA_BACKEND=memory`。再起動すると過去のリンクは 404 になる
  (GCS 版も 24 時間で失効するので実害は小さい)。TTL は 24 時間に揃える。
- SQLite に書くのは backend コンテナだけにする。EDINET batch も `docker compose exec`
  で同じコンテナ内から実行し、ホストの macOS から DB ファイルを直接書かない
  (security-platform と同じ方針。VM をまたいだ WAL 共有を避ける)。
- Cloud Tasks に残っているタスクは、GCP から切り替える前に空になるのを待つ。
- 切替中に届いたメッセージを落とさないよう、LINE の「Webhook の再送」を切替中だけ有効にする。

### 3.4 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 切替時のデータ取りこぼし (旧 active が書き込み中にコピー) | High | 旧 active を先に止めてからコピー。コピー後に全テーブルの件数 + 内容 hash を照合し、不一致なら Webhook を切り替えない |
| Postgres へ戻したとき、連番 (id の sequence) がずれて INSERT が衝突 | High | コピー後に各テーブルの sequence を `max(id)+1` に `setval` する。テストで確認 |
| Mac mini の停止 (停電・OS 更新・スリープ) | Medium | スリープ無効・停電後の自動起動・自動ログイン、`restart: unless-stopped`。外部の死活監視で通知。長期なら GCP へ切替 |
| ローカルのディスク故障でデータ消失 | High | 日次で `sqlite3 .backup` を外部ディスク / iCloud に保存 (世代管理)。月 1 で復元リハーサル |
| Funnel 公開による攻撃面の増加 | Medium | 公開は `/api/line` 配下のみ。署名検証・`FAMILY_USER_IDS`・回数制限は既存実装を維持。`APP_ENV=prod` で Web API / docs を無効化 |
| GCP 側のコードが古くなり、いざ戻すと動かない | Medium | 同じ Dockerfile を両方で使う。リハーサル (§4.5 Manual) を定期実施し、結果を Implementation History に残す |
| 秘密情報の二重管理 (local env と Secret Manager) | Medium | `secrets push/pull` スクリプトで同期。値はスクリプトの出力に表示しない |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
                ┌──────────── local active ────────────┐
LINE ──HTTPS──▶ │ tailscale (sidecar, Funnel /api/line) │
                │        │                              │
                │        ▼                              │
                │ backend (同じ Dockerfile)             │──push──▶ api.line.me
                │   ├─ data/stock_analysis.db (SQLite)  │
                │   ├─ data/edinet/ (書類 cache, csv)   │
                │   └─ data/analytics/ (JSONL)          │
                └───────────────────────────────────────┘
                   ▲ launchd: 02:00 EDINET batch / 03:00 backup

     cutover スクリプト: db_copy (SQLite ⇄ Postgres) / edinet sync (dir ⇄ GCS)
                        / secrets (env ⇄ Secret Manager) / LINE webhook 切替

                ┌──────────── gcp (standby / active) ──────────┐
                │ Cloud Run webhook + worker, Cloud Tasks,     │
                │ shared Cloud SQL, GCS media/edinet, Pub/Sub  │
                │ (Terraform は現状維持 + standby 変数)        │
                └──────────────────────────────────────────────┘
```

### 4.2 GCP の部品とローカルでの置き換え

| GCP | ローカル | 切替方法 |
|---|---|---|
| Cloud Run webhook | compose `backend` | — |
| Cloud Run worker + Cloud Tasks | なし (in-process BackgroundTasks) | `TASKS_ENABLED=false` |
| Cloud SQL `stock_analysis_db` | `data/stock_analysis.db` | `DATABASE_URL` 未設定 → `DB_PATH` |
| GCS media | インメモリ配信 | `MEDIA_BACKEND=memory`, `PUBLIC_BASE_URL=https://<host>.ts.net`, TTL 86400 |
| GCS edinet | `data/edinet/` | `EDINET_CACHE_BACKEND=local`, `EDINET_CODE_CSV_PATH=/app/data/edinet-code/Edinetcode.csv` |
| Cloud Run Job + Scheduler | launchd → `docker compose exec backend` | — |
| Pub/Sub → GCS → BigQuery | `data/analytics/` の JSONL | `ANALYTICS_STORAGE_BACKEND=local` |
| Secret Manager | `config/local.env` (600, git 管理外) | `secrets pull/push` |
| Cloud Run の公開 URL | Tailscale Funnel | LINE Webhook URL を API で切替 |

### 4.3 データモデル

スキーマの変更はない。移行対象テーブル:

| テーブル | 扱い |
|---|---|
| `reports` / `watchlist` / `ticker_dictionary` / `alerts` / `edinet_documents` | 全件コピー |
| `price_cache` | コピーしない (TTL 24h の cache。`--include-cache` で任意) |
| `alembic_version` | コピー先で `alembic upgrade head` を先に実行して揃える |

### 4.4 主要モジュール / ファイル

| パス | 内容 |
|---|---|
| `stock-analysis-agent/docker-compose.local.yml` | 本番ローカル用 compose (`backend` + `tailscale` sidecar)。`./data` を bind mount |
| `stock-analysis-agent/config/local.env.example` | ローカル本番の環境変数の雛形 (§4.2 の切替値を記載) |
| `stock-analysis-agent/config/tailscale-serve.json` | Funnel の設定 (`/api/line` → `backend:8080/api/line` のみ) |
| `stock-analysis-agent/scripts/migrate/db_copy.py` | DB コピー。`--src` / `--dst` に任意の SQLAlchemy URL。コピー先に alembic 適用 → 空であることを確認 (`--force` で truncate) → テーブル順にバッチ INSERT → Postgres なら sequence 補正 → 件数 + 行 hash 照合 |
| `stock-analysis-agent/scripts/migrate/cloudsql_proxy.sh` | cloud-sql-proxy の起動と、Secret Manager から DB パスワードを取得して `DATABASE_URL` を組み立てる補助 |
| `stock-analysis-agent/scripts/migrate/edinet_sync.sh` | `data/edinet/` ⇄ `gs://<edinet bucket>/` の `gcloud storage rsync` |
| `stock-analysis-agent/scripts/migrate/secrets.sh` | `pull`: Secret Manager → `config/local.env` / `push`: 逆向き。値は表示しない |
| `stock-analysis-agent/scripts/cutover/line_webhook.py` | LINE Messaging API で Webhook URL の取得・設定・疎通テスト (`/v2/bot/channel/webhook/endpoint`, `/v2/bot/channel/webhook/test`) |
| `stock-analysis-agent/scripts/cutover/to_local.sh` / `to_gcp.sh` | 切替手順を順に実行。各段で確認プロンプト、失敗時はそこで止まる |
| `stock-analysis-agent/scripts/local/launchd.sh` | EDINET batch (02:00) と backup (03:00) の LaunchAgent を install / uninstall / status (security-platform の `host-inventory-launchd.sh` と同じ形) |
| `stock-analysis-agent/scripts/local/backup.sh` / `restore.sh` | `sqlite3 .backup` + 世代管理 (既定 14 日)、復元 |
| `stock-analysis-agent/terraform/` | `var.standby` を追加。true で Cloud Scheduler を paused にする (他のリソースは維持) |
| `stock-analysis-agent/Makefile` | `local-up` / `local-down` / `local-logs` / `cutover-to-local` / `cutover-to-gcp` / `backup` など |

#### 切替手順 (cutover-to-local の例)

1. 事前確認: ローカル backend が `/health` OK、Funnel 経由で `/api/line/webhook` に到達できる
2. LINE の Webhook 再送を有効化 (手動。Console で切替。スクリプトは確認だけ促す)
3. GCP を止める: Cloud Tasks queue を pause → 実行中タスクが 0 になるのを待つ → webhook の `allUsers` invoker を外す
4. `db_copy.py --src <Cloud SQL> --dst sqlite:///data/stock_analysis.db --force` (照合まで)
5. `edinet_sync.sh down`
6. `line_webhook.py set https://<host>.ts.net/api/line/webhook` → `line_webhook.py test`
7. `terraform apply -var standby=true` (Scheduler 停止)
8. 家族向けに「切替完了」を Push (任意)、LINE の Webhook 再送を元に戻す

`cutover-to-gcp` はこの逆 (ローカル停止 → `terraform apply -var standby=false` → `db_copy` (sequence 補正) →
`edinet_sync up` → `secrets push` (変更があれば) → Webhook を Cloud Run URL に切替 → 疎通)。

### 4.5 Test Plan

- **Unit**:
  - `db_copy`: SQLite → SQLite の全件コピーと照合、コピー先が空でないときの拒否 / `--force`、
    `price_cache` の除外、照合不一致の検出 (行を 1 件書き換えて失敗すること)
  - `line_webhook`: LINE API をモックして set / get / test のリクエスト内容とエラー処理
  - 設定: `config/local.env.example` を読み込んだ `Settings` が SQLite・memory media・
    tasks 無効・local analytics になることを確認
- **Integration**:
  - `db_copy`: SQLite ⇄ Postgres (docker の postgres を使う。無い環境では skip)。
    往復させて内容が一致し、Postgres 側で新規 INSERT が id 衝突しないこと (sequence 補正)
  - compose: `docker-compose.local.yml` で起動し `/health` と、署名付きの擬似 Webhook が 200 になること
- **Manual / E2E** (切替のリハーサル。結果を §8 に記録):
  - [ ] Cloud SQL → ローカル: 件数一致、LINE で過去レポート参照・マイリスト表示・`分析` が動く
  - [ ] チャート画像と全文リンクが LINE で開ける (Funnel 経由)
  - [ ] EDINET batch が launchd から動き、`edinet_documents` が更新される
  - [ ] backup から別ディレクトリへ restore して起動できる
  - [ ] ローカル → GCP → ローカルの往復で、各方向の停止時間が 15 分以内

### 4.6 Migration / Rollback

- **Migration**: スキーマ変更なし。初回はリハーサルとして Cloud SQL のコピーをローカルに取り、
  動作確認後に本番の `cutover-to-local` を実施する。
- **Rollback**: GCP は standby で残しているので `cutover-to-gcp` がそのままロールバック手順になる。
  切替直後 (ローカルで新しい書き込みが無い間) は Webhook URL を戻すだけでもよい。
- **既存ユーザー影響**: 切替中の数分間は応答が遅れる (再送有効時は後から処理される)。
  Bot の友だち登録・チャネルの認証情報はそのまま。

### 4.7 Feature Enablement

- ローカル / GCP の違いはすべて環境変数で切り替える (§4.2)。アプリのコード分岐は増やさない。
- Terraform は `var.standby` (既定 false = 現状どおり) のみ追加。

---

## 5. Operational Concerns

### 5.1 Monitoring

security-platform の `src/notify/health.py` と同じく、**Mac の内側から「最後に成功した時刻」を
見る方式**にする。外部から叩ける監視用エンドポイントは追加しない。

| 監視項目 | 判定 |
|---|---|
| `backend:health` | compose 内から `/health` が応答するか |
| `funnel` | `tailscale funnel status` で `/api/line` が公開されているか |
| `edinet:index` | `edinet_documents.last_index_refreshed_at` の最大値が 26 時間以内か |
| `backup` | 最新の backup ファイルが 26 時間以内か |
| `analysis` (任意) | 直近の分析が連続で失敗していないか |

- 状態が変わったとき (異常になった / 戻った) だけ、管理者の LINE userId に Push する。家族には送らない
- Mac 自体の停止・回線断は内側の監視では検知できないため、security-platform と同じく
  **Healthchecks.io へジョブごとに ping する** (`src/common/healthcheck.py` の `make_pinger` と同じ形)。
  - `HEALTHCHECK_PING_BASE=https://hc-ping.com/<ping-key>` (security-platform と同じ Ping key を共用)
  - slug は `stock-<job>`: `stock-backend` (数分おきの生存 ping)、`stock-edinet_index`、`stock-backup`、`stock-health`
  - 成功は `<base>/stock-<job>`、失敗は `/fail` を付ける。`?create=1` で check を自動作成
  - Ping key が URL に入るため、HTTP クライアントのリクエスト URL をログに出さない
  - ping が途絶えたら Healthchecks.io 側から通知される (外向き通信のみで受け口は増えない)
- `docker compose logs backend`、`data/analytics/` の JSONL を DuckDB で集計。
- launchd ジョブのログは `data/logs/` に出す。

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| LINE の「検証」が失敗する | Funnel が無効 / tailscale sidecar 停止 / `/api/line` のパス設定違い。`tailscale funnel status` を確認 |
| チャート画像が表示されない | `PUBLIC_BASE_URL` 未設定または Funnel のホスト名と不一致。backend 再起動で memory store が消えた |
| `database is locked` | ホストから DB を直接書いていないか確認。batch は `docker compose exec` 経由で実行する |
| GCP へ戻した後に INSERT が `duplicate key` | sequence 補正が漏れている。`db_copy.py --fix-sequences-only` を実行 |

### 5.3 Dependencies

- LINE Messaging API (Push / Webhook 設定 API)
- Tailscale (Funnel、HTTPS 証明書)
- Claude Code OAuth token、Brave Search API、EDINET API
- GCP (standby 側): Cloud Run / Cloud Tasks / shared Cloud SQL / GCS / Secret Manager / Cloud Scheduler

### 5.4 Non-Functional Requirements

#### 性能
- 分析 1 件あたりの所要時間は GCP 版と同程度 (数十秒〜数分)。同時分析は 1〜2 件を想定

#### コスト
- GCP standby の費用: Cloud Run は min=0 で実質 0、Scheduler は paused、GCS / Secret は数円程度。
  `stock_analysis_db` は shared-pg 上なので追加費用なし

#### プライバシー / データ保持
- 分析レポートと LINE userId はローカルのディスクと backup 先のみに置く。backup 先は暗号化されたボリュームにする

---

## 6. Drawbacks

- 可用性は Mac mini と家庭の回線に依存し、GCP より下がる
- 切替用スクリプトと standby の維持にリハーサルの手間がかかる

## 7. Alternatives

### 案 A: ローカルも Postgres (Docker) にする
- 概要: `pg_dump` / `pg_restore` で移行し、GCP と同じ DB 製品に揃える
- 却下理由: ローカル運用の他プロジェクトはすべて SQLite で、バックアップもファイルコピーで済む。
  stock は Postgres 固有機能を使っておらず、SQLite ⇄ Postgres の往復は `db_copy` で吸収できる

### 案 B: Cloudflare Tunnel + 独自ドメイン
- 概要: 独自ドメインを取得して Cloudflare Tunnel で公開する
- 却下理由: ドメインを持っておらず、購入・管理の手間が増える。Funnel で要件 (固定 URL・HTTPS) を満たせる

### 案 C: ngrok の無料固定ドメイン
- 却下理由: ブラウザでの表示に警告ページが挟まり、全文レポートの HTML 閲覧に支障がある

### 案 D: 一方通行の移行 (GCP 側は destroy)
- 却下理由: 戻すときに構成・秘密情報・データ移行を作り直すことになる。standby の維持費はほぼ 0

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-11-15 | Draft | 初稿 |
