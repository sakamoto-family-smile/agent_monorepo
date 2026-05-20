# fujisawa-info-bot 設計書

| | |
|---|---|
| **Version** | 0.1 |
| **最終更新** | 2026-05-20 |
| **Status** | Draft |
| **Owner** | @kurama554101 |
| **README** | [`../README.md`](../README.md) |
| **設計原典** | [`../../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../../docs/PROPOSALS/0004-fujisawa-info-bot.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-05-19 | 0.1 | 初版 (Phase 0 雛形と同時に作成) |
| 2026-05-20 | 0.2 | Phase 2 (LangGraph Supervisor + Intent + RAG Agent) 確定 |

---

## 0. Executive Summary

proposal 0004 に基づき、 藤沢市公式 HP を一次ソースとする LINE Bot を新規構築する。
LangGraph Supervisor + 4 sub-agent (Intent / RAG / Crawl / Emergency) で、
`fujisawa-platform` (proposal 0003) を path dep で参照することで
クロール / 知識ベース / 出典 Skill を共通化する。

本ファイルは Phase ごとに「proposal 上の設計と、 実装で確定した詳細との差分 / 追加判断」 を記録する。

---

## 1. 設計原典

[`../../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../../docs/PROPOSALS/0004-fujisawa-info-bot.md) を一次ソースとする。 本ファイルでは
proposal で書ききれない実装レベルの詳細 (具体的な Pydantic schema、 関数シグネチャ、
SQL クエリ等) を Phase ごとに節を作って追加する。

---

## 2. Phase 0 (雛形) で確定した詳細

### 2.0 設計判断

- **dependencies は最小**: Phase 0 では FastAPI / uvicorn / pydantic / httpx + `fujisawa-platform` path dep のみ。 LangGraph / line-bot-sdk / Pub/Sub / Vertex AI 等は Phase 1+ で各 Phase の必要時に extras として追加していく方針。 1 Phase = 1 PR の粒度を保つため
- **`fujisawa-platform` を Phase 0 から path dep 宣言**: Phase 1 以降で必ず使うため、 雛形時点で import 経路を成立させる。 ただし Phase 0 の code 本体では import しない
- **`/health` endpoint のみ**: Cloud Run startup probe (Phase 7) で利用想定の単純 endpoint。 Phase 0 では CI で動作確認することを主目的とする
- **テスト構成**: pytest + `FastAPI TestClient` パターン。 dev-deps のみで完結し、 path dep 側の重い ML extras (vertex / pdf) を Phase 0 CI に持ち込まない

### 2.1 ディレクトリ構成

```
fujisawa-info-bot/
├── pyproject.toml
├── README.md
├── docs/
│   └── DESIGN.md  # 本ファイル
├── app/
│   ├── __init__.py
│   └── main.py    # FastAPI app
└── tests/
    ├── __init__.py
    └── test_main.py
```

Phase 1 以降の追加予定 (proposal 0004 §4.3 参照):

```
app/
├── line_handler.py     # Phase 1: 署名検証 / event 振り分け
├── graph/
│   ├── supervisor.py   # Phase 2: LangGraph Supervisor
│   ├── state.py        # Phase 2: InfoBotState (TypedDict)
│   └── agents/
│       ├── intent.py   # Phase 2
│       ├── rag.py      # Phase 2
│       ├── crawl.py    # Phase 4
│       └── emergency.py # Phase 6
├── skills/             # Phase 2-: info-bot 専用 Skill
├── tools/              # Phase 2-: MCP client / tool wrappers
└── batch/
    ├── crawl_weekly.py # Phase 5 (or fujisawa-platform 側で済む可能性検討)
    └── poll_rss.py     # Phase 6
```

### 2.2 `app/main.py` (Phase 0 時点)

`FastAPI` インスタンスを作り `/health` endpoint を生やすだけ。 LINE webhook / Pub/Sub
handler 等は Phase 1 以降で追加。

