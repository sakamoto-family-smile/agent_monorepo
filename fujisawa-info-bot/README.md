# fujisawa-info-bot

藤沢市公式 HP を一次ソースとし、 自然言語の質問に **出典 URL 付き** で回答する
LINE Bot エージェント。 RAG + リンク 1 階層追跡 + 緊急情報プッシュ + 多言語誘導
を提供する。

> **Status**: Phase 2 (LangGraph + RAG) + Phase 7 (terraform / Cloud Run deploy) 完了。
> Pub/Sub 非同期化 / Crawl / Emergency push / Feedback は順次 Phase 3+ で実装。

設計詳細は [`../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../docs/PROPOSALS/0004-fujisawa-info-bot.md) 参照。
本 README は「動かす / 取り込む」観点に絞る。

---

## 0. Quickstart

### 0.1 前提

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | パッケージマネージャ |
| docker (任意) | — | ローカル smoke 用 (Phase 7+) |

### 0.2 セットアップ

```bash
cd fujisawa-info-bot
uv sync --dev
```

`fujisawa-platform` を path dep で参照しているため、 親リポジトリ全体を clone
した状態で実行すること。

### 0.3 ローカル起動 (Phase 1)

`.env.example` を `.env` に copy して LINE Channel の値を埋める:

```bash
cp .env.example .env
$EDITOR .env  # LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN を埋める
```

起動:

```bash
uv run uvicorn app.main:app --reload --port 8080
# 別ターミナルで
curl http://localhost:8080/health
# → {"status":"ok"}
```

LINE Platform から webhook を届かせるには ngrok 等で外部公開する:

```bash
ngrok http 8080
# 生成された https://xxxx.ngrok.io/webhook を LINE Developer Console >
# Messaging API > Webhook URL に登録 (末尾に /webhook を忘れない)
```

`.env` が未設定 (LINE_* 空文字列) の状態だと `/webhook` は **503** を返す。
これは「設定漏れを早期検知する」 ための意図的挙動。

### 0.4 テスト

```bash
uv run pytest tests/ -q
uv run ruff check app tests
```

---

## 1. 設計概要

proposal 0004 の設計を読んでから本 README に戻ること。 概要のみ:

- **2 サービス構成**: `api` (FastAPI / Webhook 受け) + `agent-core` (LangGraph Supervisor)
- **path dep**: [`fujisawa-platform`](../fujisawa-platform/) (knowledge_base / crawler / skills / pdf_pipeline)
- **LLM**: Vertex AI Gemini (default) + Anthropic Claude (fallback)
- **データ**: Firestore (users / sessions / feedback) + Cloud SQL (`fujisawa_kb_db` を fujisawa-platform 経由で参照)

---

## 2. 環境変数 (Phase 2 時点)

`.env.example` を参照。 全変数は `FUJISAWA_INFO_BOT_` prefix。

| 変数 | 必須 | 用途 |
|---|---|---|
| `LINE_CHANNEL_SECRET` | LINE 連携 | webhook 署名検証用 HMAC 鍵 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE 連携 | Reply Message API の Bearer |
| `LLM_PROVIDER` | optional (default `mock`) | `mock` / `vertex_anthropic` |
| `GCP_PROJECT_ID` | `vertex_anthropic` 時必須 | Vertex AI を使う GCP project |
| `VERTEX_REGION` | optional (default `us-east5`) | Vertex AI region |
| `ANTHROPIC_MODEL` | optional | Vertex 形式モデル名 (例: `claude-haiku-4-5@20251001`) |
| `KB_STORE_MODE` | optional (default `inmemory`) | `inmemory` / `pgvector` |
| `EMBEDDING_PROVIDER` | optional (default `mock`) | `mock` / `vertex` |
| `EMBEDDING_DIM` | optional (default `768`) | Vertex の場合 768 固定 |
| `CLOUD_SQL_HOST` / `_USER` / `_PASSWORD` / `_DATABASE` | `pgvector` 時必須 | Cloud SQL fujisawa_kb_db への接続 |
| `RAG_ENABLED` | optional (default `true`) | RAG 経路 ON/OFF |
| `RAG_TOP_K` | optional (default `5`) | top-k 取得件数 |

Phase 3+ で Pub/Sub / Cloud Tasks / Firestore 等が追加される。

---

## 3. ディレクトリ構成

```
fujisawa-info-bot/
├── pyproject.toml                       # uv project, fujisawa-platform / llm-client path dep
├── .env.example                         # 環境変数テンプレ
├── README.md
├── docs/
│   └── DESIGN.md                        # SYSTEM_DESIGN_TEMPLATE 準拠
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI entrypoint, lifespan で graph 初期化
│   ├── config.py                        # pydantic-settings (LINE / LLM / KB)
│   ├── line_client.py                   # LineBotClient + 署名検証
│   ├── llm.py                           # build_llm_client (mock | vertex_anthropic)
│   ├── kb.py                            # build_knowledge_backend (inmemory | pgvector)
│   ├── graph/
│   │   ├── state.py                     # InfoBotState TypedDict
│   │   ├── supervisor.py                # LangGraph build_graph + run_graph
│   │   └── agents/
│   │       ├── intent.py                # classify_intent
│   │       └── rag.py                   # answer_with_rag (検索 + LLM + 出典)
│   ├── skills/
│   │   ├── __init__.py                  # load_skill ヘルパ
│   │   └── category_routing.md          # 7 カテゴリ分類 Skill prompt
│   └── routes/
│       └── line.py                      # POST /webhook → graph 実行
└── tests/
    ├── test_main.py
    ├── test_line_client.py
    ├── graph/
    │   ├── test_intent.py
    │   ├── test_rag.py
    │   ├── test_supervisor.py
    │   └── test_factories.py
    └── routes/
        └── test_line.py
```

Phase 3+ で `app/batch/` (RSS poll) / `app/pubsub/` 等を順次追加していく (proposal 0004 §4.3 参照)。

---

## 4. Phase Roadmap

| Phase | 内容 | env flag |
|---|---|---|
| **Phase 0** | 雛形 — pyproject + README + FastAPI `/health` + CI 統合 (完了 PR #142) | — |
| **Phase 1** | LINE webhook (FastAPI) + 署名検証 + 単純 echo reply (完了 PR #143) | — |
| **Phase 2** | LangGraph Supervisor + Intent Agent + RAG Agent (出典 URL 付き) (完了 PR #144) | `RAG_ENABLED=true` |
| **Phase 3** | Pub/Sub 経由の非同期 reply (3 秒 timeout 対策) | — |
| **Phase 4** | Crawl Agent (リンク 1 階層追跡) | `CRAWL_ENABLED=true` |
| **Phase 5** | weekly_crawl batch (KB 投入 ETL) — fujisawa-platform 側で実装 (完了 PR #146 + #147 fix) | — |
| **Phase 6** | Emergency RSS poll + Cloud Tasks + opt-in/out | `EMERGENCY_ENABLED=true` |
| **Phase 7** | terraform / Cloud Run / LINE Channel 連携 (本 PR) | — |
| **Phase 8** | Feedback (👍👎) / リッチメニュー / 多言語誘導 / observability | — |

---

## 5. 関連ドキュメント

- [`../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../docs/PROPOSALS/0004-fujisawa-info-bot.md) — 本エージェント設計
- [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — 共通基盤
- [`../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md`](../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md) — 事前調査
- [`docs/DESIGN.md`](docs/DESIGN.md) — Phase ごとの設計詳細記録
- [`docs/SETUP.md`](docs/SETUP.md) — Phase 7 deploy runbook (terraform / LINE Channel)
