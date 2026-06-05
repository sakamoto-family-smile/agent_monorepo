# PROPOSAL-0009: GCP コスト最適化（Cloud SQL 集約ほか）

| | |
|---|---|
| **Status** | Implementing |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-05-30 |
| **Updated** | 2026-05-31 |
| **Target** | cross-agent (GCP インフラ全体) |
| **Related PRs** | P1: piyolog Cloud SQL 集約 (本ブランチ) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

モノレポの GCP 構成は Cloud Run / Cloud Run Jobs が **scale-to-zero**（min instances 既定 0）で、
アイドル課金がほぼ無い良い設計になっている。一方で **24時間課金され続ける数少ない常時稼働リソースが
Cloud SQL** であり、現在 **2 インスタンス**（`driving-license-bot-pg` と `piyolog`）が個別に稼働している。

本提案は、(1) Cloud SQL を **2台 → 1台に集約**し、(2) public IPv4 廃止・Artifact Registry クリーンアップ・
リージョン整理・LLM 呼び出し最適化など複数の低リスク施策を併せて実施し、**固定費を月 $15〜30 程度削減**
することを目的とする。各施策は独立した PR に分割できるよう優先度と依存関係を整理する。

## 2. Motivation

個人運営のモノレポであり、固定費（特にアイドル時も課金されるリソース）を抑えることが運営継続性に
直結する。現状把握として、Terraform から以下を確認した。

| 項目 | 実態（Terraform 由来） |
|---|---|
| Cloud SQL #1 | `driving-license-bot-pg`：db-f1-micro / 10GB PD_SSD / ZONAL / autoresize=false / **public IP** |
| Cloud SQL #2 | `piyolog`：db-f1-micro / 10GB PD_SSD / autoresize=true / **public IP** |
| 既存の共有状況 | `fujisawa-platform` / `fujisawa-info-bot` は **既に `driving-license-bot-pg` に相乗り**（`fujisawa_kb_db`） |
| Cloud Run min instances | 大半が既定 0。例外は `driving-license-bot` の `line_bot_min_instances=1`（常時 1 起動） |
| GCS ライフサイクル | analytics / backup / fujisawa の主要バケットは **設定済** |
| Artifact Registry cleanup | **全システムで未設定**（イメージ世代が無制限に蓄積） |
| リージョン | agent 群は `asia-northeast1`、**analytics-platform のみ `us-central1`**（クロスリージョン） |
| LLM | driving-license は `gemini-2.5-pro` + `claude-sonnet` の **cross-check（2モデル実行）** |

放置すると、Cloud SQL 2台＋public IP の固定費が継続的に発生し、Artifact Registry のイメージ蓄積と
クロスリージョン egress がじわじわ増える。

### 2.1 Goals

- [ ] Cloud SQL インスタンスを **2 → 1** に集約する（DB / ユーザーの論理分離は維持）
- [ ] 固定費（Cloud SQL ベース + IPv4 + AR ストレージ + cross-region egress）を **月 $15〜30 削減**
- [ ] 各施策を **独立した PR** に分割し、リスクの低い順に段階適用できる状態にする
- [ ] 変動費（Vertex AI）の削減方針を `llm-client` 集約点で 1 箇所変更できる形で示す
- [ ] 削減施策ごとに **ロールバック手順**を明記する

### 2.2 Non-Goals

- マルチリージョン HA / 高可用構成への変更（個人運営では過剰、本提案はむしろ単純化方向）
- Cloud SQL から他DB（AlloyDB 等）への移行（より高額になるため対象外）
- アプリケーションのスキーマ大改修（集約は instance 同居であり、スキーマは原則そのまま）
- 全ノードを網羅した詳細コスト会計（GCP の Billing/BigQuery export での実測は別途）

---

## 3. Proposal

固定費インパクトと実装リスクで優先度を付け、独立適用可能な施策群として提案する。

