# PROPOSAL-0012: stock-analysis-agent ユーザー別マイリスト (ウォッチリスト)

| | |
|---|---|
| **Status** | Implementing |
| **Author** | @sakamoto-family-smile |
| **Created** | 2026-06-13 |
| **Updated** | 2026-06-13 |
| **Target** | stock-analysis-agent |
| **Related PRs** | 実装 (本ブランチ) |
| **Supersedes** | — |
| **Superseded by** | — |

---

## 1. Summary

stock-analysis-agent に **ユーザーごとのマイリスト (ウォッチリスト)** を追加する。LINE
から銘柄を**追加・削除・一覧**でき、さらに**マイリストを対象にスクリーニング**できる。

現状の「おすすめ / スクリーニング」は `data/universe/*.json` の固定銘柄が対象で
全ユーザー共通。本提案は PROPOSAL-0011 で導入済みの **`user_id` (LINE userId) +
shared Cloud SQL** を活用し、銘柄選択をパーソナライズする。

## 2. Motivation

- スクリーニング/おすすめの対象が固定で、ユーザーが「自分の気になる銘柄」を追えない。
- PROPOSAL-0011 完了で **LINE userId が全リクエストで取得でき、Cloud SQL も稼働中**。
  パーソナライズの基盤が揃っている。
- 家族/友人に展開する前提 (PROPOSAL-0011 §allow-list) があり、各自のリストを持てると
  価値が上がる。

### 2.1 Goals

- [ ] LINE から `追加 <銘柄>` / `削除 <銘柄>` で**マイリストを編集**できる
- [ ] `追加` は**企業名でもティッカーでも**指定でき、曖昧な企業名は既存の候補提示
      フロー (PROPOSAL-0011 P3) を再利用して確定させる
- [ ] `マイリスト` で**一覧を表示**し、各銘柄から**分析・削除**できる
- [ ] `スクリーニング マイ` で**マイリストを対象に短期上昇候補をスクリーニング**できる
- [ ] マイリストは **user_id ごとに分離**され、shared Cloud SQL に永続化される

### 2.2 Non-Goals

- おすすめ (ETF) のパーソナライズ (本提案はスクリーニング/分析の対象銘柄に限定)
- 銘柄の自動推薦・通知 (アラートは別 proposal)
- マイリストの共有 / グループ機能
- 動的ユニバース取得 (Finnhub 連携・指数構成の自動更新は別途、§7 案で言及)

---

## 3. Proposal

### 3.1 データモデル

新規テーブル `watchlist` (shared Cloud SQL、core スキーマに統合):

| 列 | 型 | 説明 |
|---|---|---|
| `id` | int PK autoinc | |
| `user_id` | str (index) | LINE userId |
| `ticker` | str | 正規化済みティッカー (例: `7203.T`, `AAPL`) |
| `name` | str \| null | 表示用の解決済み企業名 |
| `created_at` | str (server_default now) | 追加日時 |
| UNIQUE(`user_id`, `ticker`) | | 同一銘柄の重複登録を防止 |

- SQLAlchemy model `WatchlistItem` を `db_models.py` に追加 + **alembic 0003**。
- dev/sqlite は `init_db` の create_all、prod は alembic で適用 (P2-B と同方式)。

### 3.2 DB アクセス (`services/database.py`)

| 関数 | 振る舞い |
|---|---|
| `add_watchlist_item(user_id, ticker, name) -> bool` | 追加。既存なら False (冪等) |
| `remove_watchlist_item(user_id, ticker) -> bool` | 削除。不在なら False |
| `get_watchlist(user_id) -> list[dict]` | ticker / name / created_at を新しい順 |
| `count_watchlist(user_id) -> int` | 上限チェック用 |

- **上限**: 1 ユーザー 30 銘柄 (`WATCHLIST_MAX_ITEMS`、スクリーニングの yfinance
  バッチ負荷とコスト抑制)。超過時は追加を拒否して案内。

### 3.3 LINE コマンド

| コマンド (alias) | 動作 |
|---|---|
| `追加 <銘柄>` (`銘柄追加` / `ウォッチ` / `watch`) | 解決 → マイリストに追加。曖昧な企業名は**候補提示**(タップで `追加 <ticker>` 送信) |
| `削除 <銘柄>` (`銘柄削除` / `unwatch`) | 解決 → マイリストから削除 |
| `マイリスト` (`リスト` / `watchlist` / `お気に入り`) | 一覧を Flex 表示。各行に **分析 / 削除** ボタン + 下部に **スクリーニング** ボタン |
| `スクリーニング マイ` (`マイ` / `my`) | **マイリストを対象にスクリーニング** (既存スクリーナー流用) |

- `追加`/`削除` の銘柄解決は既存 `resolve_ticker` を再利用:
  - 高確度 (regex / 辞書) → そのまま確定
  - 低確度 (yfinance/LLM 相当) → `ticker_candidates_bubble` を**コマンド可変化**
    (`分析` → `追加`) して候補提示
- マイリスト操作は **DB のみで LLM を呼ばない** → レート制限の対象外。allow-list は
  従来どおり適用 (家族以外は黙殺)。

### 3.4 スクリーナー連携

