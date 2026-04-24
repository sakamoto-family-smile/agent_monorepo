# piyolog-analytics 設計書

**Version**: 1.2 (ローカル版、モノレポ整合版)
**最終更新**: 2026-04-24

## 変更履歴

- v1.0 (2026-04-23): 初版 (BigQuery 前提)
- v1.1 (2026-04-23): Claude 相談機能・リッチメニューを別 Phase に分離
- v1.2 (2026-04-24): モノレポの `analytics-platform` 基盤に整合。ストレージを SQLite + DuckDB + JSONL にローカル化し、Cloud Tasks / Firestore / BigQuery への直接依存を除去。Phase を再編 (MVP 分離、Phase 0 に LLM client 共通改修追加)

---

## 0. Executive Summary

ぴよログのテキストエクスポートを LINE Bot 経由で取り込み、LINE 上で統計サマリとグラフを確認し、さらに Claude に育児相談できる個人用分析基盤。モノレポの `analytics-platform` (OTel + JSONL + DuckDB + dbt) を計装・可視化基盤として再利用し、ドメインデータ (育児イベント) は SQLite に保存する。

**スコープ (v1.2)**: 取り込み・冪等化・テキストサマリ・グラフ・LLM 相談の 5 点を Phase 分割で実装。

---

## 1. モノレポとの整合

| レイヤー | 採用基盤 | 根拠 |
|---|---|---|
| 育児イベントストア | **SQLite** (`app/repositories/event_repo.py`) | モノレポ他エージェントの踏襲。ローカル dev が閉じる |
| 分析クエリ | **DuckDB ATTACH SQLite** or SQLite 直接 | サマリは SQLite 集計で十分、横断分析が要れば DuckDB で attach |
| 観測性 (LLM / webhook / parse) | **analytics-platform** path dep | `llm_call` / `business_event` / `error_event` を emit |
| 会話履歴・セッション | **SQLite** (Phase 3 で追加) | Firestore 不要、ローカル dev 可 |
| 非同期 job | **FastAPI `BackgroundTasks`** | Cloud Tasks 不要、`stock-analysis-agent` 前例 |
| LLM | `lifeplanner-agent/services/llm_client.py` を流用 | Phase 0 で `cache_system` / `complete_messages` 対応済 |
| LINE SDK ラッパ | `stock-analysis-agent/services/line_client.py` 踏襲 + `FileMessage` 拡張 | 既存資産 |
| security-platform | `inventory.yaml` / `scan.yaml` に登録 | モノレポ規約 |

GCP 移行は `analytics-platform` の Phase 5+ (BigQuery / GCS / Langfuse on GKE) に便乗する方針。本プロジェクト単独では GCP 直行しない。

---

## 2. 機能要件

