# PROPOSAL-0010: analytics-platform Phase 5 完遂（Pub/Sub 入口 + 本番イベントの GCS 永続化）

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

本番 Cloud Run のエージェント（`piyolog-analytics` / `driving-license-bot`）は analytics イベントを発火しているが、
**コンテナの揮発性ローカル FS に JSONL を書くだけ**で、再起動・scale-to-zero・新リビジョンのたびに消失している。

本提案は **イベント送信の入口を Cloud Pub/Sub に変更**し、Pub/Sub の **Cloud Storage サブスクリプション**で
既存の GCS バケットへ流し込み、そこから **BigQuery external table → dbt marts**（Phase 5 で実装済）に繋ぐことで、
本番イベントを確実に永続化する。

採用方式は **案E-1（Pub/Sub → GCS サブスク）**。クライアント（エージェント）は `AnalyticsLogger.emit()` で
**publish するだけ**になり、ローカル FS への依存・アプリ内アップローダ・shutdown flush といった moving part が
不要になる（揮発 FS 問題が入口で根本解決する）。実装は analytics-platform の**クライアントライブラリに
`PubSubSink` を 1 つ足し、env で sink を選ぶ**のが中心で、emit API は不変。

## 2. Motivation

- 本番イベントが捨てられており、**KPI 計測・本番挙動の観測・dbt marts が成立しない**。
- Phase 1〜4（ローカル）完了。Phase 5 は **Step 1,3〜9 がコード実装済、Step 2(Langfuse)/Step 10(エージェント切替)
  が未着手**。残りは「本番に配備して各エージェントを繋ぐ」配線。
- 当初案（案B: ローカル FS + アプリ内アップローダ）はアプリに非同期バッファ/flush の複雑さが残る。**Pub/Sub を入口に
  すれば、publish 時点で durable になり、呼び出し側の非同期管理が不要**になる（レビュー指摘）。Pub/Sub は
  **月 10 GiB スループットまで無料枠**で、本システムの低頻度では実質 $0 のため、コスト障壁はない。

### 2.1 Goals

- [ ] 本番 Cloud Run の emit イベントを **Pub/Sub 経由で GCS に永続化**（→ BigQuery external table → dbt marts まで疎通）
- [ ] イベント送信ライブラリ（`analytics_platform.observability`）に **`PubSubSink` を追加**し、`AnalyticsLogger.emit()`
      の API を変えずに backend を差し替え可能にする
- [ ] 稼働中エージェント（まず `piyolog-analytics`、次に `driving-license-bot`）を **Pub/Sub backend に切替**（Step 10）
- [ ] Pub/Sub topic / GCS サブスク / dead-letter / IAM を **terraform で本番作成**
- [ ] 既定は **後方互換**（`ANALYTICS_STORAGE_BACKEND=local`）。切替は env のみ・即ロールバック可
- [ ] 切替・ロールバック手順を明記する

### 2.2 Non-Goals

- **emit API（`AnalyticsLogger.emit`）の変更**（sink 差し替えのみ。呼び出し側コードは原則不変）
- **Langfuse on GKE（Step 2）**（別フェーズ）
- **全エージェントの一斉切替**（本番稼働中の 2〜3 サービスから段階適用。ローカルのみのサービスは対象外）
- イベントスキーマの大改修 / リアルタイム集計（バッチ前提、dbt は既存の定期実行）

---

## 3. Proposal

イベント送信の **入口を Pub/Sub** にする。クライアントライブラリの sink を `RotatingFileSink`（ローカル）から
`PubSubSink`（topic に publish）へ env で切り替える。Pub/Sub からの出口は **Cloud Storage サブスク**で既存 GCS に
流し、**BQ external table → dbt** をそのまま使う。

| 方式 | 入口 | 出口 | 呼出側の複雑さ | 揮発FS耐性 | 既存資産 | コスト |
|---|---|---|---|---|---|---|
| **案E-1（採用/推奨）** | Pub/Sub topic | **GCS サブスク** → 既存 GCS → BQ external table → dbt | **小**（publish のみ） | **◎ 入口で解決** | dbt/external table 流用 | 無料枠内 |
| 案E-2 | Pub/Sub topic | **BQ サブスク**（直接） | 小 | ◎ | GCS/external 層を撤去、dbt source 変更 | 無料枠内 |
| 案B | RotatingFileSink(local) | アプリ内 uploader → GCS → BQ | 中（buffer/flush/shutdown） | △（flush 窓） | 最大流用 | 無料枠内 |
| 案A | GCSSink 直書き | GCS → BQ | 中 | ◎ | 一部流用 | 無料枠内 |
| 案D（却下） | 別 Job が raw/ 収集 | — | — | **不成立** | — | — |

