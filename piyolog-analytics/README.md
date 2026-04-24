# piyolog-analytics

ぴよログ (育児記録アプリ) の .txt エクスポートを LINE Bot 経由で取り込み、
家族 (夫婦) で横断的に授乳・睡眠・排泄・体重等のサマリを共有する個人用分析基盤。

**Phase 1 (本 PR) の提供機能**:

- `.txt` 添付 → パース → SQLite に冪等保存
- LINE テキストコマンドで期間サマリ返信 (`今日` / `昨日` / `週間` / `月間` / `期間 YYYY-MM-DD YYYY-MM-DD`)
- 家族 (夫婦) の複数 LINE userId を同じ family として集計
- 許可リスト外の userId は無応答 (silent drop)
- `analytics-platform` (モノレポ共通) に webhook 受信・取り込み成否を emit

**後続フェーズ**:

- Phase 1.5: グラフ可視化 (matplotlib) + ロールバックコマンド
- Phase 2: リッチメニュー (Postback)
- Phase 3: Claude 相談機能 (prompt caching + 緊急キーワードゲート)

詳細: [`docs/design.md`](./docs/design.md)

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン |
|---|---|
| Python | 3.12+ |
| uv | 最新 |

### 0.2 セットアップ

```bash
cd agent_monorepo/piyolog-analytics
cp .env.example .env
# .env を編集: LINE チャンネルの secret / access_token、家族の LINE userId (CSV) を埋める
make install
```

### 0.3 テスト / lint

```bash
make test      # 全スイート実行
make lint      # ruff
make check     # lint + test
```

### 0.4 ローカル起動

```bash
make run
# → http://localhost:8200/healthz で liveness 確認
# → ngrok 等で外部公開して LINE Messaging API webhook URL に
#   https://xxx.ngrok.app/api/line/webhook を登録
```

---

## 1. アーキテクチャ (Phase 1)

```
┌─────────────┐
│ LINE User   │ (家族 N 人、許可リスト制)
└──────┬──────┘
       │ .txt 添付 or テキストコマンド
       ▼
┌──────────────────────────────────────────┐
│ FastAPI piyolog-analytics (port 8200)    │
│                                          │
│  POST /api/line/webhook                  │
│   ├─ FileMessage → download → parse →    │
│   │    repo.import_events → push 完了    │
│   ├─ TextMessage → command_router →      │
│   │    summarize → reply_text            │
│   └─ 認証: X-Line-Signature              │
│                                          │
│  GET /healthz                            │
└──────────────────────────────────────────┘
       │                   │
       ▼                   ▼
 ┌────────────┐      ┌─────────────────┐
 │ SQLite     │      │ analytics-      │
 │ piyolog.db │      │ platform        │
 │            │      │ JSONL → DuckDB  │
 └────────────┘      └─────────────────┘
```

主要コンポーネント:

| モジュール | 責務 |
|---|---|
| `app/parser/piyolog_parser.py` | ぴよログ .txt → `ParseResult` (pure Python) |
| `app/repositories/event_repo.py` | SQLite UPSERT + 冪等 event_id |
| `app/services/analytics.py` | 期間集計 + テキスト整形 |
| `app/services/command_router.py` | テキストコマンド解釈 |
| `app/services/line_client.py` | LINE SDK v3 ラッパ (text + file) |
| `app/services/line_handler.py` | Event 分岐 (ack reply → bg import → push) |
| `app/services/import_service.py` | bytes → decode → parse → repo |
| `app/routes/line.py` | FastAPI webhook + 署名検証 |
| `app/instrumentation/setup.py` | analytics-platform 初期化 |

---

## 2. コマンド仕様 (Phase 1)

| 入力 | 動作 |
|---|---|
| `ヘルプ` / `help` / `menu` | コマンド一覧 |
| `今日` / `today` | 今日 (JST) のサマリ |
| `昨日` / `yesterday` | 昨日サマリ |
| `週間` / `week` | 直近 7 日 (今日含む) |
| `月間` / `month` | 今月 (1日〜今日) |
| `期間 YYYY-MM-DD YYYY-MM-DD` / `period ...` | 指定期間 |
| `.txt` 添付 | ぴよログエクスポートを取り込み |

サマリ出力例 (1 日):

```
📅 2026/04/22 のサマリ

🍼 ミルク 2回 260ml / 搾母乳 1回 80ml
🤱 母乳 1回 / 左5分 右5分
💤 睡眠 10時間30分 (日中 2時間0分 / 夜間 8時間30分)
💧 おしっこ 1回 / うんち 1回
🍽️ 離乳食 1回 / お風呂 1回 / お薬 1回
🌡️ 体温 36.8°C (最終 04/22 20:10)
⚖️ 体重 8.50kg (最終 04/22 20:00)
📏 身長 72.0cm (最終 04/22 20:05)
```

