# LINE 操作 + Phase 4 ロードマップ

「LINE Bot から一通りの分析・シミュレーションを使えるようにする」ための
PR 単位の計画書。本番デプロイ (PR 0) は後回し、まずローカル / dev で
動かしてから本番に乗せる方針 (Plan B)。

## 全体像

```
Plan B 進行順:
  PR 1 → PR 2 → PR 3 → PR 4 (+ PR 1.5 統合) → PR 5 → PR 0
  (dev で動作確認しながら段階的に積み上げる)
```

| | 内容 | 状態 | PR |
|---|---|---|---|
| **PR 1** | バックエンド粒度向上 (カテゴリ・イベント明細) | ✅ merged | [#103](https://github.com/sakamoto-family-smile/agent_monorepo/pull/103) |
| **PR 2** | LINE 分析コマンド (`/summary` `/networth` `/anomalies`) | ✅ merged | [#104](https://github.com/sakamoto-family-smile/agent_monorepo/pull/104) |
| **PR 3** | LINE CF 表示 (`/cashflow <id>` 表 + 画像) | ⏳ 計画 | — |
| **PR 4** | LINE イベント設定 UI + `start_month` プロレート | ⏳ 計画 | — |
| **PR 5** | 残イベント (E03/E07/E08/E11/E10/E09/E12) | ⏳ 計画 | — |
| **PR 0** | GCP インフラ Terraform + 本番デプロイ | ⏳ 計画 | — |

---

## PR 1 (✅ merged): バックエンド粒度向上

### 何ができたか
- `agents/simulator.YearRow` に下記を追加 (後方互換、追加のみ):
  - `expense_breakdown: dict[str, Decimal]` — カテゴリ別年額
  - `event_breakdown: list[EventLine]` — イベント明細 (event_type / category / label / amount)
- `HouseholdProfile.expense_baseline_by_category` で取り込み済 transactions の直近 12 ヶ月から自動 baseline 生成 (`services/expense_baseline.py`)
- `CashFlowDelta.event_type` を追加し、`scenario_runner._expand_events` が E01/E02/E04 を後付け
- `scripts/seed_events.py`: JSON ファイル (`data/seeds/example_events.json`) から一括投入
- API `/api/scenarios/{id}/simulate` レスポンスに breakdown 追加 (Pydantic schema 拡張のみ)

### 既知の制限
- **時間粒度は年単位**。`start_year` のみで月情報なし。住宅購入が 7 月でも 2028 年に 12 ヶ月分のローン返済が計上される (30 年合計には影響なし、単年は数十万円ズレうる)。月単位プロレートは PR 4 で `start_month` を追加する。

---

## PR 2 (✅ merged): LINE 分析コマンド

### 何ができたか
- 3 コマンド追加 (`services/line_handler.py`):
  - `/summary [今月|先月|今年|YYYY-MM YYYY-MM]` — 月次サマリ + 固変分離 + カテゴリ Top 5
  - `/networth [YYYY-MM-DD]` — 純資産 + 種別別内訳
  - `/anomalies [YYYY-MM]` — 直近 6 ヶ月平均から 3σ 超のカテゴリ Top 5
- 期間パーサ `services/line_period.py` (今月/先月/今年/YYYY-MM)
- Flex helper 3 つ (`services/line_flex.py`):
  - `summary_bubble` / `networth_bubble` / `anomalies_bubble`
- リッチメニューを 2500x843 (3 ボタン) → 2500x1686 (3x2 = 6 ボタン) に拡張、カラー絵文字対応

### LINE 上の現在の構成

```
┌─────────────────────────────────────────┐
│ 📊 サマリ   💰 純資産   ⚠️ 異常検知   │
├─────────────────────────────────────────┤
│ 📋 シナリオ  💬 連携    ❓ ヘルプ      │
└─────────────────────────────────────────┘
```

---

## PR 3 (⏳ 計画): LINE CF 表示

### スコープ

`/cashflow <scenario_id>` で 30 年キャッシュフローを表 + 画像チャートで返す。

#### 想定 UX

```
ユーザー: /cashflow 1
Bot:
  📈 シナリオ "Base" のキャッシュフロー
  ┌────┬───────┬───────┬───────┐
  │年  │収入    │支出    │ネット │
  ├────┼───────┼───────┼───────┤
  │2026│720万  │420万  │+300万 │
  │2027│730万  │430万  │+300万 │
  │... (Flex carousel で 5 年単位 or 画像で 30 年俯瞰)
  ┕────┴───────┴───────┴───────┘
  純資産推移:
  [matplotlib で生成した画像]
```

### 設計案

| 項目 | 内容 |
|---|---|
| Flex 形式 | Bubble carousel (5 年ずつ 6 bubble = 30 年) or 1 bubble + 画像 |
| 画像 | matplotlib で 純資産推移 + 年次収支 stacked bar、PNG 出力 |
| 画像配信 | piyolog 流の `ImageStore` (in-memory + TTL 1 時間) + `/api/line/image/{id}.png` 公開 URL |
| 引数 | `<scenario_id>` 必須、`期間 YYYY YYYY` で年範囲絞り (任意) |

#### 必要な追加実装

1. `services/cashflow_chart.py`: matplotlib で年次 CF 図 / 純資産推移図を生成
2. `services/image_store.py`: piyolog から ImageStore をポート (TTL 付き in-memory cache)
3. `routes/line_image.py`: `/api/line/image/{id}.png` 公開エンドポイント (HMAC 検証なし、id は uuid)
4. `services/line_handler._cmd_cashflow`: シナリオ取得 → simulate → Flex + ImageMessage
5. `config.py`: `PUBLIC_BASE_URL` (Cloud Run の URL) を env で受け取る
6. リッチメニュー上段に `📈 CF` ボタンを追加 (or `/cashflow` を text コマンドのみで) — TBD

---

## PR 4 (⏳ 計画): LINE イベント設定 UI + 月単位プロレート

### スコープ

LINE 上で E01/E02/E04 を追加・編集できるようにし、同時に `start_month` (月) を全イベントに導入してプロレート対応する。

### 4-A. UI 選択 (要決定)

| 案 | UX | 工数 |
|---|---|---|
| **A. LIFF Web フォーム** | 既存の `app/static/liff/` に event 編集フォーム追加。LIFF Login で世帯認証、URL から scenario_id 受け取り | 中〜大 |
| **B. LINE Quick Reply + datetime picker** | piyolog 流。`⚙️ 設定` ボタン → イベント種別選択 (Quick Reply) → 日付 picker (datetime) → 数値入力 (text) | 中 |
| **C. 両方併存** | LIFF (フル機能) + LINE postback (簡易テンプレ) | 大 |

推奨: **B から始める**。複雑なイベント (E07 教育とか 13 パラメータ) は LIFF へ別途。

### 4-B. `start_month` プロレート (旧 PR 1.5 を統合)

#### 変更内容
- `LifeEvent` model に `start_month: int = 1` を追加 (デフォルト 1月)
- `BirthEventParams` / `HousingEventParams` / `VehicleEventParams` に `start_month` を追加
- 各 catalog (`birth.py` / `housing.py` / `vehicle.py`) でプロレート適用:
  - 初年度: `(13 - start_month) / 12` でスケール
  - 最終年: `start_month / 12` でスケール (中間年は通年)
- 例: 2028/7 住宅購入 → 2028 年は 6 ヶ月分、2058 年は 6 ヶ月分の住宅ローン
- API / JSON schema 拡張 (`start_month` を optional、null なら 1)

#### 影響範囲
- catalog の単体テスト書換 (E01/E02/E04 各々 30 年テスト)
- 既存 simulator テストは start_month=1 で同じ結果になるはず (後方互換)
- LINE で datetime picker (mode=date) を使えば start_year + start_month を一発入力可

---

## PR 5 (⏳ 計画): 残イベント実装

家族の状況 (既婚 / 0 歳児 1 人) に基づく優先順位:

| 優先 | イベント | 理由 | 想定パラメータ |
|---|---|---|---|
| 🔥 High | **E07 子の進学** | E01 教育費を後から差し替え (浪人・大学院・公立私立変更等)、子供 0 歳児 (生後 3 ヶ月) なので将来確実に必要 | child_birth_year / track_change_year / new_track / 一人暮らし開始年 / 仕送り月額 |
| 🔥 High | **E08 退職・年金** | 30 年シミュ後半の精度に直結 (退職年・公的年金開始年・退職金) | retirement_year / pension_start_year / retirement_lump_sum / 繰上繰下 |
| 🟡 Mid | **E06 転職・独立** | 年収変化シナリオの比較 | year / new_salary / 独立=true なら所得形態切替 |
| 🟡 Mid | **E11 介護発生** | 親 (60-70代) の介護費用、要支援/要介護度別 | year / 要介護度 / 在宅 or 施設 / 月額自己負担 |
| 🟡 Mid | **E03 住宅売却・住替** | E02 後の買換え可能性 | year / 売却価格 / 譲渡所得税 / 新居 (E02 と連鎖) |
| 🟢 Low | **E10 リフォーム** | E02 後 10-20 年で必要 | year / 費用 / 借入有無 |
| 🟢 Low | **E09 相続・贈与** | 受贈額・時期次第 | year / 額 / 相続税基礎控除 |
| 🟢 Low | **E12 大学院** | E07 と統合可 | E07 の university_track="grad_school" 拡張 or 別イベント |
| ⚫ Skip | E05 結婚 | 既婚なので不要 | (実装スキップ) |

PR は **High 2 件 (E07/E08) を 1 PR に**、**Mid 3 件 (E06/E11/E03) を 1 PR に**、**Low 3 件 (E10/E09/E12) を 1 PR に** の 3 分割が現実的。

---

## PR 0 (⏳ 計画): GCP インフラ整備

`piyolog-analytics` / `driving-license-bot` のものをポート。

### 必要な作業

| 項目 | 参考 (piyolog) |
|---|---|
| `terraform/main.tf` (Cloud SQL Postgres / Cloud Run / Artifact Registry) | `piyolog-analytics/terraform/` |
| `terraform/secrets.tf` (LINE_CHANNEL_SECRET / TOKEN / DATABASE_URL) | 同上 |
| `terraform/iam.tf` (sa-lifeplanner / aiplatform.user) | 同上 |
| `terraform/backup_bucket.tf` (Phase 4-A 流儀の GCS backup) | `piyolog-analytics/terraform/backup_bucket.tf` |
| `cloudbuild.yaml` | `piyolog-analytics/cloudbuild.yaml` |
| `scripts/deploy_cloud_run.sh` (env / secrets / sql instance 配線) | `piyolog-analytics/scripts/deploy_cloud_run.sh` |
| `scripts/backup_data.sh` / `restore_data.sh` | 同上 |
| `Makefile` ターゲット (`tf-init`, `tf-apply`, `deploy-cloud-run`, `backup`, `restore`) | 同上 |
| README デプロイ手順 (Step 1〜9 walkthrough) | 同上 |

---

## 共通の既知タスク / 制約

### LINE
- リッチメニューは PR 2 で 6 ボタン化済 (上段 分析 / 下段 既存)。PR 3/4 でボタン入れ替え or 8 ボタン化 (2x4) を検討
- `LIFF_ID` 未設定時は連携ボタンが `/help` フォールバック (PR 4 で LIFF 必須化の場合は要見直し)
- Flex bubble の合計サイズには 50KB 上限あり (carousel 多 bubble で注意)

### データ
- `/api/profile/*` は `Depends(get_household_id)` で `DEV_HOUSEHOLD_ID` を見るため、LINE 経由のテストでは `/link` で同じ household_id に紐付けが必要 (`tests/test_line_handler_analysis.py:_link_to_dev_household`)
- 取り込み済 transactions が 12 ヶ月分ない世帯は `compute_expense_baseline` の年率換算が荒い。最低 3 ヶ月推奨

### テスト / CI
- 全 337 件 PASS (PR 2 までで)
- 新規ファイルは ruff clean、既存 codebase に少量の lint 違反あり (本ロードマップ範囲外)

---

## 別作業に移る場合の引き継ぎ

このロードマップに沿って戻ってくれば、

1. README.md の Phase 4 セクション → 状況把握
2. 本ファイル → PR 単位の詳細計画
3. 直近の merged PR (#103 / #104) → 実装の流れ

を見れば文脈を引き継げる。本ファイルは PR 進行に応じて更新する運用。