> **採用は案E-1**。`AnalyticsLogger` が既にバッファ + 非同期フラッシュを内蔵しているため、`PubSubSink.write_batch()` は
> publish するだけでよく、**アプリ側に追加の非同期処理は不要**。Pub/Sub クライアントがバッチ/リトライを担い、publish ack
> 時点で durable なので **Cloud Run の揮発 FS / scale-to-zero でも取りこぼさない**。出口を GCS サブスクにすることで
> 既存の external table / dbt 資産をそのまま活かす。

### 3.1 User Stories

#### 3.1.1 ストーリー 1
> 運営者として、本番の LINE Bot 群のイベントを後から BigQuery / dbt で集計したい。今は再起動で消える。

#### 3.1.2 ストーリー 2
> 開発者として、イベント送信は `emit()` を呼ぶだけにしたい。アップロードの非同期管理やコンテナ終了時の flush を
> アプリに書きたくない。切替は env 1 つで、問題が出たら `local` に戻すだけにしたい。

### 3.2 Notes / Constraints / Caveats

- **`AnalyticsLogger.emit` は不変**。差し替えるのは `JsonlSink` 実装（`write_batch(lines)`）。`PubSubSink` は各行（JSON
  イベント）を Pub/Sub message として publish する。
- **at-least-once**: Pub/Sub は最低 1 回配信で重複し得る。既存の `event_id`（`sha256(...)`）で **dbt 側 dedup** する
  （現行の冪等設計を踏襲）。
- **GCS サブスクのファイル/パーティション命名**は現行の Hive `service_name=/event_type=/dt=/hour=` と異なり、
  **ingestion 日時プレフィックス**ベースになる。よって BQ external table を「日時パーティション + `service_name`/`event_type`
  はメッセージ内カラムとして読む」形に**定義調整**が要る（§4.2 / §3.3）。
- **無料枠**: Pub/Sub は月 10 GiB スループット無料。本システムは低頻度のため実質 $0。GCS / BQ も従量・微小。
- **fail-open**: publish 失敗はアプリ本体を止めない（best-effort、ログ + メトリクス）。Pub/Sub クライアントが
  リトライ、恒久失敗は dead-letter topic へ。
- **ローカル開発**: ローカルは引き続き `local`（ファイル）backend を既定にする。Pub/Sub エミュレータは任意
  （cloud のみ pubsub backend を使う運用で十分）。

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| GCS サブスクのファイル命名が external table 定義と不一致でクエリできない | High | external table を ingestion 日時パーティション + カラム読みに再定義し、疎通テストで確認（§4.5） |
| 重複配信でイベント二重計上 | Medium | `event_id` で dbt staging に dedup を入れる（既存ハッシュ流用） |
| publish 失敗でイベント欠落 / アプリ影響 | Medium | fail-open + Pub/Sub リトライ + dead-letter topic。送信失敗率を Monitoring |
| Pub/Sub / サブスク / IAM の新規インフラが増える | Medium | terraform で一括管理（topic/subscription/dead-letter/SA）。plan 目視 |
| backend 切替時の二重 / 欠落 | Medium | env gate で 1 サービスずつ切替→ GCS/BQ で件数照合してから次へ |
| 無料枠超過 | Low | 低頻度で当面無料枠内。Monitoring でスループット監視、超過時アラート |

---

## 4. Design Details

### 4.1 アーキテクチャ概略（Before / After）

