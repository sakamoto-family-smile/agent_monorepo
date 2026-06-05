# PROPOSAL-0010: analytics-platform Phase 5 完遂（本番イベントの GCS 永続化）

| | |
|---|---|
| **Status** | Draft |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-06-06 |
| **Updated** | 2026-06-06 |
| **Target** | cross-agent (analytics-platform + 稼働中エージェント) |
| **Related PRs** | (none yet) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

本番 Cloud Run で稼働中のエージェント（`piyolog-analytics` / `driving-license-bot`）は
analytics イベントを発火しているが、**コンテナの揮発性ローカル FS に JSONL を書くだけ**で、
GCS 等への永続化が無いため **scale-to-zero / 再起動 / 新リビジョンデプロイのたびに消失**している。

analytics-platform の Phase 5（GCS / BigQuery / Workflows / Terraform / Monitoring）は**コードとしては大部分
実装済**だが、(a) **terraform が未 apply で本番に GCS バケットが存在しない**、(b) **各エージェントが GCS backend
に切り替わっていない（Step 10 未着手）**、(c) **Cloud Run の揮発 FS では「ローカル raw/ → 別 Job がアップロード」
方式が別コンテナから FS を見れず成立しない**、という 3 点で本番イベントが永続化されていない。

本提案は、この 3 点を解消し **本番イベントを GCS（→ BigQuery external table → dbt marts）に確実に永続化**する
ことをゴールとする。新規コードは最小限とし、既存の `GCSTransport` / `build_upload_transport()` /
`build_payload_writer()` / terraform 資産を最大活用する。

## 2. Motivation

- 本番のイベントが捨てられているため、**KPI 計測・本番の挙動観測・dbt marts が成立しない**。
  ローカル開発フロー（`data/raw` JSONL → DuckDB → dbt）は機能するが、本番データが入らない。
- Phase 1〜4（ローカル）は完了。Phase 5 は **Step 1,3〜9 がコード実装済、Step 2(Langfuse) / Step 10(エージェント切替)
  が未着手**（`analytics-platform/README.md` Status / `docs/DESIGN.md` §6.3）。残りは「本番に配備して各エージェントを
  繋ぐ」配線作業が主体。
- 個人運営のため、**hot path の性能を落とさず・固定費を増やさず**永続化したい。

### 2.1 Goals

- [ ] 本番 Cloud Run の emit イベントを **GCS に永続化**（→ BigQuery external table → dbt marts まで疎通）
- [ ] analytics-platform の **terraform を本番 apply**（GCS バケット 3 種 / BQ dataset / SA + IAM / Monitoring）
- [ ] 稼働中エージェント（まず `piyolog-analytics`、次に `driving-license-bot`）を **GCS backend に切替**（Step 10）
- [ ] **Cloud Run の揮発 FS でも取りこぼさないアップロード方式**を確立し、文書化する
- [ ] 既定は **後方互換**（`ANALYTICS_STORAGE_BACKEND=local` のまま、env で `gcs` 切替）。切替は env 1 つ
- [ ] 切替・ロールバック手順を明記する

### 2.2 Non-Goals

- **Langfuse on GKE（Step 2）** の導入（別提案 / 別フェーズ。本提案は JSONL→GCS→BQ パイプラインに限定）
- **全エージェントの一斉切替**（まず本番稼働中の 2〜3 サービスから段階適用。ローカルのみのサービスは対象外）
- イベントスキーマの大改修（既存の discriminated union JSONL をそのまま使う）
- リアルタイム / ストリーミング分析（バッチ前提。dbt は既存の定期実行）

---

## 3. Proposal

Phase 5 完遂を 3 つの未解決点（terraform 未 apply / エージェント未切替 / 揮発 FS）に分けて解く。
最大の論点は **「Cloud Run の揮発 FS からどう GCS に届けるか」** であり、以下の方式から選ぶ。