| # | 施策 | 効果（概算） | 労力 | リスク | 依存 |
|---|---|---|---|---|---|
| P1 | **Cloud SQL 集約**（`piyolog` → 共有インスタンス） | 〜$10/月（micro 1台分）+ IPv4 $3/月 | 中 | 中 | — |
| P2 | **Cloud SQL public IP 廃止**（Private IP）または **public IP のハードニング** | IPv4 $3/月 × 台。ただし VPC Connector 採用時はそれを上回る場合あり | 中 | 中 | P1 後が楽 |
| P3 | **Artifact Registry cleanup policy**（untagged 削除 / 最新 N 世代保持） | ストレージ漸減 | 小 | 低 | — |
| P4 | **analytics-platform を asia-northeast1 へ寄せる** | cross-region egress 削減 + レイテンシ | 中 | 中 | — |
| P5 | **Vertex AI 最適化**（cross-check サンプリング / Gemini Flash ルーティング） | 変動費（最大インパクト） | 小〜中 | 低〜中 | — |
| P6 | **`line_bot_min_instances` 見直し**（1 → 0 の是非） | idle Cloud Run 1台分 | 小 | 中（UX） | — |

> P1〜P4 が固定費、P5〜P6 が変動費/トレードオフ系。**P3 が最も低リスク**なので着手しやすい。

#### P2 補足：public → private IP のリスクとトレードオフ

レビュー指摘（"public から private にするリスクは？"）への回答。**P2 は単純な改善ではなく、
コスト最適化の文脈ではむしろ慎重に判断すべき施策**である。

- **接続経路が変わる（最大のリスク）**: Cloud Run / Cloud Run Jobs から private-IP の Cloud SQL に
  到達するには **Serverless VPC Access Connector** または **Direct VPC egress** が必要になる。現在使っている
  Cloud SQL connector（`--add-cloudsql-instances` / unix socket）は **public IP 経由なら VPC 不要**で動くため、
  private 化すると全 Cloud Run / Job の接続構成変更が必須。
- **コストが逆効果になり得る**: 削減できるのは IPv4 アドレス課金（**~$3/月/台**）のみ。一方 **VPC Connector は
  常時起動インスタンスを持ち、$3/月を上回ることがある**。Direct VPC egress なら connector 費は不要だが、
  サブネット/firewall 設計が増える。**コスト目的だけなら P2 は割に合わない可能性が高い**。
- **ローカル開発・運用の到達性**: private-only にすると、手元から `psql` / Cloud SQL Auth Proxy で直接つなぐのに
  VPC 内（踏み台 / IAP / VPN）が必要になり、移行・バックアップ・障害対応のオペが重くなる。
- **public IP は "無防備" ではない**: Cloud SQL Auth Proxy + IAM 認証 + SSL/TLS 強制 + authorized networks に
  `0.0.0.0/0` を置かない、を満たせば public IP でも実質的な攻撃面は小さい。private 化の上積み効果は限定的。

**結論 / 推奨**: P2 は「private IP 化」を必須とせず、まず **public IP のハードニング**（authorized networks 全廃 =
Auth Proxy 経由のみ許可、SSL 必須化、IAM DB 認証）で大半の安全性を**ほぼ無償**で確保する。private IP 化は
セキュリティ要件が上がった将来フェーズで、VPC コストと天秤にかけて判断する（**コスト削減の主役は P1/P3/P4**）。

#### P1 補足：共有インスタンスの命名（`driving-license-bot-pg` → `shared-pg`）

**決定（2026-05-31）**: 共有 Cloud SQL のインスタンス名を `driving-license-bot-pg` から **`shared-pg`** に変更する。

- **理由**: 現状の共有先は歴史的経緯で driving-license-bot 由来の名前だが、実態は
  driving_license / fujisawa_kb_db / piyolog が同居する **モノレポ横断の共有インスタンス**。
  名前と役割が一致しないため、中立的な `shared-pg` に改名する。
- **connection name**: `<project>:asia-northeast1:shared-pg` になる。

**重要 — これは「リネーム」ではなく「インスタンス再生成（作り直し）」**:

Cloud SQL のインスタンス `name` は **作成後に変更不可**。Terraform で `name` を変えると
プランは **旧インスタンス destroy → 新名称で create** になる（in-place rename は存在しない）。
したがって本変更は実質「新インスタンス作成 + 全 DB 移行 + 切替 + 旧インスタンス削除」であり、
**P1 の piyolog 集約（dump→restore）を、3 つの DB をまとめて新インスタンスへ行う形**になる。

影響範囲（`driving-license-bot-pg` をハードコード/参照している箇所）:

