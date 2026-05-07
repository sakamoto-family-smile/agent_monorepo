# piyolog-analytics 設計書

| | |
|---|---|
| **Version** | 2.0 |
| **最終更新** | 2026-05-07 |
| **Status** | Active |
| **Owner** | @kurama554101 |
| **README** | [`../README.md`](../README.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-04-23 | 1.0 | 初版 (BigQuery 前提) |
| 2026-04-23 | 1.1 | Claude 相談機能・リッチメニューを別 Phase に分離 |
| 2026-04-24 | 1.2 | モノレポの `analytics-platform` 基盤に整合。SQLite + DuckDB + JSONL ローカル化 |
| 2026-05-07 | 2.0 | `docs/SYSTEM_DESIGN_TEMPLATE.md` 準拠に再構成。NFR / 設計判断ログ / 用語集を追記。Phase 4-A/4-B 完了反映。旧 `design.md` を本ファイルに置換 |

---

## 0. Executive Summary

ぴよログ (育児記録アプリ) のテキストエクスポートを LINE Bot 経由で取り込み、夫婦の LINE userId を同じ家族として集計し、授乳・睡眠・排泄・体重等のサマリ / グラフを LINE で共有する個人用分析基盤。Vertex AI Gemini を使った育児相談 + 自然言語データ照会も提供。モノレポの `analytics-platform` (OTel + JSONL + DuckDB + dbt) を計装基盤として再利用し、ドメインデータは SQLite (dev) / Cloud SQL Postgres (本番) に保存する。

---

## 1. 目的・スコープ

### 1.1 目的

- 夫婦で **同じ家計** に育児ログを集約し、LINE 上でいつでも参照できるようにする
- ぴよログアプリの「家族で共有」機能だけでは横断集計やグラフが見にくいので、本ツールで補完する
- 子の体重・身長・授乳量推移を時系列で把握し、健診時の説明資料にもなる
- LINE 上で自然言語で「2 月のミルク量を比較して」のような質問ができる (Phase 3)

### 1.2 想定ユーザー

| 種別 | 内容 |
|---|---|
| 主要 | 家族 (夫婦 2 人 + 子)、ぴよログユーザー、LINE 利用者 |
| 副次 | 開発者本人 |
| 想定外 | 不特定多数の一般ユーザー、商用 SaaS としての利用 |

### 1.3 スコープ / Non-Goals

**スコープ**:
- 利用単位: 家族 (夫婦 + 子 1 人)、`FAMILY_USER_IDS` で複数 userId を 1 family に束ねる
- データ取得: ぴよログアプリの **.txt エクスポート手動アップロード** (LINE で送信)
- UI: LINE Bot (Web UI なし)
- 個人用: 1 家族向け、本番デプロイは Cloud Run 個人アカウント

**Non-Goals**:
- ぴよログ API 連携 (公開 API なし)
- 医療診断 (LLM 相談機能は「医師受診を検討」と促すのみ)
- 多家族テナント分離 (個人プロジェクトのため)
- 多言語 (日本語固定)

---

## 2. 機能要件

| ID | 機能 | 状態 | Phase | 備考 |
|---|---|---|---|---|
| F1 | ぴよログ .txt 取り込み (LINE FileMessage 添付) | ✅ 実装済 | Phase 1 | UTF-8 / cp932 自動判定 |
| F2 | 冪等化 (event_id = sha1 hash、UPSERT) | ✅ 実装済 | Phase 1 | 原本 hash で重複排除 |
| F3 | ロールバック (`undo` コマンド) | ✅ 実装済 | Phase 1.5 | `import_batches.rolled_back_at` で論理削除 |
| F4 | テキストサマリ (`今日` / `昨日` / `週間` / `月間` / `期間 ...`) | ✅ 実装済 | Phase 1 | コマンド aliases あり |
| F5 | グラフ可視化 (ミルク / 睡眠 / 体重 / ヒートマップ / ダッシュボード) | ✅ 実装済 | Phase 1.5 | matplotlib + Noto Sans CJK |
| F6 | 夫婦共有 (`FAMILY_USER_IDS` で同一 family) | ✅ 実装済 | Phase 1 | 起動時 env から投入 |
| F7 | アクセス制御 (許可リスト外は silent drop) | ✅ 実装済 | Phase 1 | bootstrap mode あり |
| F8 | リッチメニュー (Postback) | ✅ 実装済 | Phase 2 | 8 ボタン (4x2 grid、2500x1686) |
| F9 | Claude 相談機能 (Vertex Gemini SYSTEM_PROMPT + tool use) | ✅ 実装済 | Phase 3 | session/conversation テーブル + capability_gap タグ |
| F10 | 相談モード切替 | ✅ 実装済 | Phase 3 | session_repo で normal/consulting |
| F11 | 医療緊急キーワード検出 (#8000 誘導) | ✅ 実装済 | Phase 3 | regex ベース |
| F12 | バックアップ / リストア (GCS) | ✅ 実装済 | Phase 4-A | `make backup` / `make restore` |
| F13 | 子情報 DB + 設定 UI (生年月日 / 名前) | ✅ 実装済 | Phase 4-B | `children` テーブル + Quick Reply |
| F14 | リマインド通知 / 多子対応 | 📋 計画 | Phase 5+ | LINE push、`child_id` 切替 |

---

## 3. 非機能要件 (NFR)

### 3.1 性能

| 項目 | 目標 |
|---|---|
| LINE Webhook 応答 | < 3 秒 (LINE 制約) |
| ファイル取り込み (1 ヶ月分) | < 10 秒 (BackgroundTasks 経由) |
| サマリ集計 (週間) | < 200 ms |
| グラフ画像生成 | < 2 秒 |
| LLM tool_use loop (1 質問) | < 30 秒 (max 5 iterations) |

### 3.2 可用性

- 個人プロジェクトのため **99% 程度で十分**、計画停止 OK
- Cloud Run リージョン JP (`asia-northeast1`)、`min-instances=0` (cold start 許容)
- Cloud SQL Postgres (本番) の point-in-time recovery 7 日 + GCS バックアップ (Phase 4-A)

### 3.3 セキュリティ

- LINE Webhook の **HMAC-SHA256 署名検証** (`X-Line-Signature`) 必須
- `FAMILY_USER_IDS` 許可リスト外は silent drop (応答もしない)
- ファイル検証: サイズ上限 5MB (`UPLOAD_MAX_BYTES`) + `【ぴよログ】` ヘッダ必須
- secret 管理: dev は `.env` (gitignore)、本番は **Secret Manager** で `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / `DATABASE_URL`
- security-platform 連携: `inventory.yaml` / `scan.yaml` に登録済 (CVE 監視対象)

### 3.4 コスト

- 月額予算目安: ¥1,500 程度 (Cloud Run + Cloud SQL + Vertex AI、家族 2 人想定)
- LLM (Vertex Gemini): 1 conversation あたり数十円 (相談頻度 < 1 回 / 日想定)
- Cloud SQL: db-f1-micro、1 GB 程度 (1 年で数 MB 増加)
- GCS バックアップ: dump.sql ~100 KB × 90 日 retention

### 3.5 プライバシー / データ保持

- 育児記録は **PII** に該当 (子の名前 / 生年月日 / 食事 / 睡眠データ)
- LINE userId は **sha256 hash 化** して analytics-platform に送る (raw は流さない)
- 取り込んだ .txt の raw は DB に保存 (debug / undo 用)、analytics には流さない
- 保持期間:
  - `piyolog_events`: 永続 (家族の判断で削除可)
  - 会話ログ (`conversations` / `conversation_messages`): 90 日 (機能改善のため、PII フィルタ済)
  - GCS バックアップ: current 90 日 / archived 14 日 (lifecycle)

### 3.6 キャパシティ

- 1 家族あたり: 1 日 ~50 イベント × 365 日 = 年 ~18,000 行 (10 年で ~180,000 行、SQLite で十分)
- LINE webhook 同時接続: ~5 人 (家族メンバー)
- Cloud Run instance: max 2 (cold start 許容)

### 3.7 保守性 / テスト性

- カバレッジ目標: **80%+** (現状 250+ tests PASS)
- パーサーは **regex の境界条件テスト** が重要 (10+ ケースで担保)
- lint: `ruff check` を CI で実行
- observability: `analytics-platform` JSONL → DuckDB / dbt で集計可能
- LLM 相談の `capability_gap` タグで「対応できなかった理由」を追跡 (機能改善ループ)

---

## 4. データモデル

### 4.1 ER 概要

```
family_users (LINE userId 紐付け)        sessions (LINE 単位の現在モード)
        │                                       │
        ▼                                       ▼
  ┌────────────────┐                    ┌────────────────┐
  │ piyolog_events │ ◀── batch_id ──    │ conversations  │
  │ (取り込み済)   │                    │ (相談セッション)│
  └────────────────┘                    └───────┬────────┘
        ▲                                       ▼
        │                              conversation_messages
  import_batches (取り込み単位)        (user / assistant / tool_use / tool_result)
        │
        ▼
  children (子情報、Phase 4-B)
```

### 4.2 主要テーブル

| テーブル | 用途 | 主キー | 備考 |
|---|---|---|---|
| `piyolog_events` | ぴよログ 1 行 = 1 row | `event_id` (sha1 hash) | family_id + event_date でインデックス |
| `import_batches` | 取り込み単位 | `batch_id` (UUID) | `rolled_back_at` で論理削除 |
| `family_users` | LINE userId → family_id | `line_user_id` | env から起動時投入 |
| `sessions` | LINE userId 単位の現在モード | `line_user_id` | `mode` (normal / consulting) |
| `conversations` | 相談セッション 1 つ | `conversation_id` (UUID) | LLM 履歴の親 |
| `conversation_messages` | role / content / tool / capability_gap | `message_id` | role: user / assistant / tool_use / tool_result |
| `children` | 家族の子情報 (Phase 4-B) | `family_id + child_id` | birth_date / name |

詳細 DDL は `alembic/` を参照。

### 4.3 ぴよログパーサ仕様

#### 入力フォーマット (Daily / Monthly export)

```
【ぴよログ】YYYY/MM/DD(曜)
<名前> (N歳Mか月Kか日)

HH:MM   イベント名 [値文字列]
HH:MM   ...

<合計行>
<コメント本文>
```

Monthly export は複数日ブロックを `----------` 区切り。

#### 状態機械

```
START → HEADER → DATE → NAME_AGE → BLANK → EVENTS → BLANK → TOTALS → BLANK → COMMENT → (DATE or END)
```

#### イベント正規表現

| piyolog 表記 | event_type | 値正規表現 |
|---|---|---|
| `ミルク NNNml` | `formula` | `(\d+)ml` |
| `搾母乳 NNNml` | `expressed_milk` | `(\d+)ml` |
| `母乳 左N分 右M分 ▶/◀/\|` | `breast_milk` | `左(\d+)分`, `右(\d+)分` |
| `寝る` | `sleep` | — |
| `起きる (N時間M分)` | `wake` | `\((\d+)時間(\d+)分\)` |
| `おしっこ` | `pee` | — |
| `うんち (ふつう\|多め\|...)` | `poo` | 文字列 → memo |
| `身長 NN.Ncm` | `height` | `(\d+\.?\d*)cm` |
| `体重 NN.Nkg` | `weight` | `(\d+\.?\d*)kg` |
| `体温 NN.N°C` | `temperature` | `(\d+\.?\d*)°C` |
| `頭囲 NN.Ncm` | `head_circumference` | `(\d+\.?\d*)cm` |
| `お風呂` / `お薬` / `離乳食` / その他 | 個別 type or `other` | — |

#### フォールバック

- パース不能行: `event_type="other"` で raw_text を `memo` に保存
- 合計行はスキップ (冗長、event_id 対象外)
- コメントブロックは `memo` エントリとして日付の `00:00` に保存

---

## 5. アーキテクチャ

### 5.1 コンポーネント

```
┌─────────────┐
│ LINE User   │ (家族 N 人、許可リスト制)
└──────┬──────┘
       │ .txt 添付 / テキストコマンド / Postback
       ▼
┌──────────────────────────────────────────┐
│ FastAPI piyolog-analytics (port 8200)    │
│                                          │
│  POST /api/line/webhook                  │
│   ├─ FileMessage → download → parse →    │
│   │    repo.import_events → push 完了    │
│   ├─ TextMessage → command_router or     │
│   │    consultation (LLM tool use loop)  │
│   ├─ Postback → postback_router          │
│   └─ 認証: X-Line-Signature              │
│                                          │
│  GET /healthz                            │
└──────────────────────────────────────────┘
       │                   │              │
       ▼                   ▼              ▼
 ┌──────────────────┐  ┌─────────────┐  ┌─────────────┐
 │ SQLite (dev)     │  │ analytics-  │  │ Vertex AI   │
 │ Postgres (本番)  │  │ platform    │  │ Gemini      │
 │   via SQLAlchemy │  │ JSONL → DDB │  │ (Phase 3+)  │
 └──────────────────┘  └─────────────┘  └─────────────┘
```

### 5.2 主要モジュール

| モジュール | 責務 |
|---|---|
| `app/parser/piyolog_parser.py` | ぴよログ .txt → `ParseResult` (pure Python、状態機械) |
| `app/repositories/event_repo.py` | DB UPSERT + 冪等 event_id |
| `app/repositories/session_repo.py` | sessions / conversations / messages |
| `app/repositories/child_repo.py` | children テーブル CRUD (Phase 4-B) |
| `app/services/analytics.py` | 期間集計 + テキスト整形 |
| `app/services/visualizer.py` | matplotlib グラフ生成 5 種 |
| `app/services/command_router.py` | テキストコマンド解釈 |
| `app/services/postback_router.py` | リッチメニュー Postback dispatch |
| `app/services/consultation.py` | Vertex Gemini 相談 + tool use loop |
| `app/services/tool_executor.py` | LLM tool 実行 (query_events / ask_clarification) |
| `app/services/context_builder.py` | LLM 用 RECENT CONTEXT (72h / 7d サマリ + 子情報) |
| `app/services/emergency_gate.py` | 緊急ワード regex (#8000 誘導) |
| `app/services/line_client.py` | LINE SDK v3 ラッパ (text / file / Flex / Quick Reply) |
| `app/services/line_handler.py` | Event 分岐 (text / file / postback / follow) |
| `app/services/import_service.py` | bytes → decode → parse → repo |
| `app/routes/line.py` | FastAPI webhook + 署名検証 |
| `app/instrumentation/setup.py` | analytics-platform 初期化 |

### 5.3 外部依存

| 連携先 | 用途 | 認証方式 |
|---|---|---|
| LINE Messaging API | webhook / push / file content / rich menu | Channel Access Token (Secret Manager) |
| Vertex AI Gemini | LLM 相談 (Phase 3) | ADC / SA `roles/aiplatform.user` |
| Cloud SQL Postgres | 本番 DB | DATABASE_URL (Secret Manager) |
| Cloud Storage | バックアップ (Phase 4-A) | sa-piyolog SA (Cloud SQL → GCS で objectAdmin 自動付与) |
| `analytics-platform` (path dep) | 業務ログ集約 | path dep |
| `security-platform` | CVE 監視 / MCP gateway (将来) | inventory 登録 |

### 5.4 LINE コマンド仕様

| 入力 | 動作 |
|---|---|
| `ヘルプ` / `help` / `menu` | コマンド一覧 |
| `今日` / `today` | 今日 (JST) のサマリ |
| `昨日` / `yesterday` | 昨日サマリ |
| `週間` / `week` | 直近 7 日 (今日含む) |
| `月間` / `month` | 今月 (1日〜今日) |
| `期間 YYYY-MM-DD YYYY-MM-DD` / `period ...` | 指定期間 |
| `ミルク` / `milk` | ミルク量グラフ |
| `睡眠` / `sleep` | 睡眠グラフ |
| `体重` / `weight` | 体重・身長・頭囲グラフ |
| `時間帯` / `heatmap` | 授乳ヒートマップ |
| `ダッシュボード` / `dashboard` | 4 種を 1 枚に集約 |
| `相談` | 相談モード ON (LLM tool use loop 開始) |
| `相談終了` / `exit` | 相談モード OFF |
| `取り消し` / `undo` | 直近の取り込みバッチを論理削除 |
| `.txt` 添付 | ぴよログエクスポートを取り込み |
| (リッチメニュー Postback) | 各 8 ボタンに対応 |

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

### 5.5 観測性 (analytics-platform 連携)

| タイミング | event_type |
|---|---|
| webhook 受信開始 | `conversation_event` (started) |
| import 成否・webhook 処理 | `business_event` (domain=piyolog, action=line_webhook_processed / import_success / import_error) |
| Claude 呼出 (Phase 3) | `llm_call` (lifeplanner llm_client 流用) |
| 個別イベント処理失敗 | `error_event` |
| webhook 受信終了 | `conversation_event` (ended) |

`LINE userId` は raw では流さない (sha256 ハッシュ化)。LLM 会話の raw text は emit せず、`content_hash` + `content_chars` のみ送信 (PII 配慮)。

---

## 6. 開発フェーズ / Roadmap

### 6.1 Phase 一覧

| Phase | 名前 | 状態 | 主要内容 |
|---|---|---|---|
| Phase 0 | LLM client 共通改修 | ✅ 完了 | `lifeplanner-agent/services/llm_client.py` に prompt caching + complete_messages (PR #33) |
| Phase 1 | MVP (取り込み + サマリ) | ✅ 完了 | F1〜F2、F4〜F7 |
| Phase 1.5 | グラフ + ロールバック | ✅ 完了 | F3、F5 |
| Phase 2 | リッチメニュー | ✅ 完了 | F8 |
| Phase 3 | Claude 相談 | ✅ 完了 | F9〜F11 |
| Phase 4-A | バックアップ / リストア | ✅ 完了 | F12 (PR #99) |
| Phase 4-B | 子情報 DB + 設定 UI | ✅ 完了 | F13 (PR #100) |
| Phase 5+ | リマインド通知 / 多子対応 | 📋 計画 | F14、現状未着手 |

### 6.2 残課題 (Phase 5+ で検討)

- リマインド通知: 「3 時間ミルクなし」「夜泣き続き」を Cloud Scheduler で push
- 多子対応: 現状 `DEFAULT_CHILD_ID` 固定。複数子のとき `.txt` 内の名前パースで自動判定 or `期間 さくら 2026-04-22 ...` のような子指定
- 31 日超期間の表示: 現状サマリ整形が長くなる、Phase 5 で短縮

---

## 7. 設計判断ログ (ADR-lite)

| 日付 | 判断 | 理由 | 詳細 |
|---|---|---|---|
| 2026-04-23 | SQLite を採用 (ローカル dev)、本番は Cloud SQL Postgres | dev 環境でファイル 1 つで完結、prod は SQLAlchemy 同一コードで Postgres に移行可 | DATABASE_URL 切替 |
| 2026-04-23 | family_id を env (`FAMILY_USER_IDS`) で投入 | Phase 1 はシングル family 固定、複雑な family CRUD は不要 | 起動時 |
| 2026-04-23 | child_id を `DEFAULT_CHILD_ID` 固定 | Phase 1 の家族は子 1 人前提、複数子は将来 | Phase 5 で見直し |
| 2026-04-23 | raw_text を `piyolog_events` に保存 | storage cost 僅か (年 数 MB)、debug 価値大 | 本番でも保持 |
| 2026-04-23 | `event_id = sha1(family + ts + type + raw)` | 決定論的 ID で再送に強い (UPSERT で吸収) | usedforsecurity=False |
| 2026-04-23 | LINE userId は sha256 hash 化して analytics に流す | PII 配慮 + observability の両立 | bootstrap mode のみ raw |
| 2026-05-04 | Phase 3 で Vertex Gemini を採用 (Anthropic 直呼ばず) | GCP IAM / VPC で統制、prompt caching は将来導入 | LLM_PROVIDER 廃止 |
| 2026-05-04 | conversation_messages.capability_gap タグ | LLM が「対応できなかった理由」を分類 (asked_clarification / out_of_scope / data_missing / tool_error / refused / completed)、機能改善ループ | partial index で集計効率化 |
| 2026-05-05 | Phase 4-A で GCS バックアップ (force_destroy=false) | tf-destroy しても backup bucket は残る、誤削除防止 | versioning ON |
| 2026-05-05 | Phase 4-B で env CHILD_BIRTH_DATE 廃止 → DB 一本化 | env で誤った生年月日を残すリスク回避、UI から書換可 | children テーブル |

---

## 8. 運用

詳細手順は別ドキュメントに分離:

- **デプロイ手順** (B 案 9 ステップ walkthrough): [README §0.5.1-0.5.2](../README.md)
- **DB 切替** (SQLite ↔ Postgres + Alembic): [README §0.5](../README.md)
- **LINE userId 取得手順**: [README §0.5 / Phase 1 残 TODO 対応](../README.md)
- **バックアップ / リストア**: [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md)
- **設定 UI 仕様**: [`SETTINGS.md`](SETTINGS.md)

### 8.1 監視・運用 (トラブルシュート)

| 症状 | 確認ポイント |
|---|---|
| 署名検証 401 | `LINE_CHANNEL_SECRET` と LINE Developers Console の Channel secret 一致確認 |
| 503 応答 | `.env` に LINE 認証情報が設定されているか、プロセス再起動後に反映されたか |
| 応答が返らない | `FAMILY_USER_IDS` に自分の LINE userId が入っているか (LINE Developers の userId は webhook ログから確認) |
| 取り込み時 `InvalidPiyologFileError` | ぴよログアプリから export した .txt をそのまま送信しているか (UTF-8 / cp932 自動判定) |
| サマリが空 | `event_date` (JST) と指定期間が一致しているか、`import_batches.rolled_back_at IS NULL` か |
| LLM 相談で 'capability_gap=tool_error' 多発 | tool_executor の DB 接続 / family_id 一致を確認 |

データ確認クエリ:
```bash
sqlite3 data/piyolog.db "SELECT event_date, event_type, COUNT(*) FROM piyolog_events GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 20;"
```

---

## 9. セキュリティ・プライバシー

### 9.1 データ分類

| 種類 | 例 | 取扱い |
|---|---|---|
| **PII** | LINE userId / 子の名前・生年月日 / 取り込んだ .txt の raw | DB のみ、analytics には sha256 hash で送信 |
| **機微情報** | 育児イベント (授乳・睡眠・体重) | family_id でアクセス制御、家族内共有 |
| **機密** | LINE channel secret / DATABASE_URL / Vertex AI ADC | Secret Manager (本番)、`.env` (gitignore) |
| **公開可** | docs / README / 設計判断 | — |

### 9.2 認証・認可

- **LINE Webhook**: HMAC-SHA256 署名検証 (LINE channel secret)
- **Family 集約**: `FAMILY_USER_IDS` で起動時に投入された LINE userId のみ受付、それ以外は silent drop
- **Bootstrap mode**: `FAMILY_USER_IDS` 未設定時は受信した userId を WARN ログに出すだけ (運用で設定したら通常モード)

### 9.3 既知のリスク・残課題

- 生年月日 / 名前は `children` テーブルに平文で保存 (個人プロジェクトのため pgcrypto は未実装)
- LLM 会話は 90 日保持しているが、自動削除のジョブは未実装 (Phase 5)
- 多家族テナント分離は未対応 (個人運用のため意図的)

---

## 10. テスト戦略

| レイヤ | 対象 | 状態 |
|---|---|---|
| Unit (parser) | regex の境界条件、状態機械 | 10+ ケース、`tests/test_parser.py` |
| Unit (services) | analytics / visualizer / context_builder / tool_executor / line_period | 各 module カバレッジ 80%+ |
| Integration | repository (SQLite / Postgres 両方)、LINE webhook stub | `test_event_repo.py` / `test_line_webhook.py` |
| LLM | consultation tool_use loop の deterministic mock | `test_consultation.py` |
| 全体 | 250+ tests PASS | CI で `make check` |

合計 250+ tests PASS (2026-05 時点)。手動 QA は LINE 実機での動作確認。

---

## 11. 関連ドキュメント

- [`../README.md`](../README.md) — Quickstart / GCP デプロイ手順 (B 案 9 ステップ) / LINE userId 取得 / DB 切替 / 監視・運用
- [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) — Phase 4-A バックアップ / リストア手順
- [`SETTINGS.md`](SETTINGS.md) — Phase 4-B 子情報 設定 UI 仕様
- [`../alembic/`](../alembic/) — DB マイグレーション
- [`../../docs/PROPOSALS/`](../../docs/PROPOSALS/) — モノレポ共通の機能個別 ADR
  - (Backfill 予定: Phase 4-B 子情報 DB の ADR、`docs/PROPOSALS/README.md` 参照)
- [モノレポ全体の設計テンプレート](../../docs/) — `SYSTEM_DESIGN_TEMPLATE.md` 等

---

## 12. 用語集

| 用語 | 意味 |
|---|---|
| family_id | 1 家族を束ねる ID。`FAMILY_USER_IDS` で複数 LINE userId を集約する単位 |
| child_id | 子の識別子。Phase 1 は `DEFAULT_CHILD_ID` 固定、Phase 5 で複数子対応予定 |
| import_batch | 1 回の .txt 取り込み単位。`rolled_back_at` で論理削除可 |
| capability_gap | LLM 相談で「対応できなかった理由」のタグ。asked_clarification / out_of_scope / data_missing / tool_error / refused / completed の 6 種 |
| piyolog event | ぴよログの 1 行 = 授乳 / 睡眠 / 排泄 / 体重 などの 1 イベント |
| RECENT CONTEXT | LLM に渡す直近 72h / 7d / 30d のサマリ + 子のプロフィール |
| consulting mode | LLM 相談モード。リッチメニューの「相談」ボタンで切替 |