```
Before（本番イベントは消失）
  Cloud Run (agent)
    AnalyticsLogger.emit → RotatingFileSink → /data/raw/...jsonl  （揮発 FS、再起動で消失）

After（案E-1: Pub/Sub 入口）
  Cloud Run (agent, ANALYTICS_STORAGE_BACKEND=pubsub)
    AnalyticsLogger.emit
       └─ (buffer + 非同期 flush は AnalyticsLogger が内蔵)
            └─ PubSubSink.write_batch(lines)
                  → publish to topic: analytics-events            ← ここで durable
                        │
              Pub/Sub Cloud Storage サブスク（バッチ）
                        ↓
              gs://<raw-bucket>/<prefix>/<YYYY/MM/DD/HH>/...        （既存バケット）
                        ↓
              BigQuery external table → dbt staging/marts          （Phase 5 実装済を流用）
        恒久失敗 → dead-letter topic
```

#### クライアントライブラリ（送信側）の構造

- 入口: `analytics_platform.observability.AnalyticsLogger`（path dep）。`emit()` が **バリデーション + バッファ +
  非同期フラッシュ**を担い、`JsonlSink.write_batch(lines: list[str])` を呼ぶ（`sinks/file_sink.py` の Protocol）。
- 現状: `RotatingFileSink`（ローカル Hive JSONL）/ `NoOpSink` のみ。
- 追加: **`PubSubSink(JsonlSink)`** — `write_batch` で各行を topic に publish（fire-and-forget、ack で durable）。
- **backend 選択を 1 箇所に集約**: `gcp_config.build_sink(...)` を新設（既存 `build_upload_transport` / `build_payload_writer`
  と同様）し、`ANALYTICS_STORAGE_BACKEND` で `local`→`RotatingFileSink` / `pubsub`→`PubSubSink` を返す。
  エージェントの `setup.py` はこの factory を呼ぶだけ（現状のハードコードを置換 = Step 10）。

#### 環境別の格納先（local / cloud）と切替

格納先は稼働環境ではなく **`ANALYTICS_STORAGE_BACKEND`** で決まる。

| 稼働環境 / backend | イベント本体 | 大容量 payload | 永続性 |
|---|---|---|---|
| ローカル / `local`（既定） | ローカル FS `${ANALYTICS_DATA_DIR}/raw/` → DuckDB/dbt | `.../payloads/` | ✅ ディスク |
| クラウド / `pubsub`（推奨） | Pub/Sub topic → GCS サブスク → `gs://<bucket>/...` → BQ external table → dbt | `gs://<bucket>/payloads/`（`GCSPayloadWriter` 直書き） | ✅ Pub/Sub→GCS |
| （参考）現状クラウド | コンテナ揮発 FS のみ | コンテナ揮発 FS のみ | ❌ 消失 |

**切替は env のみ**（コード変更・再ビルド不要、再デプロイのみ）:

| env | 値 | 役割 |
|---|---|---|
| `ANALYTICS_STORAGE_BACKEND` | `local`（既定）/ `pubsub`（/ `gcs` は案B 互換の file-upload） | sink 選択スイッチ |
| `ANALYTICS_PUBSUB_TOPIC` | topic 名 | `pubsub` 時必須。未設定なら local に fallback + 警告 |
| `ANALYTICS_GCP_PROJECT` | project id | Cloud Run + WIF なら省略可 |
| `ANALYTICS_ENABLED` | `true`/`false` | emit 自体の on/off（false で NoOp） |
| `ANALYTICS_DATA_DIR` | パス | ローカル root（`local` 時のみ使用、既定 `./data`） |

- 既定 `local` で現行どおり（後方互換）。本番は `pubsub` + topic を Cloud Run env に足して再デプロイ。
- ロールバックは env を `local` に戻して再デプロイするだけ。

### 4.2 データモデル

- イベントスキーマ変更なし（既存 discriminated union JSONL を Pub/Sub message body にそのまま載せる）。
- GCS 上のファイルは GCS サブスクが ingestion 日時でパーティション。`service_name` / `event_type` / `ts` /
  `event_id` 等は**メッセージ内のカラム**として保持され、BQ external table はそれらをカラムとして読む
  （Hive パス partition から日時 partition + カラムフィルタへ定義変更）。
- dedup は `event_id` で dbt staging にて実施。

### 4.3 API

- 外部 API / emit API 変更なし。切替は env（`ANALYTICS_STORAGE_BACKEND` / `ANALYTICS_PUBSUB_TOPIC` / `ANALYTICS_GCP_PROJECT`）。

### 4.4 主要モジュール