`ScreenerRequest` に `tickers: list[str] | None = None` を追加。`run_screener` は
`tickers` 指定時はそれを universe とし (固定 JSON の代わり)、`market` はラベル
(`"MY"`) として扱う。既存のスコアリング/ランキングはそのまま。

### 3.5 主要モジュール変更

| 区分 | 変更 |
|---|---|
| `services/db_models.py` | `WatchlistItem` model |
| `alembic/versions/0003_watchlist.py` | テーブル作成 |
| `services/database.py` | add / remove / get / count 関数 |
| `models/stock.py` | `ScreenerRequest.tickers` |
| `agents/screener.py` | `tickers` 指定時はそれを universe に |
| `services/line_flex.py` | `watchlist_bubble` 追加 + `ticker_candidates_bubble` に command 引数 |
| `services/line_handler.py` | トークン + `追加`/`削除`/`マイリスト` ハンドラ + `スクリーニング マイ` 分岐 + ヘルプ追記 |

### 3.6 実行経路

マイリスト操作・`スクリーニング マイ` はいずれも **webhook 内で同期実行** (Reply)。
分析 (Cloud Tasks→worker) のような非同期は不要 (DB / yfinance のみで軽量)。webhook
は既に DB 接続済 (PROPOSAL-0011 P2-B)。

---

## 4. Design Details

### 4.1 アーキテクチャ (Before / After)

```
Before: スクリーニング対象 = data/universe/{jp,us,growth}.json (全ユーザー共通・固定)

After:
  追加 トヨタ → resolve → watchlist(user_id, 7203.T, トヨタ) INSERT
  マイリスト   → SELECT ... WHERE user_id=? → Flex 一覧 (分析/削除/スクリーニング)
  スクリーニング マイ → watchlist の tickers → run_screener(tickers=...) → 上位候補
```

### 4.2 Risks and Mitigations

| リスク | 影響 | 対策 |
|---|---|---|
| 大量登録で yfinance バッチが重い | 中 | 1 ユーザー 30 銘柄上限 |
| `削除` 等の汎用語が誤マッチ | 低 | Bot 文脈では明確。ヘルプに明記 |
| ticker 解決ミスで意図しない銘柄を登録 | 低 | 低確度は候補提示で確定 (PROPOSAL-0011 と同じガード) |
| 空リストでスクリーニング | 低 | 件数 0 なら追加方法を案内 |

### 4.3 Test Plan

- **Unit**: add/remove/get/count の冪等性・上限・user 分離 (sqlite)。`ScreenerRequest.tickers`
  指定時に universe が差し替わること。`watchlist_bubble` の構造、候補 bubble の command 可変。
- **Integration**: webhook 経由で `追加`/`削除`/`マイリスト`/`スクリーニング マイ` が
  期待どおり Reply すること (StubLineBotClient)。
- **Manual (配備後)**: LINE で 追加→一覧→スクリーニング→削除 の一連。allow-list 外は黙殺。

### 4.4 Migration / Rollback

- alembic 0003 を追加するだけ (既存テーブルへの変更なし)。Rollback は downgrade で
  `watchlist` を drop (他テーブル無影響)。

### 4.5 Feature Enablement

- 追加コマンドは常時有効。`WATCHLIST_MAX_ITEMS` (既定 30) で上限調整。

---

## 5. Operational Concerns

- **Monitoring**: business_event に `watchlist_added` / `watchlist_removed` を emit し、
  利用状況を BQ で追える (PROPOSAL-0011 の analytics 経路に乗る)。
- **Dependencies**: 既存 (Cloud SQL / line-bot-sdk / yfinance)。新規依存なし。
- **コスト**: 追加なし (LLM 不使用。yfinance はスクリーニング時のみ)。

---

## 6. Drawbacks

- コマンド体系が増える (ヘルプで吸収)。
- マイリストのスクリーニングは登録銘柄数に比例して yfinance 呼び出しが増える
  (上限でキャップ)。

## 7. Alternatives

### 案 A: 採用 — DB テーブル + LINE コマンド
- 既存の user_id + Cloud SQL を活用。最小の新規実装でパーソナライズを実現。

### 案 B: おすすめ (ETF) もパーソナライズ
- ETF 版マイリストも持つ。Non-Goal とし、本提案ではスクリーニング/分析に限定。

### 案 C: 動的ユニバース (Finnhub / 指数構成の自動更新)
- 固定 JSON を API/バッチで自動更新する案 (PROPOSAL-0011 §3 で議論した B/C)。
  マイリストとは直交する別軸の改善で、本提案には含めない。

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-06-13 | Implementing | 実装。`WatchlistItem` model + alembic 0003、`database.py` に add/remove/get/count、`ScreenerRequest.tickers` + screener 注入、`line_flex` に `watchlist_bubble` と候補 bubble の command 可変、`line_handler` に 追加/削除/マイリスト + `スクリーニング マイ` 分岐 + ヘルプ追記、business_event(watchlist_added/removed) emit。test 追加 (254 passed)。 |
| 2026-06-13 | Draft | 初稿。PROPOSAL-0011 完了 (user_id + Cloud SQL) を前提に、ユーザー別マイリスト (追加/削除/一覧 + マイリストのスクリーニング) を提案。銘柄指定は企業名/ティッカー両対応 (低確度は候補提示を再利用)。スクリーナーに tickers 注入経路を追加 |
