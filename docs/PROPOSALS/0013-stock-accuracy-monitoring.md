# PROPOSAL-0013: stock-analysis-agent 予測精度モニタリングと改善ループ（市場データ蓄積基盤を含む）

| | |
|---|---|
| **Status** | In Review |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-10-08 |
| **Updated** | 2026-10-15 |
| **Target** | stock-analysis-agent（+ analytics-platform の BigQuery / dbt） |
| **Related PRs** | (none yet) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

stock-analysis-agent の出力（価格予測バンド、LLM の強気／中立／弱気判断、スクリーナーの順位）を
**後から実績と突き合わせられる形で記録**し、精度をメトリクスとして継続的に計測する。
そのための土台として、株価・指数・財務・需給の**時点固定（point-in-time）の履歴を BigQuery に日次バッチで蓄積**する。

計測できるようになったら、「変更 → 評価 → 採用／却下」を回す**改善ループ（ループエンジニアリング）**を
3 つの速度（リプレイ／ウォークフォワード／前向き検証）で運用する。判定はノイズを最適化しないよう、
事前に決めた主指標・ガードレール・最低サンプル数・ループが触らない検証期間で行う。

## 2. Motivation

現状は精度を測る土台がない。

- **予測が評価できる形で残っていない**：レポートは自由文のまま `reports.report_data` に保存されている
  （`app/agents/orchestrator.py` の `save_report`）。判断・確率・予測バンド・入力データの基準日が構造化されていない。
- **履歴データを持っていない**：日次バッチは EDINET の書類インデックス（`app/batch/edinet_index_etl.py`、
  毎日 02:00 JST、Cloud SQL `edinet_documents`）だけ。株価は `price_cache`（TTL 24 時間）に
  リクエスト時に入るだけで、履歴は残らない。有報の PDF/XBRL も分析時に取得して GCS にキャッシュするだけで、
  抽出した財務数値は保存していない。
- **yfinance の `.info` は時点固定ではない**：過去時点で何が分かっていたかを再現できず、バックテストに先読みバイアスが入る。
- **予測ロジックに既知の問題がある**（§3.2）。

放置すると、プロンプトやロジックを変えても良くなったのか悪くなったのか判断できず、改善が勘頼みになる。

### 2.1 Goals

- [ ] 予測（判断・確率・バンド・スクリーナーのスコア）を `predictions` に構造化して記録し、期間経過後に実績を自動で突き合わせる
- [ ] 株価・指数・財務・需給を BigQuery に日次で蓄積し、時点固定の履歴でバックテストできる
- [ ] §4.5 のメトリクスを dbt mart として算出し、ダッシュボードで推移を確認できる
- [ ] 現行版と新版を同じ日・同じ銘柄で並行評価（チャンピオン／チャレンジャー）し、事前に決めた基準で採否を判定できる
- [ ] 予測モデルの既知のバグ（ドリフトの二重補正、祝日カレンダー）を修正する

### 2.2 Non-Goals

- 自動売買・発注（承認フロー、証券会社 API 連携）は対象外。別提案で扱う
- 分足・ティックなど日中データの取得
- 改善ループの完全自動化（Claude が自律的にコードを変えてマージするところまで）。本提案では判定基準と計測基盤までとし、変更の採否は人が承認する
- 配当（インカムゲイン）戦略の評価。キャピタルゲインに集中する

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 精度の確認
> 毎週、ダッシュボードで「先月のスクリーナー上位 10 銘柄は、21 営業日後に TOPIX を平均で何%上回ったか」
> 「予測バンド P10〜P90 に実績が入った割合は 80% に近いか」を確認する。

#### 3.1.2 変更の採否判定
> プロンプトを改善した新版を 4 週間、裏側で現行版と並行して動かす。Rank IC の差の信頼区間が 0 を含まず、
> ガードレール指標が悪化していなければ新版に切り替える。

### 3.2 Notes / Constraints / Caveats

**予測モデルの既知の問題（P0 で修正）**