| 方式 | 概要 | hot path 性能 | 取りこぼし耐性 | 新規コード | 既存資産活用 |
|---|---|---|---|---|---|
| **案A: GCSSink 直書き** | イベント JSONL を batch flush 時に GCS へ直接 PUT する新 Sink | 中（flush 時 GCS I/O） | 高（local FS 非依存） | 中（新 Sink） | `GCSTransport` 部分流用 |
| **案B: in-process uploader（推奨）** | 既存どおり `RotatingFileSink` で local に書き、**アプリ内バックグラウンドタスクが短間隔で `GCSTransport` により GCS へ flush** + shutdown 時 flush | 高（append はローカル） | 中（flush 間隔分の窓） | 小（runner + 起動配線） | `LocalUploader`/`GCSTransport` をほぼそのまま |
| 案C: GCS FUSE マウント | `analytics_data_dir` を Cloud Run の GCS volume にマウント | 低（小ファイル高頻度に弱い） | 高 | ほぼ無 | — |
| 案D（却下）: 別 Cloud Run Job で raw/ をアップロード | 別 Job が agent の揮発 FS を読む | — | **不成立** | — | — |

> **推奨は案B**。理由: 既存 `LocalUploader` / `GCSTransport` をほぼそのまま使え、**hot path はローカル append のまま**で
> 性能劣化が無く、flush 間隔を短く（例 30〜60s）すれば取りこぼし窓は実用上小さい。Cloud Run の SIGTERM 猶予中に
> best-effort の最終 flush を行う。イベント低頻度（個人運営）なので案B で十分。
> 案A（GCSSink）は窓ゼロにできるが hot path / batch に GCS I/O が乗る。将来高頻度化したら案A へ移行可能。
> 案C（FUSE）は小ファイル高頻度 append に弱く却下寄り。

### 3.1 User Stories

#### 3.1.1 ストーリー 1
> 運営者として、本番で動いている LINE Bot 群の利用イベント（取り込み成否・相談回数等）を後から
> BigQuery / dbt で集計したい。今はコンテナ再起動で消えてしまい計測できない。

#### 3.1.2 ストーリー 2
> 開発者として、永続化を **env 1 つ（`ANALYTICS_STORAGE_BACKEND=gcs`）で on/off** したい。問題が出たら
> その env を `local` に戻すだけでロールバックしたい。

### 3.2 Notes / Constraints / Caveats

- **GCS バケット名はグローバル一意**。terraform `name_prefix` を `sakamomo-family-agent-analytics` 等に設定する。
- **リージョン整合**: terraform の bucket location 既定は `US`。egress / レイテンシ / proposal 0009 P4 のリージョン整理に
  合わせ **`ASIA-NORTHEAST1`** に寄せる。BigQuery dataset も同一ロケーションにする（external table 制約）。
- **認証**: Cloud Run の SA に GCS 書込（`roles/storage.objectAdmin` を raw/payloads prefix にスコープ）を付与。
  CI は WIF（既存 `pr-tests.yml` の WIF パターン踏襲）。
- **揮発 FS と flush 窓**: 案B はクラッシュ / 強制終了時に未 flush 分（最大 flush 間隔）を失う。低頻度のため許容。
  窓ゼロが要件化したら案A へ。
- **payload**: 8KB 超の本文は `GCSPayloadWriter`（実装済）で GCS payloads/ prefix に直書きできる。イベント本体（raw JSONL）
  とは別 prefix。

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| flush 前のコンテナ強制終了でイベント取りこぼし | Medium | flush 間隔を短く（30〜60s）+ SIGTERM 時 best-effort flush。低頻度のため実害小。要件次第で案A へ |
| GCS 書込権限不足で全 emit が失敗 / アプリに影響 | High | emit / upload は **fail-open**（失敗してもアプリ本体は継続）。dead_letter/ に退避し再送。SA 権限を事前検証 |
| terraform apply で既存リソースに影響 | Medium | analytics-platform は新規スタック（既存と独立 state）。plan を目視。バケット名一意性を事前確認 |
| 固定費の増加 | Low | GCS は従量・低額（イベント微小）。lifecycle で NEARLINE→COLDLINE→ARCHIVE 逓減（terraform 実装済） |
| BigQuery external table がパーティションを認識しない | Medium | Hive partition (`service_name=/event_type=/dt=/hour=`) を GCSTransport が保持。autodetect 設定済。疎通テストで確認 |
| 切替後にイベントが二重 / 欠落 | Medium | env gate で段階適用。1 サービスずつ切替→ GCS / BQ で件数照合してから次へ |