| 種別 | 箇所 |
|---|---|
| 名前生成 | `driving-license-bot/terraform/locals.tf` の `cloudsql_instance_name`（`${name_prefix}-pg` → 専用 var 化が必要） |
| 相乗り参照 | `fujisawa-platform` / `fujisawa-info-bot` / `piyolog-analytics` の `shared_cloudsql_instance_name` と `*.tfvars.example` の connection name |
| ドキュメント | 各 `terraform/README.md` / `docs/SETUP.md` / 本 proposal の Before/After |

> `driving-license-bot` の他リソース名は `name_prefix="driving-license-bot"` 由来のまま据え置き、
> **Cloud SQL instance 名だけを専用変数（例 `cloudsql_instance_name`、既定 `shared-pg`）に分離**して
> 切り出すのが最小差分。`${name_prefix}-pg` への暗黙依存を断つ。

**移行ステップ（実装 PR で詳細化、本 proposal では方針のみ）**:

1. 3 DB すべてをバックアップ（`gcloud sql export sql`：question_bank / fujisawa_kb_db / piyolog）。
2. 新インスタンス `shared-pg`（db-g1-small, max_connections=100）を作成。
3. 3 DB を `shared-pg` へ import、pgvector 拡張・各 user / GRANT を再作成。
4. 全 consumer（driving-license-bot / fujisawa-platform / fujisawa-info-bot / piyolog）の
   `shared_cloudsql_instance_name` と connection name を `shared-pg` に更新し、Cloud Run / Job を再デプロイ。
5. 動作確認後、旧 `driving-license-bot-pg` は即削除せず一定期間 stop で保持（ロールバック余地）。

> **ロールバック**: consumer の connection name を旧 `driving-license-bot-pg` に戻して再デプロイ、
> stop 中の旧インスタンスを start。切替直後ならステップ 1 のバックアップから復旧。
>
> **ステータス**: 命名を `shared-pg` に決定（意思決定のみ）。実装は別 PR（P1 の続き）。
> P1 の piyolog 集約（#182）と driving-license-bot の right-size（#183）が先行し、本改名は
> それらの上に乗せて 1 度の移行メンテで実施するのが望ましい。

### 3.1 User Stories

#### 3.1.1 ストーリー 1
> 運営者として、毎月の GCP 請求のうち「使っていなくても課金される」部分を最小化したい。
> Cloud SQL が 2 台あるのを 1 台にまとめ、public IP も外して、固定費を下げたい。

#### 3.1.2 ストーリー 2
> 開発者として、施策を一度に全部入れるのではなく、リスクの低いものから PR 単位で安全に適用し、
> 問題があればその PR だけロールバックしたい。

### 3.2 Notes / Constraints / Caveats

- **db-f1-micro は共有コア・RAM 0.6GB**。`fujisawa_kb_db` は **pgvector** を使うため、複数アプリ +
  ベクトル検索を 1 台の micro に集約すると RAM 不足になりやすい。集約と同時に **`db-g1-small`(1.7GB) 等への
  right-size がほぼ必須**。それでも「micro×2 → small×1」ならトータルは下がる試算。
- 集約しても **DB 名・DB ユーザーは分離したまま同居**できる（論理分離は維持、最小権限 GRANT を継続）。
- `piyolog` は `disk_autoresize=true`（青天井）、`driving-license-bot-pg` は `false`+10GB 上限。集約後は
  方針を統一（autoresize=true + `disk_autoresize_limit` 設定を推奨）。