| 箇所 | 問題 | 影響 |
|---|---|---|
| `app/agents/forecast.py:126,140` | `mu` は対数リターンの平均で、すでに μ−σ²/2 にあたる。そこから `drift = mu - 0.5σ²` でさらに σ²/2 を引いている | P50 が −hσ²/2 だけ下に偏る（σ=日次 2%、21 日で約 −0.4%、σ=4% で約 −1.7%）。数式からの導出値 |
| `forecast.py:126` + 分析期間の既定値 `3mo` | 約 62 日分から μ を推定しており、21 日換算で ±5% 程度の推定誤差 | 中央値の方向が事実上ランダム。ドリフトは 0 にするか小さく縮める |
| `forecast.py` | σ が一定の正規分布 | ファットテールや、ボラティリティが時期によって固まる性質を表現できない |
| `forecast.py` の `_next_business_days` | 東証の祝日を考慮していない | 予測の対象日がずれる |
| `app/agents/technical_analysis.py:72-73` | RSI を単純移動平均で計算（Wilder の平滑化ではない） | 一般に公表される RSI と値がずれる（軽微） |

**評価上の制約**

- **LLM の判断はバックテストできない**：モデルの学習データに過去の結果が含まれるため、過去日付で評価すると先読みになる（Glasserman & Lin 2023）。LLM の判断は前向き検証（記録して待つ）だけで評価する。
- **ユニバースが小さい**：`data/universe/jp.json` は 50 銘柄。日々の IC のばらつきが大きく（標準偏差およそ 0.15）、IC 0.03 程度の差を検出するには重ならない期間が約 100 回分必要になる（目安の試算）。ユニバースを 500 銘柄程度に広げると、必要な期間はおよそ 1/3〜1/4 になる。
- **J-Quants の Free プランは直近 12 週間を取得できない**ため、日々の運用には Light 以上が必要。データの保存・利用は利用規約の範囲（個人利用、再配布しない）で行う。規約は導入時に確認する。

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 改善ループがノイズを最適化する（偶然良く見えた変更を採用する） | High | 試行回数をすべて記録し、Deflated Sharpe 等で有意水準を補正。ループが見ない検証期間を確保。最低サンプル数に達するまで判定しない |
| 先読みバイアス（財務データを開示前の日付で使う、上場廃止銘柄の欠落） | High | 財務は開示日時（`disclosed_at`）を基準に結合。銘柄一覧を日次スナップショットで保存し、上場廃止銘柄も残す |
| 外部 API の仕様変更・停止（特に yfinance） | Medium | 生データを GCS に保存してから取り込む。J-Quants を日本株の主ソースにし、yfinance は補助にする |
| データ提供元の利用規約違反（保存・再配布） | Medium | 個人利用の範囲に限定し、BigQuery のデータを外部公開しない。導入前に規約を確認 |
| BigQuery のコスト超過 | Low | テーブルを日付で分割し銘柄でクラスタリング。dbt mart は増分更新。想定データ量は十数 GB 以下（§5.4） |
| 評価結果を「投資判断の保証」と誤解される | Medium | ダッシュボードとレポートに、統計的評価であり投資助言ではない旨を明記 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
[日次バッチ: Cloud Run Job + Cloud Scheduler]   ← edinet_index_etl と同じ構成
  market_data_etl (JP 18:30 JST / US 07:30 JST)
    J-Quants / yfinance / EDINET(XBRL) ──→ GCS (生データ JSON, 日付別)
                                        └─→ BigQuery `market_raw` (MERGE で冪等)
  prediction_eval (毎日 08:00 JST)
    期間が経過した predictions × 実績株価 ──→ `prediction_outcomes`

[オンライン: stock-analysis-agent]
  分析・スクリーニング ──→ predictions を記録（Cloud SQL → 日次で BigQuery へ同期）
                       ──→ 株価・財務は BigQuery から読む（失敗時は従来の API にフォールバック）

[分析: analytics-platform の dbt]
  market_raw + predictions + prediction_outcomes
    → staging → marts (mart_forecast_calibration / mart_signal_ic / mart_llm_stance / mart_guardrails)
    → ダッシュボード（Looker Studio など）
