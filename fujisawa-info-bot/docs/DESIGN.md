# fujisawa-info-bot 設計書

| | |
|---|---|
| **Version** | 0.1 |
| **最終更新** | 2026-05-19 |
| **Status** | Draft |
| **Owner** | @kurama554101 |
| **README** | [`../README.md`](../README.md) |
| **設計原典** | [`../../docs/PROPOSALS/0004-fujisawa-info-bot.md`](../../docs/PROPOSALS/0004-fujisawa-info-bot.md) |

## 変更履歴

| 日付 | Version | 変更内容 |
|---|---|---|
| 2026-05-19 | 0.1 | 初版 (Phase 0 雛形と同時に作成) |

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

## 3. Phase 1 以降の予定

本ファイルは Phase ごとに節を追加していく。 各 Phase 完了 PR で:

1. 該当 Phase の節を新規追加 (例: `## 3. Phase 1 (LINE webhook) で確定した詳細`)
2. 設計判断 / 確定スキーマ / 関数シグネチャを記録
3. proposal との差分があれば明示