- 障害の影響範囲（blast radius）は 1 台ダウンで全系停止に拡大する。バックアップ（自動 + export bucket）は既存。
- analytics-platform のリージョン移設（P4）は **state / bucket / BigQuery dataset の再作成**を伴うため、
  データ移行 or 作り直しの判断が必要（イベントは再生成可能なら作り直しが簡単）。

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 集約後 RAM/接続不足で全系が遅延・接続エラー | High | 集約と同時に `db-g1-small` 以上へ right-size、`max_connections` 調整、アプリ側 asyncpg プール上限の見直し |
| 1 インスタンス障害で全系停止（blast radius 拡大） | High | 自動バックアップ + PITR 有効化、export bucket 継続、`deletion_protection=true` |
| 移行中のデータ消失 | High | 旧インスタンスは即削除せず一定期間 stop で保持、`pg_dump`/`gcloud sql export` でフルバックアップ後に切替 |
| Private IP 化で Cloud Run から到達不可 | Medium | Serverless VPC Connector or Direct VPC egress を事前検証。現行の public 経由 socket 接続が動かなくなる点に注意 |
| Private IP 化の VPC Connector 費が IPv4 削減分を相殺 | Medium | コスト目的なら private 化を見送り、public IP のハードニング（authorized networks 全廃 + SSL + IAM DB 認証）で代替（3.1 P2 補足参照） |
| Private IP 化でローカル/運用の DB 到達性が低下 | Medium | 踏み台 / IAP / Auth Proxy 経由の手順を整備、移行・バックアップ運用への影響を事前確認 |
| AR cleanup で必要イメージを誤削除 | Medium | `keep` 条件（最新 N 世代 + tagged 保持）優先、初回は `dry-run` 相当で対象確認 |
| LLM cross-check 削減で品質低下 | Medium | 難易度/サンプリングでゲート、品質 KPI（analytics-platform イベント）で監視しながら段階適用 |
| リージョン移設での egress 一時増 | Low | 移行は低トラフィック時間帯、移行後に旧リソース削除 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略（Before / After）

```
Before（Cloud SQL 2 台）
  driving-license-bot-pg (f1-micro, public IP)
     ├── driving_license_db
     └── fujisawa_kb_db        ← fujisawa-platform / info-bot が相乗り（既存）
  piyolog (f1-micro, public IP, autoresize)
     └── piyolog_db

After（Cloud SQL 1 台に集約 + Private IP）
  shared-pg (db-g1-small, Private IP, autoresize+limit)
     ├── driving_license_db    (user: dlb_app)
     ├── fujisawa_kb_db        (user: fujisawa_etl / consumer, pgvector)
     └── piyolog_db            (user: piyolog_app)        ← P1 で移設
```

- Cloud Run / Cloud Run Jobs はいずれも Cloud SQL connector（unix socket）で `shared-pg` に接続。
- 既存の `shared_cloudsql_instance_name` / `_connection_name` 変数の仕組みを **piyolog にも展開**するだけで
  Terraform 上の構造は最小変更で済む（fujisawa が既に同パターン）。

### 4.2 データモデル

- スキーマ変更なし（集約は instance 同居）。各 DB は独立スキーマのまま。
- 移行は `pg_dump`（piyolog_db）→ `shared-pg` への `pg_restore`。pgvector 拡張は `fujisawa_kb_db` で
  `CREATE EXTENSION IF NOT EXISTS vector;` を維持。

### 4.3 API

- 変更なし（接続先の connection name / socket path のみ env / Terraform var で切替）。

### 4.4 主要モジュール

| 施策 | 主な変更ファイル |
|---|---|
| P1 集約 | `piyolog-analytics/terraform/cloud_sql.tf`（instance 作成を削除し共有 var 参照へ）、`locals.tf` / `variables.tf` / `outputs.tf`、各 `cloud_run` の接続設定 |
| P2 Private IP | 各 `cloudsql.tf`（`ipv4_enabled=false` + `private_network`）、VPC Connector or Auth Proxy 設定 |
| P3 AR cleanup | 各 `artifact_registry.tf` に `cleanup_policies`（keep 最新 N + delete untagged > Nd） |
| P4 リージョン | `analytics-platform/terraform/variables.tf`（region 既定）、bucket/BQ/Job 再作成、`workflows/dbt_pipeline.yaml` の location |
| P5 LLM | `driving-license-bot/app/config.py`（cross-check ゲート / モデル選択）、`llm-client` のルーティング |
| P6 min instances | `driving-license-bot/terraform/variables.tf`（`line_bot_min_instances` 既定） |

### 4.5 Test Plan

- **Unit**: 接続文字列ビルダ / config の backend 切替（既存テストの env マトリクスに socket path 追加）
- **Integration**: 集約先 `shared-pg` に対し各アプリの起動 + マイグレーション + 代表クエリ（pgvector 検索含む）を実行。
  Cloud SQL Auth Proxy をローカル/CI で立てて接続確認。