```

### 4.2 データモデル

**BigQuery `market_raw` データセット**（location は analytics-platform に合わせる。日本株中心なら `asia-northeast1` も検討）

| テーブル | キー | 内容 | ソース |
|---|---|---|---|
| `daily_prices` | (date, ticker) | 調整前後の OHLCV、調整係数 | J-Quants（JP）、yfinance（US） |
| `index_prices` | (date, index_code) | TOPIX、業種別指数、S&P500、セクター ETF | J-Quants / yfinance |
| `listed_info_snapshot` | (snapshot_date, ticker) | 銘柄一覧（市場区分、業種）。上場廃止銘柄も残す | J-Quants |
| `fin_summary` | (ticker, disclosed_at, period) | 決算短信ベースの実績と会社予想 | J-Quants |
| `edinet_financials` | (document_id) | XBRL から抽出した財務数値（既存の `parse_xbrl_zip` の出力）と `submit_date` | EDINET |
| `earnings_calendar` | (ticker, announce_date) | 決算発表予定日 | J-Quants |
| `margin_interest` / `short_selling` | (date, ticker or sector) | 信用残、空売り比率（プランによる） | J-Quants |
| `fundamentals_snapshot` | (snapshot_date, ticker) | yfinance `.info` の日次スナップショット（US 用。時点固定の履歴を自前で作る） | yfinance |

すべてのテーブルに `ingested_at` と `source` を持たせる。日付で分割し、ticker でクラスタリングする。

**`predictions`**（Cloud SQL に記録し、日次で BigQuery に同期する）

| カラム | 説明 |
|---|---|
| `prediction_id` | UUID |
| `kind` | `forecast_band` / `llm_stance` / `screener_score` / `ml_rank` |
| `variant` | `champion` / `challenger:<name>` |
| `ticker`, `as_of_date` | 対象銘柄と基準日（入力データの最終日） |
| `horizon_days` | 5 / 21 |
| `benchmark` | `TOPIX` / `SPX` など |
| `stance`, `prob_up` | LLM の判断と確率（`llm_stance` のみ） |
| `score` | スクリーナーや ML のスコア |
| `bands` | P10〜P90（JSON、`forecast_band` のみ） |
| `report_id` | `reports` への参照（あれば） |
| `model_id`, `prompt_version`, `code_version` | 何で出した予測か |
| `input_hash` | 入力データのハッシュ（リプレイ用） |
| `created_at` | 記録日時 |

**`prediction_outcomes`**（BigQuery）：`prediction_id`, `realized_price`, `realized_return`,
`benchmark_return`, `excess_return`, `pit`（予測分布上の位置）, `in_band_80`, `in_band_50`, `evaluated_at`

### 4.3 API

- LLM の出力を構造化する：`AnalysisReport` に `stance`（bullish/neutral/bearish）、`prob_up`、`horizon_days`、`key_drivers[]` を追加し、JSON スキーマで出力させる。既存の自由文レポートはそのまま残す。
- 新規エンドポイントは追加しない。メトリクスはダッシュボードで見る。

### 4.4 主要モジュール

| 追加・変更 | 内容 |
|---|---|
| `app/agents/forecast.py` | ドリフトの二重補正を修正。ドリフト 0／縮小をオプション化。σ 推定期間を伸ばし EWMA／GARCH を選べるようにする。東証カレンダーを使う |
| `app/batch/market_data_etl.py`（新規） | J-Quants／yfinance／EDINET から取得 → GCS に生データ → BigQuery に MERGE |
| `app/batch/prediction_eval.py`（新規） | 期間が経過した予測を実績と突き合わせて `prediction_outcomes` に書く |
| `app/services/prediction_log.py`（新規） | 予測を `predictions` に記録する |
| `app/services/market_store.py`（新規） | BigQuery から株価・財務を読む。失敗時は既存の `data_collection` にフォールバック |
| `app/agents/orchestrator.py` | 構造化出力、予測の記録、`variant` を受け取ってチャンピオン／チャレンジャーを並行実行 |
| `analytics-platform/dbt/models/` | §4.5 の mart を追加 |
| `stock-analysis-agent/terraform/` | Job と Scheduler を 2 つ追加、BigQuery のデータセットと IAM、J-Quants の API キー（Secret Manager） |

### 4.5 メトリクス定義

**目標の分解**（Grinold の基本法則：情報比 ≒ IC × √判断する銘柄数）

```
最終目標: ベンチマーク超過リターン（手数料・税控除後）／情報比
  ├─ IC ……… 予測の当たり具合    ← ループの主な判定指標
  ├─ 銘柄数 … ユニバースの広さ   ← J-Quants でユニバース拡大
  └─ コスト … 売買回転率 × コスト ← ガードレール