```python
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

### 2.3 CI 統合

`.github/workflows/pr-tests.yml` の `detect-changes` に `fujisawa_info_bot` output
を追加し、 `Test / fujisawa-info-bot` ジョブで `uv sync --dev` + `ruff check` + `pytest`
を実行する (driving-license-bot / fujisawa-platform と同パターン)。

terraform 系 / Cloud Build 系の CI 統合は Phase 7 で対応。

---

## 3. Phase 1 (LINE webhook + echo reply) で確定した詳細

### 3.0 設計判断

- **`line-bot-sdk` v3+ を default deps に昇格**: Phase 0 では extras だったが、 webhook が稼働ロジックの中心になるため default 化。 deps 重量は ~5 MB 増程度で許容範囲
- **`LineBotClient` を薄ラッパに**: driving-license-bot と同じ思想。 SDK の `WebhookParser` をそのまま expose せず、 bytes 直の署名検証パスを `verify_signature` として残しテスト容易性を上げる
- **シングルトン + `LINE_*` 未設定時 503**: env 未設定 (= Phase 0 状態 / 開発前) で webhook が来ると 503 を返す。 「開発者の設定漏れを早期検知」と「LINE 側の retry 抑止」 のバランス
- **個別 event 失敗を握りつぶし**: LINE は 200 以外を返すと retry してくる。 1 イベントの失敗で再送ループに入らないよう、 logger.exception でログだけ残して webhook 全体は 200 を維持

### 3.1 `app/config.py`

`pydantic-settings.BaseSettings` で env / `.env` から読む。 全変数は `FUJISAWA_INFO_BOT_` prefix:

| 変数 | 型 | default | 用途 |
|---|---|---|---|
| `LINE_CHANNEL_SECRET` | str | `""` | HMAC-SHA256 鍵 (webhook 署名検証用) |
| `LINE_CHANNEL_ACCESS_TOKEN` | str | `""` | Reply / Push API の Bearer |

`settings.line_configured` プロパティで両方が揃っているか判定。

### 3.2 `app/line_client.py`

| API | 用途 |
|---|---|
| `LineBotClient.verify_signature(body, signature)` | LINE 公式仕様 (HMAC-SHA256 → base64) で X-Line-Signature 検証 |
| `LineBotClient.parse_events(body, signature)` | SDK の `WebhookParser.parse` をラップ。 失敗時 `InvalidSignatureError` |
| `LineBotClient.reply_text(reply_token, messages)` | テキスト Reply Message (1 回最大 5 通) |
| `get_line_bot_client()` | グローバルシングルトン。 未設定時は `None` |
| `reset_line_bot_client()` | テスト用 |

### 3.3 `app/routes/line.py`

`POST /webhook` の挙動:

| 入力 | レスポンス | 処理 |
|---|---|---|
| LINE_* 未設定 | 503 | 設定漏れ早期検知 |
| 無効署名 | 401 | tamper / 不正リクエスト |
| 有効署名 + text MessageEvent | 200 | 本文をそのまま echo reply |
| 有効署名 + sticker/image/etc. | 200 | 無視 (Phase 2+ で Crawl/RAG 経路に置換) |
| event 内例外 | 200 | logger.exception + 次 event へ |

### 3.4 テスト構成

- `tests/test_line_client.py` 8 件
  - HMAC 検証 (valid / empty / mismatched / tampered body)
  - constructor の必須引数バリデーション
  - シングルトン (未設定時 None / 設定時 同一インスタンス)
- `tests/routes/test_line.py` 5 件
  - 503 (LINE 未設定)
  - 401 (無効署名)
  - text echo
  - 非 text 無視
  - 複数 event の順次処理
- LINE Channel 実値は不要 (mock secret / token で完結)

### 3.5 ローカル smoke (実 LINE 連携時)

LINE Developer Console > Messaging API Channel を作成し、 secret / access token を `.env` に投入してから:

```bash
uv run uvicorn app.main:app --reload --port 8080
ngrok http 8080
# https://xxxx.ngrok.io/webhook を LINE webhook URL に登録
```

`.env` 投入は本 PR 範囲外 (Phase 7 deploy 時に Secret Manager 経由で本格管理)。

---

## 4. Phase 2 (LangGraph Supervisor + Intent + RAG Agent) で確定した詳細

### 4.0 設計判断

- **LLM provider は Vertex Anthropic Claude を採用** (proposal §4.5 の Gemini default から逸脱)
  - 理由: 共有パッケージ `llm-client` (`VertexAnthropicLLMClient`) が完備されており、 即動かせる
  - 影響: コスト試算 (proposal §5.4) を Anthropic Vertex の単価で再評価する必要あり (follow-up backlog)
  - Gemini 対応は `llm-client` 拡張 PR で後追い予定 ([[project_fujisawa_info_bot_followup]] に記録)
- **同期 graph 実行を採用** (Phase 2 範囲)
  - 理由: Pub/Sub 統合 (Phase 3) を別 PR にする方針。 Phase 2 PR を小さく保つ
  - 制約: LINE webhook 3 秒タイムアウトに対し、 mock + InMemoryStore なら問題なし。 本番 (vertex_anthropic + pgvector) は Phase 7 デプロイ時に実測予定
- **LangGraph を Phase 2 から採用** (proposal 準拠)
  - 理由: Phase 4 (Crawl) 追加時に branch を増やすだけで済むよう、 雛形を早めに整える
  - 範囲: `classify → conditional → rag | out_of_scope → END` の 3 node 構成 (intent + rag + out_of_scope)
- **Skill prompt は markdown を `load_skill()` で動的読込**
  - 理由: 人間が編集する prompt を python 文字列に埋めると編集体験が悪い。 `app/skills/*.md` を Skill としてキャッシュ付きで読込む
  - `category_routing.md` が Phase 2 唯一の Skill。 Phase 4+ で `flex_message.md` / `feedback_response.md` 等を追加
- **MockLLM + InMemoryStore + MockEmbedding を CI default に**
  - 理由: 本番 vendor 呼出をテストに混ぜない (driving-license-bot / fujisawa-platform と同パターン)
  - 副作用: `settings.llm_provider=mock` + `kb_store_mode=inmemory` + `embedding_provider=mock` のとき env を 1 つも設定せず動く
- **出典フッタは LLM 任せにしない**
  - 理由: 「公式 HP の出典 URL を必ず付ける」は本 Bot の核機能であり、 LLM 出力 verify を最小化したい
  - 実装: `rag.py` の `_format_citations()` が `SearchHit` の URL を最大 3 件 (重複除外) で末尾に固定形式で付与

### 4.1 ディレクトリ構成 (Phase 2 で追加)

```
app/
├── llm.py                    # build_llm_client (mock | vertex_anthropic)
├── kb.py                     # build_knowledge_backend (inmemory | pgvector)
├── graph/
│   ├── __init__.py           # public API: build_graph / run_graph / InfoBotState / Intent / GraphDependencies
│   ├── state.py              # InfoBotState TypedDict (total=False)
│   ├── supervisor.py         # LangGraph build_graph + run_graph + GraphDependencies
│   └── agents/
│       ├── intent.py         # classify_intent → IntentResult
│       └── rag.py            # answer_with_rag → (text, hits)
├── skills/
│   ├── __init__.py           # load_skill(name) — lru_cache
│   └── category_routing.md   # 7 カテゴリ分類 Skill
```

### 4.2 `app/config.py` 追加項目

| 変数 | 型 / default | 用途 |
|---|---|---|
| `LLM_PROVIDER` | `mock` \| `vertex_anthropic` (default `mock`) | LLM 実装の切替 |
| `GCP_PROJECT_ID` | str | vertex_anthropic / vertex embedding 時必須 |
| `VERTEX_REGION` | str (default `us-east5`) | Claude が host されている region |
| `ANTHROPIC_MODEL` | str (default `claude-haiku-4-5@20251001`) | Vertex 形式 |
| `LLM_MAX_TOKENS` | int (default 1024) | max_tokens |
| `KB_STORE_MODE` | `inmemory` \| `pgvector` (default `inmemory`) | 知識ベース実装 |
| `EMBEDDING_PROVIDER` | `mock` \| `vertex` (default `mock`) | embedding 実装 |
| `EMBEDDING_DIM` | int (default 768) | vertex の場合 768 固定 |
| `CLOUD_SQL_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_DATABASE` | str | pgvector 接続情報 |
| `RAG_ENABLED` | bool (default true) | RAG 経路 ON/OFF (Phase 2 ではまだ未使用 / Phase 3 で利用) |
| `RAG_TOP_K` | int (default 5) | top-k 件数 |

### 4.3 `app/graph/state.py` (InfoBotState)

```python
class InfoBotState(TypedDict, total=False):
    user_id: str
    query: str
    intent: Literal["rag", "out_of_scope"]
    category: str | None
    rag_hits: list[SearchHit]
    final_text: str
```

`total=False` により各 node が必要なキーだけ書き込めばよい。 proposal §4.4 の
`messages` / `user_profile` / `crawl_pages` / `final_response (FlexMessage)` は
Phase 4+ で追加。

### 4.4 `app/graph/agents/intent.py`

| 関数 | 入力 | 出力 |
|---|---|---|
| `classify_intent(query, llm)` | `str`, `LLMClient` | `IntentResult` (intent / category / confidence) |

- 空 query → `out_of_scope` 固定 (LLM 呼出無し)
- `_VALID_CATEGORIES` = `disaster, parenting, garbage, procedure, tourism, cityhall, other`
- `other` カテゴリ + confidence ≥ 0.5 → `out_of_scope`
- confidence < 0.5 → category None で全体検索 (RAG 救済)
- LLM 出力に ```json ``` 等のラッパーが混入しても regex で最初の `{}` を取り出す
- LLM 失敗 / JSON parse 失敗 → conservative に `rag + category=None + confidence=0.0`

### 4.5 `app/graph/agents/rag.py`

| 関数 | 入力 | 出力 |
|---|---|---|
| `answer_with_rag(query, embedding, store, llm, top_k, category)` | full kwargs | `(final_text, hits)` |

flow:

1. `embedding.embed(query)` → query_vec
2. `store.search_pages(query_vec, top_k=, category=)` → top-k SearchHit
3. ヒット 0 件 → `_NO_HIT_TEXT` (固定文 + コンタクトセンター案内) を返す
4. LLM に system (`_SYSTEM_PROMPT`) + 抜粋 (最大 800 文字 × top_k 件) を渡す
5. `_format_citations(hits)` で URL 重複除去 + 最大 3 件のフッタを付与
6. LLM 例外時は固定の fallback 本文 + 出典フッタのみ

### 4.6 `app/graph/supervisor.py`

```
START → classify → conditional ──▶ rag → END
                              └─▶ out_of_scope → END
```

- `GraphDependencies` (LLMClient / EmbeddingClient / KnowledgeStore / top_k) を DI
- `build_graph(deps)` で compile 済 graph を返す
- `run_graph(deps, user_id, query)` でヘルパとして 1 ターン実行 → `final_text`

### 4.7 webhook (`app/routes/line.py`) 更新

- `request.app.state.graph_deps` から DI 取得
- `_handle_event` を async 化、 text MessageEvent → `run_graph()` で graph 実行 → `client.reply_text(reply_token, [answer])`
- 既存挙動 (503 / 401 / 非 text 無視) は維持

### 4.8 `app/main.py` lifespan

- startup で `build_llm_client(settings)` + `await build_knowledge_backend(settings)` を実行
- `app.state.graph_deps = GraphDependencies(...)` / `app.state.kb_pool = backend.pool`
- shutdown で `kb_pool.close()` (pgvector 時のみ非 None)

### 4.9 テスト構成

| ファイル | 件数 | 内容 |
|---|---|---|
| `tests/graph/test_intent.py` | ~14 | classify_intent の全分岐 (empty / valid / low conf / other / invalid / LLM 例外) |
| `tests/graph/test_rag.py` | 7 | empty / no hit / 1 hit / 重複 URL / cap 3 / LLM 失敗 / category filter |
| `tests/graph/test_supervisor.py` | 4 | run_graph end-to-end (空 / no data / out_of_scope / 出典付き) |
| `tests/graph/test_factories.py` | 4 | build_llm_client / build_knowledge_backend の分岐 |
| `tests/routes/test_line.py` | 6 | webhook (503 / 401 / no hit / 出典付き / 非 text 無視 / 複数 event) |

`asyncio.run()` で seed する箇所が 1 件あるが、 test の async 関数本体ではないので副作用は限定的。

### 4.10 Phase 2 で意図的に未対応にしたもの

- Pub/Sub 非同期化 (Phase 3 で別 PR)
- Firestore (sessions / feedback) — Phase 8
- Crawl Agent (リンク追跡) — Phase 4
- Emergency Agent + RSS poll — Phase 6
- Vertex Gemini — `llm-client` 拡張 PR で対応予定
- Flex Message (LINE リッチ表示) — Phase 8

---

## 5. Phase 3 以降の予定

本ファイルは Phase ごとに節を追加していく。 各 Phase 完了 PR で:

1. 該当 Phase の節を新規追加 (例: `## 5. Phase 3 (Pub/Sub 非同期 reply) で確定した詳細`)
2. 設計判断 / 確定スキーマ / 関数シグネチャを記録
3. proposal との差分があれば明示