- **Manual / E2E**:
  - [ ] piyolog 移行後、LINE で `.txt` 取り込み → サマリ表示が成功する
  - [ ] driving-license の pgvector 重複検査が動作する
  - [ ] fujisawa ETL Job が `shared-pg` に upsert できる
  - [ ] Private IP 化後も全 Cloud Run / Job が DB 到達できる
  - [ ] AR cleanup 適用後、最新イメージで deploy できる（必要世代が残っている）

### 4.6 Migration / Rollback

- **Migration (P1)**:
  1. `shared-pg` を `db-g1-small` 等へ right-size（必要なら新規作成）。
  2. `gcloud sql export sql` で `piyolog_db` をダンプ → `shared-pg` に `import`。
  3. piyolog の Cloud Run の接続先を `shared-pg` の connection name に切替（Terraform apply）。
  4. 動作確認後、旧 `piyolog` インスタンスを **stop**（即削除しない）。
  5. 1〜2 週間問題なければ旧インスタンス削除。
- **Rollback**: Cloud Run の接続先 var を旧 `piyolog` instance に戻して apply。stop 中の旧インスタンスを start。
- **既存ユーザー影響**: 移行はメンテ時間帯に実施。切替中は短時間の DB 接続断（LINE は即時200を返し、
  処理失敗時は再送/エラー通知）。Firestore 利用機能は影響なし。

### 4.7 Feature Enablement

- 各施策は Terraform var / env で切替可能にする（例: `cloud_sql_use_shared_instance`、
  `cloud_sql_enable_public_ip`、`llm_cross_check_enabled`、`line_bot_min_instances`）。
- 無効化時は現行挙動を維持（後方互換）。

---

## 5. Operational Concerns

### 5.1 Monitoring

- Cloud Monitoring：`shared-pg` の CPU / memory / connections / disk 使用率（集約後の飽和検知）。
- 集約直後は接続エラー率・レイテンシ（各 Cloud Run のログ）を重点監視。
- 効果測定：Billing の BigQuery export、または請求コンソールで Cloud SQL / Networking 項目の月次推移を比較。
- LLM 最適化（P5）：analytics-platform のイベントでモデル別呼び出し回数・トークンを追跡。

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| 集約後に DB 接続エラー多発 | 接続数上限 → `max_connections` / アプリ側プール上限調整、tier 増強 |
| pgvector 検索が遅い | RAM 不足 → `db-g1-small` 以上へ、index（HNSW/IVFFlat）見直し |
| Cloud Run から Private IP DB に到達不可 | VPC Connector 未設定 / egress 設定 → connector + `vpc_access` 確認 |
| AR cleanup 後に rollback 用イメージが無い | keep 世代数が少ない → `keep` 条件の世代数を増やす |

### 5.3 Dependencies

- Cloud SQL（Postgres + pgvector）/ Secret Manager / IAM
- Serverless VPC Access Connector or Cloud SQL Auth Proxy（P2）
- Vertex AI / Anthropic（P5）/ `llm-client`
- analytics-platform（効果測定のイベント計装）

### 5.4 Non-Functional Requirements

#### コスト (Cost)
- 固定費: Cloud SQL 2→1 + IPv4 廃止 + cross-region 解消で **月 $15〜30 削減**目標（tier 次第）。
- right-size 後も「micro×2 → small×1」で純減を維持する（純増する tier 選定はしない）。
- 変動費: LLM cross-check を必要時のみに絞り、簡易タスクは Gemini Flash へルーティング。

#### 性能 (Performance)
- 集約後も各 LINE webhook は即時 200（既存）、ユーザー体感の劣化なし。
- pgvector 検索のレイテンシは集約前と同等以下を維持（RAM 確保で担保）。

#### プライバシー / データ保持
- DB / ユーザー分離と最小権限 GRANT を維持。同居でも他 DB へはアクセス不可。
- バックアップ保持・PITR の期間は現行ポリシー踏襲。

#### キャパシティ
- `shared-pg` は全系の同時接続を吸収できる接続数 / RAM を確保（監視しながら調整）。

---

## 6. Drawbacks

- 単一 Cloud SQL への集約は **blast radius が広がる**（1 台障害で複数サービス停止）。個人運営で許容可能と
  判断するが、HA を重視する将来フェーズでは再検討の余地。
