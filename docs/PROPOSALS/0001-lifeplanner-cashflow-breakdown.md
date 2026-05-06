# PROPOSAL-0001: lifeplanner-agent キャッシュフロー粒度向上

| | |
|---|---|
| **Status** | Implemented |
| **Author** | @kurama554101 |
| **Created** | 2026-05-05 |
| **Updated** | 2026-05-07 |
| **Target** | lifeplanner-agent |
| **Related PRs** | [#103](https://github.com/sakamoto-family-smile/agent_monorepo/pull/103) |
| **Supersedes** | — |
| **Superseded by** | — |

> 注: 本 proposal は PR #103 の **後追いドキュメント** として作成された
> (テンプレート初投入時の事例)。通常は実装着手前に Draft で作成する。

---

## 1. Summary

シミュレーション結果に **カテゴリ別生活費の年明細** と **イベント line item** を追加し、
LINE / UI で「月や年ごとに食費・通信費・住居費・出産費用・住宅ローン等が見える」
ようにするバックエンド粒度向上。あわせて JSON ファイルからイベントを一括投入する
seed スクリプト (`scripts/seed_events.py`) を整備。

## 2. Motivation

PR 1 着手前の `agents/simulator.YearRow` は `living_expense` (合計 1 値) と
`event_net` (合計 1 値) しか持たず、UI で「何にいくら使うか」を見せられなかった。
LINE 上で 30 年キャッシュフローの内訳をユーザーに表示するためには、
カテゴリ別 / イベント別の line item を出力するバックエンド改修が必須。

### 2.1 Goals

- [x] `YearRow.expense_breakdown: dict[str, Decimal]` でカテゴリ別年額を出力
- [x] `YearRow.event_breakdown: list[EventLine]` でイベント由来の line item を出力
- [x] 取り込み済 transactions の直近 12 ヶ月から baseline を自動生成 (CSV 取り込み済前提)
- [x] JSON ファイルからイベントを一括投入できる seed スクリプト
- [x] 既存 API レスポンスを破壊しない (追加のみ)

### 2.2 Non-Goals

- カテゴリ別の inflation 率指定 (現状は単一 `inflation_rate` を全カテゴリに適用)
- LINE 上での表示 (PR 2 / PR 3 で実装)
- 月単位プロレート (PR 4 で `start_month` を追加予定)

---

## 3. Proposal

### 3.1 User Stories

#### 3.1.1 家計データ取り込み済の家族
> 家族 A は MF CSV を半年分取り込み済。シナリオを 1 つ作って simulate を回したとき、
> 「2030 年の支出 320 万円のうち、住居費 144 万・食費 80 万・通信費 24 万…」と
> カテゴリ別に内訳が見える。LINE 上の表示やレビューで使う想定。

#### 3.1.2 イベント計画を一括登録したい家族
> 家族 B は出産・住宅・車の 3 イベントを 1 シナリオに追加したい。GUI を作る前に
> JSON で一括投入できれば、`curl` を打たずに済む。
> `python scripts/seed_events.py --scenario-id 1 --file data/seeds/example_events.json`
> の 1 行で 3 イベント追加が完了する。

### 3.2 Notes / Constraints / Caveats

- **時間粒度は年単位**。`start_year` のみで月情報なし。住宅購入が 7 月でも 2028 年に
  12 ヶ月分のローン返済が計上される (30 年合計には影響なし、単年は数十万円ズレうる)。
  月単位プロレートは PR 4 で `start_month` を追加する。
- ベースラインの自動生成は `transactions.amount < 0` (支出) かつ
  `expense_type != 'income'` の集計。`is_transfer / is_target=False` は除外。
- カテゴリ未登録のレコードは `canonical_category="other"` に集約される。
  CSV 取り込みが少ない世帯では年率換算 (`* 365 / lookback_days`) で荒くなる。

### 3.3 Risks and Mitigations

| リスク | 影響度 | 対策 |
|---|---|---|
| 既存 API レスポンスの破壊で UI / LLM advisor が壊れる | High | 追加のみ (`expense_breakdown`, `event_breakdown` を新フィールドで導入)、Pydantic schema を 後方互換 (デフォルト空) で拡張 |
| `expense_baseline_by_category=None` の旧挙動がデグレ | Medium | "other" カテゴリ 1 値に集約してフォールバック、簡易テスト (`test_simulator_breakdown.test_expense_breakdown_falls_back_to_other_category`) で保証 |
| イベント `event_type` が未設定で UI に "?" が出る | Low | `scenario_runner._expand_events` で全イベントに `dataclasses.replace(event_type=...)` を強制、catalog 関数の戻り値が空でも検知できるテスト追加 |

---

## 4. Design Details

### 4.1 アーキテクチャ概略

```
[CSV import]──→ Transaction (canonical_category)
                       │
                       ▼
            services/expense_baseline.py (新設)
            12 ヶ月集計 → ExpenseBaseline (dict)
                       │
                       ▼
[Scenario.base_assumptions.expense_baseline_by_category]
                       │
                       ▼
           agents/simulator.run_projection
                       │
            + agents/event_catalog (CashFlowDelta + event_type)
                       │
                       ▼
              YearRow (breakdown 付き)
                       │
                       ▼
              /api/scenarios/{id}/simulate
              (rows[i].expense_breakdown / event_breakdown)
```

### 4.2 データモデル

DB スキーマ変更なし。`SimulationResultRow.metrics` は JSON カラムなので
内部構造を拡張するだけで足りる。

### 4.3 API

- `/api/scenarios/{id}/simulate` レスポンスの `rows[i]` に追加:
  - `expense_breakdown: dict[str, str]` — カテゴリ → 金額 (Decimal を str)
  - `event_breakdown: list[EventLineOut]` — `{event_type, category, label, amount}` のリスト

### 4.4 主要モジュール

| ファイル | 変更 |
|---|---|
| `app/services/expense_baseline.py` | **新設**。`ExpenseBaseline` dataclass + `compute_expense_baseline()` |
| `app/agents/simulator.py` | `HouseholdProfile` / `YearRow` 拡張、`EventLine` 追加、`run_projection` で breakdown 計算 |
| `app/agents/event_catalog/types.py` | `CashFlowDelta.event_type: str = ""` 追加 |
| `app/services/scenario_runner.py` | `_expand_events` で `dataclasses.replace(event_type=...)` |
| `app/routes/simulate.py` | Pydantic レスポンス拡張 |
| `scripts/seed_events.py` | **新設**。JSON → DB 一括投入 |
| `data/seeds/example_events.json` | **新設**。E01 + E02 + E04 のサンプル |

### 4.5 Test Plan

- **Unit**:
  - `test_simulator_breakdown.py` (10 件): inflation 適用 / 合計整合性 / fallback / 後方互換 / イベント明細
  - `test_expense_baseline.py` (7 件): カテゴリ集計 / income 除外 / transfer 除外 / 年率換算
  - `test_seed_events.py` (6 件): バリデーション / sample JSON
- **Integration**: 既存の `test_scenarios_api.py` / `test_simulator.py` (296 件 → 316 件) が
  後方互換で通ることを確認 (PR 1 完了時点で全 296 件 PASS、内 23 件が新規)
- **Manual**: `make run` でローカル起動、`curl /api/scenarios/{id}/simulate` で
  `rows[0].expense_breakdown` が non-empty であること

### 4.6 Migration / Rollback

- DB スキーマ変更なし → migration 不要
- 既存ユーザー影響: ❌ なし (追加フィールドのみ、既存呼び出し側は無視できる)
- ロールバック: コード revert で完了 (DB に新規データなし)

### 4.7 Feature Enablement

- env での ON/OFF はなし (常時有効)
- `expense_baseline_by_category=None` を渡せば旧挙動 (= 単一値) にフォールバックするので、
  暗黙的な「無効化」は可能

---

## 5. Operational Concerns

### 5.1 Monitoring

- `/api/scenarios/{id}/simulate` のレスポンスを確認。
  `rows[0].expense_breakdown` が空 dict なら baseline が生成されていない
  (= CSV 未取り込み or `expense_type=income` だけの世帯)
- analytics-platform: `business_event` の `action=scenario_simulated` 内で
  `total_event_net` が記録されているので、breakdown 機能の利用回数は scenario_id ごとに集計可能

### 5.2 Troubleshooting

| 症状 | 原因 / 対処 |
|---|---|
| `expense_breakdown` が `{"other": ...}` のみ | CSV 未取り込み or `expense_baseline_by_category` が未指定。scenario の `base_assumptions.expense_baseline_by_category` を埋めるか、`compute_expense_baseline()` を呼ぶ |
| `event_breakdown[].event_type == "?"` | catalog 関数の戻り値に `event_type` が付与されていない (catalog バグ)。`scenario_runner._expand_events` の `replace(event_type=...)` が抜けていないか確認 |
| `seed_events.py` が "scenario_id not found" | scenario が DEV_HOUSEHOLD_ID (test-household) 配下に作られているか。`/api/scenarios` で先に scenario を作る必要あり |

### 5.3 Dependencies

- 既存の `services/category_mapper.py` (canonical カテゴリ変換) に依存
- 新規の外部依存なし (DB / Python 標準ライブラリのみ)

---

## 6. Drawbacks

- **複雑度の増加**: `YearRow` がフラット構造ではなくなり、JSON シリアライズの
  helper (`_year_row_to_dict`) を介する必要が出た。メリット (粒度) > コスト (複雑度) と判断
- **テストの拡張が必要**: catalog 関数の戻り値テストと `scenario_runner` の event_type
  付与を別々に検証する必要があり、テスト数が膨らむ

## 7. Alternatives

### 案 A: カテゴリ別 inflation 率も同時に導入

- 概要: `expense_baseline_by_category` だけでなく、各カテゴリに inflation 率を持たせる
- 却下理由: スコープ拡大で PR が膨らむ。PR 1 では aggregate inflation のままにし、
  必要になったら別 PR で対応 (現状そこまでの精度は不要)

### 案 B: SimulationResultRow に新しいテーブル (per-category metrics) を作る

- 概要: `simulation_metrics_categories` 等の正規化テーブルを追加
- 却下理由: JSON カラム (`metrics: dict`) の拡張で十分対応可能。テーブル増加は alembic
  migration コストが上回る。集計が必要になったら DuckDB 等で JSON_EXTRACT で対応

### 案 C: GUI 先行 (LINE / Web で先に表示してからバックエンド最適化)

- 概要: フロント側で 1 アイテム単位の集計を毎回やる
- 却下理由: 30 年 × カテゴリ × イベントの集計を毎回 client 側でやるのは非効率。
  LLM advisor も粒度のあるデータを必要としているため backend で持たせるべき

---

## 8. Implementation History

| 日付 | 種別 | 内容 |
|---|---|---|
| 2026-05-05 | Draft | 設計案 (本 doc は PR 1 merged 後の後追い doc。実際は対面で議論 → 即実装) |
| 2026-05-05 | PR #103 created | 全実装 + テスト 23 件追加 |
| 2026-05-05 | PR #103 merged | 全 296 tests PASS、ruff (新規) clean |
| 2026-05-05 | docs amendment | docstring に「年単位粒度」の制限を明記 (commit `90a37db`) |
| 2026-05-07 | Implemented | テンプレート初投入時の事例 doc として整備 |