| 区分 | 変更 |
|---|---|
| analytics-platform (lib) | `observability/sinks/pubsub_sink.py` に **`PubSubSink(JsonlSink)`** を追加（`google-cloud-pubsub`、`[pubsub]` extra・遅延 import）。`gcp_config.build_sink()` を新設して backend で sink を選択 |
| analytics-platform (terraform) | Pub/Sub **topic** / **GCS サブスク** / **dead-letter topic + サブスク** / 関連 IAM を追加。BQ external table を ingestion 日時 partition + カラム読みに調整。既存 GCS バケット/BQ dataset/Monitoring は流用 |
| agent: instrumentation | `setup.py` を **`build_sink()` 利用**に変更（`RotatingFileSink` ハードコードを置換）。`emit` 呼び出し箇所は不変 |
| agent: config | `analytics_storage_backend` / `analytics_pubsub_topic` / `analytics_gcp_project` を `Settings` に追加（既定 local/空） |
| Cloud Run env | 対象サービスに `ANALYTICS_STORAGE_BACKEND=pubsub` / `ANALYTICS_PUBSUB_TOPIC=<topic>` / `ANALYTICS_GCP_PROJECT` を設定し、SA に `roles/pubsub.publisher` を付与して再デプロイ |

### 4.5 Test Plan

- **Unit**: `build_sink` の backend 分岐（local/pubsub/fallback）、`PubSubSink.write_batch` が各行を publish するか
  （fake publisher で検証）、publish 失敗時の fail-open。
- **Integration**: Pub/Sub エミュレータ or fake で emit → publish → （サブスク相当の）GCS 書き込み形を検証。
- **E2E（staging / 本番）**:
  - [ ] 対象サービスを `pubsub` 切替・再デプロイ後、テストイベント発火 → topic にメッセージ → `gs://<bucket>/...` に出現
  - [ ] BigQuery external table から当該イベントが SELECT でき、`event_id` dedup が効く
  - [ ] dbt（`--target gcp`）で staging/marts までビルドできる
  - [ ] env を `local` に戻すと現行どおり（後方互換）
  - [ ] publish を強制失敗させてもアプリ本体は 200 を返し継続（fail-open）

### 4.6 Migration / Rollback

- **Migration（段階適用）**:
  1. terraform apply（topic / GCS サブスク / dead-letter / IAM / external table 調整を本番作成）
  2. analytics-platform に `PubSubSink` + `build_sink` を追加（コードのみ、挙動は env gate）
  3. `piyolog-analytics` を `pubsub` に切替・再デプロイ → topic / GCS / BQ で件数照合
  4. 問題なければ `driving-license-bot` も切替
  5. dbt marts / Monitoring で観測開始
- **Rollback**: 対象サービスの env を `ANALYTICS_STORAGE_BACKEND=local` に戻して再デプロイ（即時・コード変更不要）。

### 4.7 Feature Enablement

- `ANALYTICS_STORAGE_BACKEND`（既定 `local`）= `pubsub` で有効化。`ANALYTICS_PUBSUB_TOPIC` 未設定なら local に
  fallback + 警告。無効時は現行 local/NoOp 挙動を完全維持。

---

## 5. Operational Concerns

### 5.1 Monitoring

- Pub/Sub: publish 失敗率 / 未 ack メッセージ数 / dead-letter のメッセージ数（Cloud Monitoring アラート）。
- GCS サブスク: 書き込み遅延 / エラー。BigQuery: 日次イベント件数（marts）でサービス別 emit の急減を検知。
- アプリ: `PubSubSink` の publish 成否を構造化ログ + メトリクスで emit。

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| GCS にファイルが出ない | サブスク未設定 / SA 権限（publisher / サブスク writer）→ IAM とサブスク設定を確認 |
| BQ external table が空 | ファイル命名と external table 定義の不一致 → §4.2 の日時 partition / カラム定義を確認 |
| 重複計上 | dbt の `event_id` dedup 未適用 → staging の distinct 化を確認 |
| 再起動でまだ消える | env が `local` のまま or topic 未設定 → backend と topic を確認 |
| dead-letter が増える | publish 先 / スキーマ不正 → メッセージとサブスク設定を点検 |

### 5.3 Dependencies