- Private IP 化（P2）は VPC Connector の運用が増える（わずかなコストと複雑性）。
- リージョン移設（P4）は一度きりの移行コストが発生する。egress 削減効果と天秤にかける。

## 7. Alternatives

### 案 A: 現状維持（2 インスタンスのまま）
- 概要: 何もしない。
- 却下理由: 固定費（micro 2台 + IPv4 2つ）が継続。最小の労力で確実に下げられる P1/P3 を見送る理由が薄い。

### 案 B: 全 Postgres を Firestore へ寄せて Cloud SQL 全廃
- 概要: Cloud SQL を捨て Firestore に統一し、常時課金リソースをゼロに。
- 却下理由: pgvector（ベクトル検索）/ 関係モデル（piyolog の集計クエリ）が Firestore に不向き。
  移行コストと機能劣化が大きい。

### 案 C: Cloud SQL を停止スケジュール運用（夜間 stop）
- 概要: 低利用時間帯に instance を stop してコスト削減。
- 却下理由: LINE Bot は 24h 受信し得るため本番 DB の stop は不可。dev インスタンスには有効なので
  「開発用のみ stop 運用」は補助施策として併用可。

### 共有インスタンスの命名に関する代替案

- **案 N1: `driving-license-bot-pg` のまま共有（改名しない）**
  - 概要: 既存インスタンスをそのまま共有先として使い続ける。追加作業ゼロ・無停止。
  - 却下理由: 全システム共有なのに名前が 1 エージェント由来で、実態とズレる。命名の妥当性を優先し改名する。
- **案 N2（採用）: `shared-pg` へ改名（= 新インスタンス作成 + 全 DB 移行）**
  - 概要: 中立名の新インスタンスを作り、3 DB を移行して切替。
  - 採用理由: 命名が実態に合う。移行コストは P1 集約と同じ「dump→restore」を一度にまとめて実施できる。
  - 留意: Cloud SQL は in-place rename 不可のため再生成になる（3.1 P1 補足参照）。

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-30 | Draft | 初稿（Terraform 実構成の調査に基づくコスト削減提案） |
| 2026-05-30 | Review | レビュー指摘を反映：P2 を「private IP 必須」から「public IP ハードニング優先 / private は任意」に緩和。VPC Connector コスト・到達性リスクを追記 |
| 2026-05-31 | Implementing (P1) | piyolog Cloud SQL を共有インスタンスへ集約。`cloud_sql_use_shared_instance` フラグで両モード切替（既定 false=後方互換）、移行手順を piyolog-analytics/terraform/README.md に追記 |
| 2026-05-31 | Implementing (P1) | 共有先 (driving-license-bot) を right-size: tier 既定を db-f1-micro → db-g1-small、max_connections を明示設定済。集約有効化の前提を満たす |
| 2026-05-31 | Decision (P1) | 共有インスタンス名を `driving-license-bot-pg` → **`shared-pg`** に改名すると決定（命名の妥当性優先）。Cloud SQL は in-place rename 不可のため**インスタンス再生成 + 全 DB 移行**になる。本コミットは意思決定の記録のみ（実装は別 PR、3.1 P1 補足に方針記載） |
| 2026-05-31 | Implementing (P1) | `shared-pg` 改名を実装。driving-license-bot に `cloudsql_instance_name`（既定 shared-pg）を追加し name_prefix 依存を分離、consumer (fujisawa×2 / piyolog) の tfvars.example・変数説明・docs を `shared-pg` に更新、移行 runbook を driving-license-bot/terraform/README.md に追記 |
| 2026-06-05 | Implementing (P1) | 実移行前の repo 仕上げ: piyolog tfvars.example の集約変数追記・region 修正、`shared_cloudsql_instance_name` 必須の cross-var validation 追加、fujisawa-platform tfvars.example の project 名タイポ修正（sakamoto→sakamomo）。本番未実行 |
| 2026-06-05 | Runbook (P1) | 案②（`shared-pg` 改名・完全準拠）の実行手順書を確定（実環境ファクト反映・未実行）。`docs/PROPOSALS/notes/proposal-0009-p1-shared-pg-migration-2026-06-05.md` |