---

## 4. Design Details

### 4.1 アーキテクチャ概略（Before / After）

```
Before（本番イベントは消失）
  Cloud Run (piyolog / driving-license-bot)
    AnalyticsLogger → RotatingFileSink → /data/raw/...jsonl  （揮発 FS）
                                            └─ 再起動で消失。GCS 連携なし

After（案B: in-process uploader）
  Cloud Run (agent, ANALYTICS_STORAGE_BACKEND=gcs)
    AnalyticsLogger → RotatingFileSink → ./data/raw/...jsonl
                          │
                          └─ 同コンテナ内 background task（30〜60s 間隔 + shutdown flush）
                                LocalUploader.run_once() → GCSTransport.send()
                                   → gs://<bucket>/uploaded/service_name=.../*.jsonl
                                        └→ BigQuery external table → dbt staging/marts
    payload(8KB+) → GCSPayloadWriter → gs://<bucket>/payloads/...
```

#### 環境別の格納先（local / cloud）と切替

イベントの格納先は **稼働環境ではなく `ANALYTICS_STORAGE_BACKEND` で決まる**（ローカルでも `gcs` を、クラウドでも
`local` を選べるが、実運用は下表の組合せ）。

| 稼働環境 / backend | イベント本体 (raw JSONL) | 大容量 payload | 永続性 |
|---|---|---|---|
| ローカル / `local`（既定） | ローカル FS `${ANALYTICS_DATA_DIR}/raw/`（→ DuckDB / dbt local） | `${ANALYTICS_DATA_DIR}/payloads/` | ✅ ディスク |
| クラウド / `gcs` | ローカル raw/ に一旦書き → uploader が flush → `gs://<bucket>/uploaded/service_name=.../*.jsonl` → BigQuery external table → dbt marts | `gs://<bucket>/payloads/`（`GCSPayloadWriter` 直書き） | ✅ GCS |
| （参考）現状クラウド | コンテナ揮発 FS のみ | コンテナ揮発 FS のみ | ❌ 再起動で消失 |

**切替は env のみ**（コード変更・再ビルド不要、再デプロイのみ）:

| env | 値 | 役割 |
|---|---|---|
| `ANALYTICS_STORAGE_BACKEND` | `local`（既定）/ `gcs` | 格納先スイッチ |
| `ANALYTICS_GCS_BUCKET` | バケット名 | `gcs` 時必須。未設定なら **local に自動フォールバック + 警告**（`gcp_config.load_gcs_config`） |
| `ANALYTICS_GCP_PROJECT` | project id | Cloud Run + WIF なら省略可 |
| `ANALYTICS_ENABLED` | `true` / `false` | emit 自体の on/off（false で NoOp） |
| `ANALYTICS_DATA_DIR` | パス | ローカル root（既定 `./data`） |

- 既定 `local` のため、何もしなければ現行どおり（後方互換）。本番は `gcs` + bucket を Cloud Run env に足して再デプロイ。
- ロールバックは env を `local` に戻して再デプロイするだけ。
- backend 選択ロジック（`detect_storage_backend` / `load_gcs_config` / `build_upload_transport` / `build_payload_writer`）は
  analytics-platform 側に実装済。**エージェントの `setup.py` がそれらを呼ぶよう変える + config に上記 env を追加する**のが Step 10 の作業。

### 4.2 データモデル