---

## 3. データモデル (Phase 1)

### `piyolog_events` (SQLite)

| カラム | 説明 |
|---|---|
| event_id | `sha1(family_id + ISO8601 ts + event_type + raw)` |
| family_id | 集計単位キー |
| source_user_id | 取り込んだ LINE userId |
| child_id | `DEFAULT_CHILD_ID` (Phase 1 固定) |
| event_timestamp | ISO8601 (+09:00) |
| event_date | YYYY-MM-DD (JST、冗長集計キー) |
| event_type | `formula` / `breast_milk` / `expressed_milk` / `sleep` / `wake` / `pee` / `poo` / `temperature` / `weight` / `height` / `head_circumference` / `bath` / `medicine` / `baby_food` / `memo` / `other` |
| volume_ml / left_minutes / right_minutes / sleep_minutes / temperature_c / weight_kg / height_cm / head_circumference_cm | 型別フィールド |
| memo | コメント・パース不能行フォールバック |
| raw_text | 原文 1 行 |
| import_batch_id / imported_at | バッチ追跡 |

### `import_batches`

取り込み単位のメタ情報。同じ原本 (raw_text hash) を 2 回送ると
`DuplicateImportError` で弾き、ユーザに「すでに取り込み済み」を返す。

---

## 4. 観測性 (analytics-platform 連携)

| タイミング | 発行 event_type |
|---|---|
| webhook 受信開始 | `conversation_event` (started) |
| import 成否・webhook 処理 | `business_event` (domain=piyolog, action=line_webhook_processed) |
| 個別イベント処理失敗 | `error_event` |
| webhook 受信終了 | `conversation_event` (ended) |

`LINE userId` は raw では流さない (body を sha256 ハッシュ化した値のみ記録)。

---

## 5. セキュリティ

| 項目 | 対策 |
|---|---|
| LINE Webhook 偽装 | X-Line-Signature (HMAC-SHA256) 検証 |
| 不正ユーザー | `FAMILY_USER_IDS` 許可リスト、外は silent drop |
| ファイル検証 | サイズ上限 5MB (`UPLOAD_MAX_BYTES`) + `【ぴよログ】` ヘッダ必須 |
| シークレット | `.env` (gitignore)、本番は Secret Manager を想定 |
| 監視登録 | `security-platform/config/inventory.yaml` / `scan.yaml` に登録済 |

---

## 6. 残課題と次フェーズ

### Phase 1.5 (次の PR)

- グラフ可視化 5 種 (ミルク / 睡眠 / 体重 / ヒートマップ / ダッシュボード)
- `取り消し` / `undo` コマンドで直近バッチの `rolled_back_at` をセット

### Phase 2

- リッチメニュー (Postback) 対応
- `scripts/setup_richmenu.py` で画像生成 + LINE API 登録

### Phase 3

- Claude 相談機能 (`lifeplanner-agent/services/llm_client.py` の prompt caching API を活用)
- 緊急キーワードゲート (`#8000` 誘導)
- `sessions` / `conversations` テーブル (SQLite)
- consulting mode 切替

### 複数子対応 (将来)

Phase 1 は `child_id` を `DEFAULT_CHILD_ID` 固定。
複数子の場合は、Phase 2+ で `.txt` 内の名前 (`baby_name` パース済) から自動判定 or
`期間 さくら 2026-04-22 2026-04-22` のような指定を導入予定。

---

## 7. 監視・運用

| 症状 | 確認ポイント |
|---|---|
| 署名検証 401 | `LINE_CHANNEL_SECRET` と LINE Developers Console の Channel secret 一致確認 |
| 503 応答 | `.env` に LINE 認証情報が設定されているか、プロセス再起動後に反映されたか |
| 応答が返らない | `FAMILY_USER_IDS` に自分の LINE userId が入っているか (LINE Developers の userId は webhook ログから確認) |
| 取り込み時 `InvalidPiyologFileError` | ぴよログアプリから export した .txt をそのまま送信しているか (UTF-8 / cp932 自動判定) |
| サマリが空 | `event_date` (JST) と指定期間が一致しているか、`import_batches.rolled_back_at IS NULL` か |

データ確認クエリ:

```bash
sqlite3 data/piyolog.db "SELECT event_date, event_type, COUNT(*) FROM piyolog_events GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 20;"
```
