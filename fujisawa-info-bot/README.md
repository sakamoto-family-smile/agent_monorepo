# fujisawa-info-bot

藤沢市公式 HP を一次ソースとし、 自然言語の質問に **出典 URL 付き** で回答する
LINE Bot エージェント。 RAG + リンク 1 階層追跡 + 緊急情報プッシュ + 多言語誘導
を提供する。

> **Status**: Phase 0 (雛形) — pyproject + FastAPI `/health` のみ。
> 実機能 (LINE webhook / LangGraph / RAG / Emergency push) は順次 Phase 1+ で
> 実装。

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

### 0.3 ローカル起動 (Phase 0)

```bash
uv run uvicorn app.main:app --reload --port 8080
# 別ターミナルで
curl http://localhost:8080/health
# → {"status":"ok"}
```

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

## 2. 環境変数 (Phase 0 時点)

Phase 0 では FastAPI 起動のみで実機能は無いため設定不要。 Phase 1+ で `.env.example` を整備予定。

---

## 3. ディレクトリ構成

```
fujisawa-info-bot/
├── pyproject.toml             # uv project、 fujisawa-platform を path dep
├── README.md
├── docs/
│   └── DESIGN.md              # SYSTEM_DESIGN_TEMPLATE 準拠
├── app/
│   ├── __init__.py
│   └── main.py                # FastAPI entrypoint (Phase 0: /health のみ)
└── tests/
    ├── __init__.py
    └── test_main.py
```

Phase 1+ で `app/line_handler.py` / `app/graph/` / `app/skills/` / `app/batch/` 等を順次追加していく (proposal 0004 §4.3 参照)。

---

## 4. Phase Roadmap

| Phase | 内容 | env flag |
|---|---|---|
| **Phase 0** | 雛形 (本 PR) — pyproject + README + FastAPI `/health` + CI 統合 | — |
| **Phase 1** | LINE webhook (FastAPI) + 署名検証 + 単純 echo reply | — |
| **Phase 2** | LangGraph Supervisor + Intent Agent + RAG Agent (出典 URL 付き) | `RAG_ENABLED=true` |
| **Phase 3** | Pub/Sub 経由の非同期 reply (3 秒 timeout 対策) | — |
| **Phase 4** | Crawl Agent (リンク 1 階層追跡) | `CRAWL_ENABLED=true` |
| **Phase 5** | weekly_crawl batch (KB 投入 ETL) — fujisawa-platform reuse 検討 | — |
| **Phase 6** | Emergency RSS poll + Cloud Tasks + opt-in/out | `EMERGENCY_ENABLED=true` |
| **Phase 7** | terraform / Cloud Run deploy / Cloud Scheduler | — |
| **Phase 8** | Feedback (👍👎) / リッチメニュー / 多言語誘導 / observability | — |

---

## 5. 関連ドキュメント

- [`../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../docs/PROPOSALS/0004-fujisawa-info-bot.md) — 本エージェント設計
- [`../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md`](../docs/PROPOSALS/0003-fujisawa-platform-shared-base.md) — 共通基盤
- [`../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md`](../docs/PROPOSALS/notes/fujisawa-platform-investigation-2026-05-09.md) — 事前調査
- [`docs/DESIGN.md`](docs/DESIGN.md) — Phase ごとの設計詳細記録