- Cloud Pub/Sub（topic / GCS サブスク / dead-letter）/ GCS / BigQuery / Cloud Monitoring / IAM（SA + WIF）
- `google-cloud-pubsub`（analytics-platform `[pubsub]` extra）/ 既存 `google-cloud-storage` / dbt-bigquery
- 既存資産: `AnalyticsLogger` / `JsonlSink` / `GCSPayloadWriter` / BQ external table / dbt / terraform 一式

### 5.4 Non-Functional Requirements

#### 性能 (Performance)
- hot path（emit）は AnalyticsLogger のバッファ + publish（非同期）で劣化なし。GCS/BQ への配送は Pub/Sub が担う。

#### コスト (Cost)
- Pub/Sub は月 10 GiB 無料枠内（低頻度）。GCS / BQ external table も従量・微小。固定費増はほぼ無し。

#### プライバシー / データ保持
- LINE 個人データを含み得るため topic / バケットは非公開・最小権限 SA。GCS lifecycle で逓減保持。payload は別 prefix。

#### キャパシティ
- 低頻度（個人運営）。将来高頻度化しても Pub/Sub がスケール。サブスクのバッチ間隔 / ファイルサイズで調整。

---

## 6. Drawbacks

- 新規インフラ（Pub/Sub topic / GCS サブスク / dead-letter / IAM）が増え、terraform の維持対象が広がる。
- **at-least-once** のため downstream で `event_id` dedup が必須（既存ハッシュで対応可だが dbt に明示実装が要る）。
- GCS サブスクのファイル命名が現行 Hive partition と異なり、**BQ external table の定義変更**が必要。
- ローカルと本番で backend が分かれる（local=ファイル / cloud=Pub/Sub）。ただし env 切替で吸収。

## 7. Alternatives

### 案 E-1: Pub/Sub → GCS サブスク（採用 / 推奨）
- 概要: 入口を Pub/Sub、出口を GCS サブスクにして既存 GCS / external table / dbt を流用。
- 採用理由: 呼出側は publish のみで揮発 FS を入口で根本解決。既存 Phase 5 資産（GCS/dbt）を最大流用。無料枠内。

### 案 E-2: Pub/Sub → BigQuery サブスク（直接）
- 概要: GCS / external table を撤去し、Pub/Sub から BQ ネイティブテーブルへ直接書き込む。
- 評価: 最もシンプル（中間層ゼロ）。ただし GCS の安価な長期アーカイブと既存 external-table/dbt 接続を失う。
  GCS アーカイブ不要なら有力な簡素化。

### 案 B: ローカル FS + アプリ内 uploader（旧推奨）
- 概要: `RotatingFileSink` で local に書き、アプリ内 background `GCSTransport` で flush + shutdown flush。
- 却下理由: アプリに buffer/flush/shutdown の複雑さが残り、flush 窓の取りこぼしもある。Pub/Sub 化で入口解決する方が綺麗。
  ただし既存 uploader 資産を最大流用でき、Pub/Sub を増やしたくない場合の代替。

### 案 A: GCSSink で直書き
- 概要: イベント JSONL を batch flush 時に GCS へ直接 PUT する新 Sink。
- 評価: 取りこぼし窓ゼロだが hot path に GCS I/O が乗る。Pub/Sub を使わない最小構成の代替。

### 案 C: GCS FUSE マウント
- 却下寄り: 小ファイル高頻度 append にレイテンシ / 整合性で弱い。

### 案 D: 別 Cloud Run Job が raw/ をアップロード（却下）
- 却下理由: Cloud Run の揮発 FS は別コンテナから参照不可。アーキ的に成立しない。

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-06-06 | Draft | 初稿。本番イベントが揮発 FS で消失している実態を踏まえ Phase 5 完遂を提案。当初は案B（in-process uploader）を推奨 |
| 2026-06-06 | Draft | §4.1 に環境別の格納先 / env 切替表を追記 |
| 2026-06-06 | Draft | レビュー指摘（Pub/Sub 入口・呼出側を非同期にしない）を反映し、**案E-1（Pub/Sub → GCS サブスク）を推奨に格上げ**して全面改稿。クライアントライブラリ（`AnalyticsLogger` + `JsonlSink`）に `PubSubSink` を足し env で sink を選ぶ設計に。案B は代替へ降格 |