- イベントスキーマ変更なし（既存 discriminated union JSONL / Hive partition をそのまま）。
- GCS key 構造: `uploaded/service_name=<svc>/event_type=<et>/dt=<YYYY-MM-DD>/hour=<HH>/<file>.jsonl[.gz]`。
- BigQuery external table が上記 prefix を Hive partition として読む（実装済）。

### 4.3 API

- 外部 API 変更なし。切替は env（`ANALYTICS_STORAGE_BACKEND` / `ANALYTICS_GCS_BUCKET` / `ANALYTICS_GCP_PROJECT`）。

### 4.4 主要モジュール

| 区分 | 変更 |
|---|---|
| analytics-platform | uploader の **実行 entrypoint**（`python -m analytics_platform.uploader` 相当の async runner）を追加。アプリ内 background task として起動できる薄い API（`start_background_uploader(...)`）も提供 |
| analytics-platform | （案A 採用時のみ）`GCSSink` を新設。本提案では推奨案B のため optional |
| agent: instrumentation | `setup.py` を **`build_payload_writer()` / `build_upload_transport()`（`gcp_config`）利用**に変更。`ANALYTICS_STORAGE_BACKEND=gcs` のとき GCS、`local` 既定で現行どおり。app startup で background uploader を起動、shutdown で flush |
| agent: config | `analytics_storage_backend` / `analytics_gcs_bucket` / `analytics_gcp_project` を `Settings` に追加（既定 local/空） |
| terraform | analytics-platform `terraform/` を **本番 apply**。`name_prefix` / bucket location（asia-northeast1）/ project を設定。各 agent SA に GCS 書込 IAM を付与 |
| Cloud Run env | 対象サービスに `ANALYTICS_STORAGE_BACKEND=gcs` / `ANALYTICS_GCS_BUCKET=<raw bucket>` / `ANALYTICS_GCP_PROJECT` を設定して再デプロイ |

### 4.5 Test Plan

- **Unit**: backend 選択（`detect_storage_backend` / `load_gcs_config` の local/gcs/fallback）、uploader の retry / dead_letter 振り分け、Hive key 生成。
- **Integration**: fake GCS client（既存 `tests/test_gcs_transport.py` 流儀）で emit → `run_once` → 期待 GCS key にアップロード・local 削除を確認。
- **E2E（本番 / staging）**:
  - [ ] 対象サービスを `gcs` 切替・再デプロイ後、テストイベント発火 → `gs://<bucket>/uploaded/...` にオブジェクト出現
  - [ ] BigQuery external table から当該イベントが SELECT できる
  - [ ] dbt（`--target gcp`）で staging/marts までビルドできる
  - [ ] env を `local` に戻すと現行どおり（後方互換）

### 4.6 Migration / Rollback

- **Migration（段階適用）**:
  1. terraform apply（GCS / BQ / IAM / Monitoring を本番作成）
  2. analytics-platform に uploader runner 追加（コードのみ、挙動は env gate）
  3. `piyolog-analytics` を `gcs` に切替・再デプロイ → GCS / BQ で件数照合
  4. 問題なければ `driving-license-bot` も切替
  5. dbt marts / Monitoring で観測開始
- **Rollback**: 対象サービスの env を `ANALYTICS_STORAGE_BACKEND=local` に戻して再デプロイ（即時・コード変更不要）。
  GCS / BQ リソースは残しても課金は微小。

### 4.7 Feature Enablement

- `ANALYTICS_STORAGE_BACKEND`（既定 `local`）= `gcs` で有効化。`ANALYTICS_GCS_BUCKET` 未設定なら local に
  fallback + 警告（`gcp_config.load_gcs_config` 実装済）。無効時は現行 NoOp / local 挙動を完全維持。

---

## 5. Operational Concerns

### 5.1 Monitoring