```

**主指標（変更の採否判定に使う）**

| 対象 | 指標 | 定義 |
|---|---|---|
| スクリーナー／ML | Rank IC, ICIR | 日ごとに、スコアと 5／21 営業日先の対ベンチマーク超過リターンの Spearman 相関。ICIR = 平均 IC ÷ IC の標準偏差 |
| 予測バンド | CRPS スキル | 1 − CRPS(モデル) ÷ CRPS(ドリフト 0 のランダムウォーク) |
| 予測バンド | 区間の的中率誤差 | \|P10〜P90 に入った割合 − 0.8\|、\|P25〜P75 に入った割合 − 0.5\| |
| LLM の判断 | Brier スキルスコア | 1 − Brier(モデル) ÷ Brier(過去の上昇割合を常に答える予測) |

**補助指標（傾向の把握）**

- 予測バンド：PIT ヒストグラム、バンド幅（シャープネス）、Kupiec／Christoffersen 検定
- LLM：判断の的中率（超過リターン基準）、信頼度曲線、同一入力での判断一致率
- スクリーナー：上位 N 銘柄とユニバース全体の超過リターン差、シグナルごとの寄与
- 最終指標：上位 N 銘柄を等金額で持った場合の超過リターンと情報比（手数料・税控除後）。ループが触らない検証期間で四半期ごとに確認

**ガードレール（悪化したら不採用）**

| 指標 | 基準 |
|---|---|
| 数値の不一致率（レポート中の数値とプロンプトに渡したデータの食い違い） | 0 件を維持 |
| 必須要素の欠落（免責文、ニュースの日付と出典） | 0 件を維持 |
| データの鮮度（最新株価の日付 ＝ 直近営業日か）、欠損率 | 現行版以上 |
| 1 レポートあたりのコスト、処理時間 | 現行版の +20% 以内 |
| 売買回転率（推奨銘柄の入れ替わり） | 現行版の +20% 以内 |

### 4.6 改善ループの運用

| ループ | 速さ | 変える対象 | 判定 |
|---|---|---|---|
| 速い（リプレイ） | 数分〜数時間 | プロンプト、出力スキーマ | `input_hash` で保存した入力を再実行し、ガードレールと一貫性を確認。リターンは見ない |
| 中くらい（ウォークフォワード） | 数時間〜数日 | 予測モデル、スクリーナーのルール、ML の特徴量 | BigQuery の時点固定データで IC と CRPS を測る。時系列を考慮した交差検証（Purged/Embargo）。LLM は含めない |
| 遅い（前向き検証） | 数週間〜数か月 | 上で合格した変更、LLM の判断 | チャンピオンとチャレンジャーを同じ日・同じ銘柄で記録し、差を対にして検定（DM 検定、IC 差のブロックブートストラップ信頼区間） |

**採用基準**

1. 主指標の改善が対にした検定で有意（p < 0.05、または信頼区間が 0 を含まない）
2. ガードレールがすべて維持されている
3. 事前に決めた最低サンプル数に達している（例：5 日先なら重ならない 20 期間以上）
4. 試行回数を記録し、試行回数に応じて有意水準を補正している

**ループが見ない検証期間**：直近 3 か月はループの判定に使わず、四半期に 1 回だけ最終指標の確認に使う。

### 4.7 Test Plan

- **Unit**
  - `forecast.py`：平均対数リターン 0 の系列で P50 の終値が起点価格とほぼ一致すること（ドリフト修正の回帰テスト）。祝日が予測日に含まれないこと
  - メトリクス計算（Rank IC、CRPS、PIT、Brier、区間の的中率）を既知の値の小さな例で検証
  - `prediction_eval`：期間が未経過の予測は評価しない。休場日をまたぐ期間を正しく数える
  - 先読み防止：`fin_summary` を基準日で結合したとき、`disclosed_at` が基準日より後の行が含まれないこと
- **Integration**
  - `market_data_etl` を BigQuery エミュレータまたはテスト用データセットで実行し、2 回実行しても行が重複しない（冪等）こと
  - オーケストレーター経由で分析したとき、`predictions` に構造化された行が記録されること
- **Manual / E2E**
  - [ ] 本番で 1 週間バッチを動かし、欠損日がないことを確認
  - [ ] 21 営業日後に `prediction_outcomes` が埋まり、dbt mart が計算されることを確認
  - [ ] ダッシュボードで主指標とガードレールが表示されることを確認

### 4.8 Migration / Rollback

- **Migration**：Alembic `0004_predictions`（`predictions` テーブル追加）。BigQuery のデータセット・テーブルは Terraform で作成
- **Rollback**：`FORECAST_DRIFT_MODE` などの env で旧挙動に戻せる。`predictions` の記録は env で停止できる。Alembic は downgrade でテーブル削除（BigQuery 側のデータは残す）
- **既存ユーザー影響**：レポート本文は変わらない（ドリフト修正で予測バンドの数値はわずかに上方へ動く）

### 4.9 Feature Enablement

- `MARKET_STORE_ENABLED`：BigQuery から読むか（false なら従来どおり API）
- `PREDICTION_LOG_ENABLED`：予測を記録するか
- `CHALLENGER_VARIANTS`：並行実行するチャレンジャー（空なら現行版のみ）
- `FORECAST_DRIFT_MODE`：`zero` / `shrink` / `historical`
- `JQUANTS_API_KEY`：未設定なら日本株も yfinance で取得（機能を縮小して継続）

---

## 5. Operational Concerns

### 5.1 Monitoring

- バッチ：Cloud Run Job の成功／失敗、取り込み件数（`ingested_rows`）を analytics-platform の business_event として送る
- データ鮮度：`max(date)` が直近営業日でなければ Cloud Monitoring でアラート
- 精度：dbt mart（`mart_forecast_calibration` / `mart_signal_ic` / `mart_llm_stance` / `mart_guardrails`）をダッシュボードで週次確認

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| 特定日の株価が欠損 | 休場日か取得失敗。生データの GCS を確認し、日付指定で再取得 |
| IC が急に変動 | ユニバースの変更や、株式分割の調整漏れ。`listed_info_snapshot` と調整係数を確認 |
| 的中率が名目値から大きくずれる | ボラティリティの急変。σ 推定窓を確認。区間の自動較正を検討 |

### 5.3 Dependencies

- J-Quants API（JPX）。Light 以上を想定。信用残・空売りは Standard
- yfinance（米国株と補助用途）
- EDINET API v2（既存の `edinet-client`）
- BigQuery、GCS、Cloud Run Jobs、Cloud Scheduler、Secret Manager
- analytics-platform（dbt、イベント送信）

### 5.4 Non-Functional Requirements

#### 性能
- 日次バッチ：日本株全銘柄（約 4,000）の日足を 30 分以内に取り込む（J-Quants のレート制限内）
- オンライン分析での BigQuery 読み取り：2 秒以内。超えたら API にフォールバック

#### コスト
- J-Quants：月 ¥1,650（Light）〜¥3,300（Standard）
- BigQuery：日足 4,000 銘柄 × 250 日 × 10 年 ≈ 1,000 万行（数 GB）。無料枠（ストレージ 10 GB、クエリ 1 TB/月）の範囲を想定
- チャレンジャーの並行実行で LLM コストが最大 2 倍。前向き検証期間中だけ有効にする

#### プライバシー / データ保持
- `predictions` に個人情報は含めない（`user_id` は持たない）
- 市場データは個人利用の範囲で無期限に保持し、外部公開しない

---

## 6. Drawbacks

- 前向き検証は結果が出るまで時間がかかり（21 日先なら最低でも数か月）、効果が見えるまで投資が先行する
- データソースの有料化（J-Quants）で固定費が増える
- 評価の仕組みを作っても、ユニバースが小さいままでは統計的に判断できない（§3.2）

## 7. Alternatives

### 案 A: 必要なときに毎回 API から取得する（現状維持）
- 概要：保存せず、分析やバックテストのたびに API を呼ぶ
- 却下理由：yfinance の `.info` は時点固定でなく過去を再現できない。J-Quants はプランによって取得できる期間に限りがある。レート制限でバックテストが遅い

### 案 B: Cloud SQL（PostgreSQL）に履歴を保存
- 概要：既存の Cloud SQL にテーブルを追加する
- 却下理由：数百万〜千万行の分析クエリには向かず、インスタンスの負荷とコストが増える（PROPOSAL-0009 でインスタンスを集約済み）。dbt やダッシュボードとの連携も BigQuery のほうが既存の analytics-platform と揃う。ただし `predictions` の書き込みはトランザクションが必要なので Cloud SQL に置き、日次で BigQuery に同期する

### 案 C: LLM に精度の自己評価をさせる
- 概要：LLM に過去レポートを読ませて良し悪しを判定させる
- 却下理由：リターンという客観的な結果があるので、それで測るべき。LLM による採点は、数値の忠実性などガードレールの補助にだけ使う

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-10-08 | Draft | 初稿 |
| 2026-10-15 | In Review | 設計レビュー PR 作成 |

### 実装フェーズ案

| フェーズ | 内容 |
|---|---|
| P0 | `forecast.py` のドリフト修正、東証カレンダー、RSI の Wilder 平滑化 |
| P1 | LLM の構造化出力、`predictions` の記録、`prediction_eval`、BigQuery への株価・指数の日次蓄積（yfinance で開始） |
| P2 | dbt mart とダッシュボード（主指標、ガードレール） |
| P3 | J-Quants 導入（日本株の主ソース化、ユニバース拡大、財務・決算日・需給）、`edinet_financials` の蓄積 |
| P4 | チャンピオン／チャレンジャーの並行実行と採否判定の運用開始。σ モデル改善、ML ランキングモデルを裏側で記録 |

---

## Appendix: 参考文献

書誌情報のうち、リンクを付けたものはウェブで確認済み。それ以外は記憶にもとづくため、引用前に確認すること。

**評価・予測**
- Gneiting & Raftery (2007) "Strictly Proper Scoring Rules, Prediction, and Estimation", *JASA* 102(477)
- Gneiting, Balabdaoui & Raftery (2007) "Probabilistic forecasts, calibration and sharpness", *JRSS-B* 69(2)
- Kupiec (1995) *Journal of Derivatives* 3(2) ／ Christoffersen (1998) "Evaluating Interval Forecasts", *International Economic Review* 39(4)
- Diebold & Mariano (1995) "Comparing Predictive Accuracy", *JBES* 13(3)
- Brier (1950) *Monthly Weather Review* 78(1)
- Welch & Goyal (2008) *RFS* 21(4)
- Grinold (1989) "The Fundamental Law of Active Management", *JPM* 15(3) ／ Grinold & Kahn, *Active Portfolio Management*
- Gibbs & Candès (2021) "Adaptive Conformal Inference Under Distribution Shift", arXiv:2106.00170

**過学習・バックテスト**
- White (2000) "A Reality Check for Data Snooping", *Econometrica* 68(5)
- Harvey, Liu & Zhu (2016) "…and the Cross-Section of Expected Returns", *RFS* 29(1)
- Bailey & López de Prado (2014) "The Deflated Sharpe Ratio", *JPM* 40(5)
- López de Prado (2018) *Advances in Financial Machine Learning*, Wiley

**ボラティリティ・分布**
- Cont (2001) *Quantitative Finance* 1(2) ／ Engle (1982) *Econometrica* 50(4) ／ Bollerslev (1986) *J. Econometrics* 31(3)
- Christensen & Prabhala (1998) *JFE* 50(2) ／ Dubinsky et al. (2019) *RFS* 32(2)

**シグナル**
- Gu, Kelly & Xiu (2020) "Empirical Asset Pricing via Machine Learning", *RFS* 33(5)
- Bernard & Thomas (1989) *J. Accounting Research* 27
- Desai et al. (2002) *J. Finance* 57(5) ／ Asquith, Pathak & Ritter (2005) *JFE* 78(2)

**LLM × 金融**
- Lopez-Lira & Tang, "Can ChatGPT Forecast Stock Price Movements?" — [arXiv:2304.07619](https://arxiv.org/abs/2304.07619v6)
- Glasserman & Lin (2023) "Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis" — [arXiv:2309.17322](https://arxiv.org/abs/2309.17322)

**データソース**
- J-Quants API（JPX）— [https://www.jpx.co.jp/markets/other-data-services/j-quants-api/](https://www.jpx.co.jp/markets/other-data-services/j-quants-api/)
