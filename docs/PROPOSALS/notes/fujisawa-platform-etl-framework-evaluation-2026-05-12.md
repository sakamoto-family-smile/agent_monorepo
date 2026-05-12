# fujisawa-platform ETL フレームワーク再評価

| | |
|---|---|
| **日付** | 2026-05-12 |
| **トリガ** | Phase 4-2g マージ (PR #127)、機能 Job 完了。memory `project_fujisawa_etl_framework` の再評価チェックポイント |
| **判断対象** | 残りの Phase 4-2h (terraform 配備) に進む前に、自前 ETL 実装を継続するか、dbt / Airflow / Dagster へ移行するかを決める |
| **結論** | **現状維持 (Cloud Run Jobs + 自前 `run_etl_job` フレーム) を継続**。理由は §5 / §6 |

---

## 1. 評価の背景

Phase 4-2 開始時 (2026-05-10、PR #120 マージ時) にユーザーから「将来は dbt / スケジューラフレームワーク導入で実装コストを下げる選択肢もある」という示唆あり。Phase 4-2 を自前実装で完走 (7 Job + 6 Repo + 4 parser + PdfArchive + 共通ランナー) した今が、移行 vs 継続を再評価する自然なチェックポイント。

判断材料が固まった今、再評価する。

---

## 2. 現状実装の整理

### 2.1 完成した部品

| 種類 | コンポーネント | 行数概算 |
|---|---|---|
| 共通ランナー | `etl/_runner.py` (run_etl_job + etl_runs 記録 + fail-fast + skip-unchanged) | ~160 |
| Repo (6) | `etl_runs` / `facilities` / `vacancy` (+ application) / `admission` / `pdf_documents` / `competition_stats` | ~700 |
| Parser (4) | `facility_parser` / `admission_parser` / `vacancy_parser` / `min_index_parser` | ~480 |
| PdfArchive | Protocol + GcsArchive / LocalArchive / NullArchive + archive_path + factory | ~270 |
| ETL Job (7) | weekly_crawl / half_yearly_facility / biyearly_admission / monthly_vacancy / yearly_navi / monthly_stats_compute / wayback_backfill | ~1,200 |
| 補助 | facility_resolver_builder / stats_compute / config / _html / _html_table | ~400 |
| **合計** | | **~3,200 行** |

テスト: **420 件 + 1 skipped** (Docling 環境依存)

### 2.2 `run_etl_job` がカバーしている責務

proposal 0003 §4.5.6 由来:
- `etl_runs` への started / finished / status 記録
- 直近 5 件 failed なら fn を呼ばずに fail-fast
- `probe()` の source_hash が前回 success と一致なら `skipped_unchanged`
- fn 内例外を捕捉して `<ClassName>: <message>` 形式で記録

これらは Airflow / Dagster の標準機能と重複する領域。

### 2.3 残作業 (Phase 4-2h 以降)

- **Phase 4-2h**: terraform で Cloud Run Jobs 7 + Cloud Scheduler 6 + Secret Manager + IAM
- **Phase 5**: analytics-platform 計装 + Cloud Monitoring アラート

---

## 3. 検討候補

| 案 | 概要 |
|---|---|
| **A** | **現状維持** (Cloud Run Jobs + 自前 `run_etl_job` フレーム) |
| **B** | **Cloud Composer (Managed Airflow)** + 既存 Python コード資産は再利用 |
| **C** | **Dagster (Cloud / Self-hosted)** + asset 中心のモデル |
| **D** | **dbt-core / dbt Cloud** で `monthly_stats_compute` のみ SQL transformation 化 (ハイブリッド) |

---

## 4. 軸別比較

### 4.1 機能適合性 (我々の 7 Job との fit)

| 軸 | A 現状維持 | B Cloud Composer | C Dagster | D dbt ハイブリッド |
|---|---|---|---|---|
| HTML / PDF fetch + parse (Python ライブラリが中核) | ◎ そのまま | ○ KubernetesPodOperator / PythonOperator で呼出 | ◎ Python ネイティブ、既存コード資産そのまま使える | × SQL 主体で不向き |
| `monthly_stats_compute` (集計のみ) | ○ Python で書いた | ○ Python operator | ◎ asset で competition_stats を宣言できる | ◎ dbt model にぴったり |
| 依存関係 (`monthly_stats_compute` は `monthly_vacancy` の後) | △ Cloud Scheduler の時刻調整で表現 (緩い) | ◎ DAG で明示 | ◎ asset graph で明示 | △ dbt 単独では完結しない |
| `wayback_backfill` の一度きり実行 | ◎ trigger を手動 invoke | ◎ 同上 (manual DAG run) | ◎ 同上 | × dbt は seed 程度 |
| Docling / Vertex Embedding 連携 | ◎ そのまま | ◎ image に同梱 | ◎ Python ネイティブ | × 連携経路がない |

### 4.2 コスト

| 軸 | A 現状維持 | B Cloud Composer | C Dagster | D dbt ハイブリッド |
|---|---|---|---|---|
| 月額 baseline | Cloud Run Jobs 実行分のみ (~\\$1-5) | **~\\$300+ / 月** (Composer Environment 維持費) | Dagster Cloud \\$10-200 (slot 制) / self-host は GKE 等で \\$50+ | dbt Cloud Developer \\$0 (1 dev seat) ~ Team \\$100/seat |
| 移行工数 | 0 | 高 (DAG 化 + image 整備 + worker 環境) | 中 (asset 宣言 + dagster.yaml + sensors) | 中 (`competition_stats` SQL 書き直し、他 6 Job は別途) |
| 学習コスト | 0 (既知) | 高 (Airflow operator / pool / connection / sensor) | 中 (asset / op / job の概念) | 低〜中 (SQL + Jinja) |
| 既存テスト資産の維持 | ◎ そのまま | △ DAG テストは別の書き方 | ○ Python テストは流用可能、asset テスト追加 | △ Python テストは継続、SQL テストは別 |

### 4.3 運用性 (本 PR で評価上重要)

| 軸 | A 現状維持 | B Cloud Composer | C Dagster | D dbt ハイブリッド |
|---|---|---|---|---|
| 観測性 (UI / 実行履歴) | × `etl_runs` テーブル直 SQL or Cloud Logging 経由 (Phase 5 で計装予定) | ◎ Airflow UI 標準搭載 | ◎ Dagster UI 標準搭載 (timeline / asset materializations) | △ dbt の部分のみ Cloud Console |
| Retry / Alert | △ 自前 (5 連敗 fail-fast 実装済、Slack 通知は Phase 5) | ◎ on_failure_callback / SLA / email + Slack | ◎ sensor + RetryPolicy | △ dbt run のリトライのみ |
| ローカル開発 | ◎ `uv run pytest` で完結、external dep 0 | △ `docker compose up` で Airflow 起動が必要 | ◎ `dagster dev` で UI 即起動 | ◎ `dbt run` ローカル可 |
| GCP 統合度 | ◎ Cloud Run Jobs ネイティブ、Workload Identity 直結 | ◎ Composer は GCP マネージド | ○ GKE / Cloud Run on GKE 経由 | ○ BigQuery / Cloud SQL 経由 |

### 4.4 lock-in / 将来拡張

| 軸 | A 現状維持 | B Cloud Composer | C Dagster | D dbt ハイブリッド |
|---|---|---|---|---|
| ベンダー lock-in | 低 (Cloud Run Jobs は標準的) | 中 (Composer は GCP のみ) | 低〜中 (Dagster は OSS、Cloud は別途) | 低 (dbt-core は OSS) |
| 他自治体への展開 (茅ヶ崎 / 横浜) | ○ 同パターンで `chigasaki-platform` 新設 (3,200 行 × 自治体数) | ◎ DAG をテンプレ化して共有 | ◎ asset partitioning で自治体軸を切れる | △ SQL model は流用しやすいが取り込み層は別 |
| Job 数増加耐性 (7 → 15+) | △ 共通ランナーが薄いので、追加ごとに同じ pattern を書く必要 | ◎ DAG ファイル追加だけ | ◎ asset graph 拡張 | ○ model 追加だけ |

---

## 5. 評価

### 5.1 我々の規模感での適合性

- **Job 数 7** (うち 1 は一度きり) は小規模。Cloud Composer の baseline \\$300+/月 はオーバースペック
- 依存関係は実質 **`monthly_stats_compute` が `monthly_vacancy` の翌日に走る** という 1 ペアのみ。Cloud Scheduler の時刻調整で十分表現可能 (現状 22 日 / 23 日でずらしている)
- 観測性は Phase 5 で `etl_runs` テーブル + analytics-platform 計装で対応する計画。**自前で観測層を作るコスト < フレーム導入コスト** の状況

### 5.2 既に投じたコストと残作業

- 完成: 3,200 行 + 420 tests (沈没コスト)
- 残: terraform (Phase 4-2h) + observability (Phase 5)
- **terraform は Cloud Run Jobs / Cloud Scheduler が前提なので A 継続前提で書ける**
- フレーム移行する場合、terraform を後で書き直すリスクあり

### 5.3 ベンダー lock-in / 拡張性

- 他自治体 (茅ヶ崎 / 横浜) への展開は proposal §3.5 で「将来 Phase 5+ で検討」とされており、本 PR の判断対象外
- 現実装は Python ライブラリ + Cloud Run Jobs の組合せで lock-in 軽い

### 5.4 失敗シナリオの再評価

memory 書込時の想定: 「Job が 7 個に拡大した時点で自前メンテのコスト > 移行コスト」

実装してみて分かったこと:
- 7 Job のうち **集計ロジックは 1 つだけ** (`monthly_stats_compute`)、他 6 つは取得 + parse 系 (Python ライブラリの組合せが本体)
- 共通フレーム (`run_etl_job` ~ 160 行) は Job 追加時にコピペで使い回せている
- Parser がパターン化 (HTML テーブル / Docling 表 / min_index) されており、新規追加でも 1 PR で完結

つまり「Job 数の線形増加が問題」ではなく「Parser の多様化」が問題で、これはフレーム移行では解決しない。

---

## 6. 結論

**A (現状維持) を選択**

### 6.1 理由 (要約)

1. **規模感**: 7 Job + 1 依存ペアでは Composer / Dagster は過剰投資
2. **コスト**: A は月 \\$5 程度、B は月 \\$300+
3. **既存資産**: 3,200 行 + 420 tests がそのまま動き、テスト容易性が高い
4. **observability ギャップは Phase 5 で埋まる**: フレーム移行で得られる UI は、Phase 5 の analytics-platform 計装 + Cloud Monitoring で 80% 達成可能
5. **Parser の多様化問題はフレーム移行では解決しない**

### 6.2 再評価の条件 (将来トリガ)

以下のいずれかが起きたら **再評価する**:

| トリガ | 理由 |
|---|---|
| 他自治体への展開 (茅ヶ崎 / 横浜) で **3 自治体以上** に拡大 | DAG テンプレ化 + asset partitioning の恩恵が出る |
| **Job 数が 15+** に増える | 自前ランナーのメンテコストが効いてくる |
| 複雑な依存関係 (3+ Job の sequential / conditional) が出現 | Cloud Scheduler 時刻調整では破綻 |
| 観測性に **「実行 timeline / asset graph UI」レベルの要件** が発生 | 自前で Cloud Run logs から組み立てるのは現実的でない |

### 6.3 Phase 4-2h / 5 への影響

- **Phase 4-2h**: 現実装前提で Cloud Run Jobs + Cloud Scheduler の terraform を素直に書く。proposal §4.5.4 の Job 表で実装方式に注記不要 (もともと自前前提)
- **Phase 5**: `etl_runs` テーブル + analytics-platform 計装で observability を補強。Slack 通知は proposal §4.5.6 を実装

### 6.4 部分採用 (D dbt のみ)

`monthly_stats_compute` だけ dbt model 化する選択肢は技術的には可能だが、

- 集計対象テーブル (admission_results) も自前 ETL で書き込んでいる → dbt model がデータの一部しか扱わない
- 運用が「Python ETL + dbt」の 2 経路に分裂、トラブルシューティングが面倒

→ **不採用**。Python の `stats_compute.py` (pure 関数 + テスト 27 件) で十分。

---

## 7. memory への反映

`memory/project_fujisawa_etl_framework.md` を更新:
- 「Phase 4-2 完了時に再評価する」状態 → 「2026-05-12 に再評価済、現状維持を選択」に書き換え
- 再評価条件 (§6.2) を載せる
- 再再評価のチェックポイントは: 他自治体展開、Job 数 15+、複雑な依存関係出現、UI 要件発生のいずれか

---

## 8. 関連ドキュメント

- [proposal 0003 §4.5.4](../0003-fujisawa-platform-shared-base.md) — ETL Job 表
- [proposal 0003 §4.5.6](../0003-fujisawa-platform-shared-base.md) — 失敗時 handling (5 連敗 fail-fast / Slack 通知)
- 関連 PR: #120 (4-2a)、#121 (4-2b)、#122 (4-2c)、#123 (4-2c-2)、#124 (4-2d)、#125 (4-2e)、#126 (4-2f)、#127 (4-2g)