- Cloud Monitoring（terraform 実装済のアラートポリシー）: uploader 失敗率 / dead_letter 増加 / GCS 書込エラー。
- BigQuery: 日次のイベント件数推移（外部テーブル → marts）。サービス別 emit 件数の急減を異常として検知。
- アプリログ: uploader の `UploadOutcome`（uploaded / dead_letter 件数）を構造化ログで emit。

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| GCS にオブジェクトが出ない | env（backend/bucket/project）未設定 or SA 権限不足 → `gcp_config` 警告ログ / IAM 確認 |
| dead_letter/ が増える | GCS 一時障害 / 権限 → 再送、`max_attempts` / backoff 調整 |
| BQ external table が空 | prefix / Hive partition 不一致 → key 構造と external table 定義を照合 |
| 再起動でまだ消える | env が `local` のまま or uploader 未起動 → backend と startup 配線を確認 |

### 5.3 Dependencies

- GCS / BigQuery / Cloud Monitoring / Secret Manager（不要）/ IAM（SA + WIF）
- `google-cloud-storage`（analytics-platform `[gcs]` extra）/ `google-cloud-bigquery`（dbt-bigquery）
- 既存: `GCSTransport` / `LocalUploader` / `build_upload_transport` / `build_payload_writer` / terraform 一式

### 5.4 Non-Functional Requirements

#### 性能 (Performance)
- hot path（emit）はローカル append のままで劣化なし（案B）。GCS 送信は background。

#### コスト (Cost)
- GCS 従量・低額（イベント微小 + lifecycle 逓減）。BigQuery external table はストレージ課金なし、クエリ従量。
  固定費の増加はほぼ無し。

#### プライバシー / データ保持
- LINE 個人データを含み得るため、バケットは非公開・最小権限 SA。lifecycle で逓減保持。payload は別 prefix。

#### キャパシティ
- 低頻度（個人運営）。将来高頻度化時は flush 間隔短縮 or 案A（GCSSink）へ移行。

---

## 6. Drawbacks

- アプリ内 background uploader（案B）は **moving part が増える**（起動 / shutdown flush / 失敗時の dead_letter）。
- flush 間隔分の **取りこぼし窓**が残る（低頻度ゆえ許容、要件次第で案A）。
- terraform スタックを 1 つ本番運用に追加する（GCS / BQ / IAM / Monitoring の維持）。

## 7. Alternatives

### 案 A: GCSSink で直書き
- 概要: イベント JSONL を batch flush 時に GCS へ直接 PUT する新 Sink を実装し、local FS を経由しない。
- 評価: 取りこぼし窓ゼロ。ただし hot path / batch に GCS I/O が乗り、新規 Sink コードが要る。**将来高頻度化したら本案へ移行**。

### 案 B: in-process uploader（採用 / 推奨）
- 概要: 既存 `RotatingFileSink` + アプリ内 background `LocalUploader`/`GCSTransport` で短間隔 flush + shutdown flush。
- 採用理由: 既存資産をほぼそのまま使え、hot path 無劣化、env gate で段階適用・即ロールバック。個人運営の低頻度に最適。

### 案 C: GCS FUSE ボリュームマウント
- 概要: `analytics_data_dir` を Cloud Run の GCS volume にマウントし、書き込みをそのまま GCS に。
- 却下寄り理由: 小ファイル高頻度 append にレイテンシ / 整合性面で弱い。コード変更は最小だが運用特性が読みにくい。

### 案 D: 別 Cloud Run Job が raw/ をアップロード（却下）
- 概要: 別 Job が定期的に agent の `raw/` を読んで GCS へ。
- 却下理由: Cloud Run の揮発 FS は **別コンテナから参照不可**。アーキ的に成立しない。

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-06-06 | Draft | 初稿。本番イベントが揮発 FS で消失している実態（`gcloud run` / コード調査）を踏まえ、Phase 5 完遂（terraform apply + Step 10 エージェント切替 + 揮発 FS 対応）を提案。方式は案B（in-process uploader）を推奨 |
| 2026-06-06 | Draft | §4.1 に「環境別の格納先（local / cloud）と env 切替」表を追記（レビュー Q&A 反映）。切替は `ANALYTICS_STORAGE_BACKEND` のみ・既定 local で後方互換であることを明確化 |