| # | 機能 | フェーズ |
|---|---|---|
| F1 | ぴよログ .txt 取り込み (LINE `FileMessage` 添付) | P1 |
| F2 | 冪等化 (event_id = sha1 hash、UPSERT) | P1 |
| F4 | テキストサマリ (`today` / `yesterday` / `week` / `month` / `period`) | P1 |
| F6 | 夫婦共有 (FAMILY_USER_IDS 複数指定 → 同一 family として集計) | P1 |
| F7 | アクセス制御 (許可リスト外は応答しない) | P1 |
| F3 | ロールバック (`undo`) | P1.5 |
| F5 | グラフ可視化 (ミルク / 睡眠 / 体重 / ヒートマップ / ダッシュボード) | P1.5 |
| F8 | リッチメニュー (Postback) | P2 |
| F9 | Claude 相談機能 (SYSTEM_PROMPT + prompt caching) | P3 |
| F10 | 相談モード切替 | P3 |
| F11 | 医療緊急キーワード検出 (#8000 誘導) | P3 |

### 非機能

- LINE Webhook は 3 秒以内応答。重い処理は `BackgroundTasks`。
- 冪等 key: `sha1(user_id + timestamp_iso + event_type + raw_text)`。
- タイムゾーン: JST 固定。保存は ISO8601 with offset。集計は `event_date` (YYYY-MM-DD JST) を別カラム化。
- 個人情報: `.txt` は入力検証 (`【ぴよログ】` ヘッダ必須、size <= 5MB)。観測性イベントに生テキストは出さない (hash のみ)。

---

## 3. データモデル

### 3.1 `piyolog_events` (SQLite)

| カラム | 型 | 説明 |
|---|---|---|
| event_id | TEXT PK | `sha1(user_id + ts + type + raw)` |
| family_id | TEXT | 集計単位キー。`FAMILY_USER_IDS` で複数 userId を同じ `family_id` にマッピング |
| source_user_id | TEXT | 取り込んだ LINE userId |
| child_id | TEXT | 子の識別子 (Phase 1 は `DEFAULT_CHILD_ID` 固定) |
| event_timestamp | TEXT | ISO8601 (+09:00) |
| event_date | TEXT | `YYYY-MM-DD` (JST、集計用の冗長カラム) |
| event_type | TEXT | `formula` / `breast_milk` / `expressed_milk` / `sleep` / `wake` / `pee` / `poo` / `temperature` / `weight` / `height` / `head_circumference` / `bath` / `medicine` / `baby_food` / `memo` / `other` |
| volume_ml | REAL | ミルク・搾母乳 |
| left_minutes | INTEGER | 母乳 |
| right_minutes | INTEGER | 母乳 |
| sleep_minutes | INTEGER | 起床時の直前睡眠時間 |
| temperature_c | REAL | 体温 |
| weight_kg | REAL | 体重 |
| height_cm | REAL | 身長 |
| head_circumference_cm | REAL | 頭囲 |
| memo | TEXT | メモイベント / パース不明のフォールバック文 |
| raw_text | TEXT | 原文 1 行 |
| import_batch_id | TEXT | `import_batches.batch_id` FK |
| imported_at | TEXT | ISO8601 |

**インデックス**:
- `idx_events_family_date (family_id, event_date)`
- `idx_events_family_type_date (family_id, event_type, event_date)`

### 3.2 `import_batches`

| カラム | 型 | 説明 |
|---|---|---|
| batch_id | TEXT PK | UUID |
| family_id | TEXT | |
| source_user_id | TEXT | |
| source_filename | TEXT | |
| raw_text_hash | TEXT | 原本全体の sha256 |
| event_count | INTEGER | |
| imported_at | TEXT | |
| rolled_back_at | TEXT NULL | Phase 1.5 で使用 |

同 `raw_text_hash` が既に取り込み済みなら重複排除して「既に取り込み済みです」と応答。

### 3.3 `family_users`

| カラム | 型 | 説明 |
|---|---|---|
| family_id | TEXT | |
| line_user_id | TEXT PK | |
| joined_at | TEXT | |

`FAMILY_USER_IDS` 環境変数からプロセス起動時に投入 (夫婦 2 人を同じ family に固定)。

---

## 4. ぴよログパーサ仕様

### 4.1 入力フォーマット

**Daily export**:
```
【ぴよログ】YYYY/MM/DD(曜)
<名前> (N歳Mか月Kか日)

HH:MM   イベント名 [値文字列]
HH:MM   ...

<合計行>

<コメント本文>
```

**Monthly export** (複数日ブロック):
```
【ぴよログ】YYYY/MM
<名前> (現在の年齢)

----------
YYYY/MM/DD(曜)
HH:MM   ...
<合計>
<コメント>

----------
YYYY/MM/DD(曜)
...
```

### 4.2 状態機械

```
START → HEADER → DATE → NAME_AGE → BLANK → EVENTS → BLANK → TOTALS → BLANK → COMMENT → (DATE or END)
```

### 4.3 イベント正規表現

| piyolog 表記 | `event_type` | 値正規表現 |
|---|---|---|
| `ミルク NNNml` | `formula` | `(\d+)ml` |
| `搾母乳 NNNml` | `expressed_milk` | `(\d+)ml` |
| `母乳 左N分 右M分 ▶/◀/|` | `breast_milk` | `左(\d+)分`, `右(\d+)分` |
| `寝る` | `sleep` | — |
| `起きる (N時間M分)` | `wake` | `\((\d+)時間(\d+)分\)` |
| `おしっこ` | `pee` | — |
| `うんち (ふつう\|多め\|少なめ\|ちょこっと\|下痢\|やわらかめ\|かため)` | `poo` | 文字列 → `memo` 格納 |
| `身長 NN.Ncm` | `height` | `(\d+\.?\d*)cm` |
| `体重 NN.Nkg` | `weight` | `(\d+\.?\d*)kg` |
| `体温 NN.N°C` | `temperature` | `(\d+\.?\d*)°C` |
| `頭囲 NN.Ncm` | `head_circumference` | `(\d+\.?\d*)cm` |
| `お風呂` | `bath` | — |
| `お薬` / `服薬` | `medicine` | — |
| `離乳食` | `baby_food` | — |
| (その他) | `other` | raw_text を `memo` に格納 |

### 4.4 フォールバック戦略

- パース不能行: `event_type="other"` で raw_text を `memo` に入れ保存 (情報ロスを防ぐ)
- 合計行はスキップ (冗長データ、event_id ハッシュ対象外)
- コメントブロックは `memo` エントリとして日付の `00:00` に保存

---

## 5. 観測性 (analytics-platform 連携)

以下を emit:

| タイミング | event_type | 備考 |
|---|---|---|
| Webhook 受信 | `conversation_event` (started/ended) | hash 化 userId |
| import 成功 | `business_event` (domain=`piyolog`, action=`import_success`, attrs={event_count, batch_id}) | |
| import 失敗 | `error_event` | 例外種別 + message head |
| Claude 呼出 (Phase 3) | `llm_call` | `lifeplanner-agent/services/llm_client.py` が自動で emit |

LINE の `line_user_id` は必ず `sha256:<hex>` 化して流す。

---

## 6. コマンド (Phase 1)

| 入力 | 動作 |
|---|---|
| `ヘルプ` / `help` | コマンド一覧返信 |
| `今日` / `today` | 今日 (JST) のサマリ |
| `昨日` / `yesterday` | 昨日サマリ |
| `週間` / `week` | 直近 7 日 (今日含む) |
| `月間` / `month` | 今月 (1日〜今日) |
| `期間 YYYY-MM-DD YYYY-MM-DD` / `period ...` | 指定期間 |
| `.txt` 添付 | 取り込み実行 → 完了 push |

### サマリ出力例

```
📅 2026/04/24 のサマリ

🍼 ミルク: 5 回 / 合計 720ml
🤱 母乳: 3 回 / 左 25分 右 30分
💤 睡眠: 合計 10時間 30分 (日中 2時間、夜間 8時間30分)
💩 うんち: 2 回
💧 おしっこ: 6 回
🌡️ 体温: 36.8°C (最終 20:00)
⚖️ 体重: 8.5kg (最終 20:00)
📏 身長: 72.0cm (最終 20:00)
```

---

## 7. アーキテクチャ

```
┌─────────────┐
│ LINE User   │ (家族 N 人, 許可リスト制)
└──────┬──────┘
       │ .txt 添付 or テキストコマンド
       ▼
┌──────────────────────────────────────────┐
│ FastAPI piyolog-analytics                │
│                                          │
│  POST /api/line/webhook                  │
│   ├─ FileMessage → download → parse →    │
│   │    repo.upsert → push 完了通知       │
│   ├─ TextMessage → command_router →      │
│   │    summary query → reply_text        │
│   └─ 認証: X-Line-Signature              │
│                                          │
│  GET /healthz                            │
└──────────────────────────────────────────┘
       │                    │
       ▼                    ▼
 ┌────────────┐       ┌─────────────────┐
 │ SQLite     │       │ analytics-      │
 │ piyolog.db │       │ platform        │
 │            │       │ JSONL → DuckDB  │
 └────────────┘       └─────────────────┘
```

---

## 8. フェーズ計画

### Phase 0 (完了) ✅

- `lifeplanner-agent/services/llm_client.py` に prompt caching + `complete_messages()` 追加 (PR #33)

### **Phase 1 (本 PR)**: MVP

- パーサ (10+ケース) + ユニットテスト
- SQLite イベントストア + 冪等 UPSERT + 原本 hash 重複排除
- LINE Webhook (`FileMessage` / `TextMessage`)
- テキストコマンド: `help` / `today` / `yesterday` / `week` / `month` / `period`
- FAMILY_USER_IDS 許可リスト + family 集計
- analytics-platform 計装 (business_event / error_event)
- security-platform 登録

### Phase 1.5: グラフ + ロールバック

- matplotlib 可視化 5 種
- `undo` コマンド (直近 `import_batches` を rolled_back_at で無効化)

### Phase 2: リッチメニュー

- Postback Router
- rich menu 画像生成 (`scripts/setup_richmenu.py`)

### Phase 3: Claude 相談

- session/conversation SQLite テーブル
- context_builder (直近 72h / 7d サマリ)
- emergency_gate (regex)
- consulting mode 切替

---

## 9. 設計判断ログ

- **SQLite 選択**: DuckDB 単独だと書込並列に弱い。SQLite で書いて DuckDB で attach-read する構成が他エージェント前例 (lifeplanner)。
- **family_id 設計**: LINE userId を 2 つ以上同じ family に束ねるため、`FAMILY_USER_IDS` を `family_id1:uid1,uid2;family_id2:uid3` 形式で環境変数化。Phase 1 はシングル family 固定。
- **child_id 後送り**: Phase 1 は `DEFAULT_CHILD_ID="default"` 固定。複数子対応は Phase 2+ で `.txt` ファイル名から自動判定 or コマンド指定。
- **期間コマンドの曖昧さ**: `期間 YYYY-MM-DD YYYY-MM-DD` は space 区切り、`period` も同様。31 日を超える期間はサマリ短縮 (Phase 1.5)。
- **raw_text 保持**: storage cost 僅かで debug 価値大。SQLite ファイルサイズは 1 年で数 MB 想定。
