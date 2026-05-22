# edinet-client

金融庁 EDINET API v2 の薄いラッパパッケージ (proposal 0006)。 stock-analysis-agent
を始めとする monorepo 内エージェントから path dep で利用する。

## 設計原典

[`../docs/PROPOSALS/0006-edinet-integration.md`](../docs/PROPOSALS/0006-edinet-integration.md)

## 主要 API

```python
from edinet_client import EdinetClient, DocumentType, LocalCache

client = EdinetClient(
    api_key="YOUR_API_KEY",
    cache=LocalCache(root="./data/edinet"),
    user_agent="my-app/0.1 (https://example.com/contact)",
)

# 1) 文書 INDEX 取得 (daily batch 用)
docs = await client.list_documents(date(2026, 5, 22))

# 2) 本体取得 (cache 経由)
body = await client.download(document_id="S100ABC1", content_type="pdf")
```

## Phase 状況

| Phase | 内容 | 状態 |
|---|---|---|
| **Phase 1a** | HTTP client + types + LocalCache + tests | 本 PR |
| Phase 1b | code_resolver (ticker → EDINET code) | 別 PR |
| Phase 1c | GcsCache 実装 | 別 PR |
| Phase 1d | stock-analysis-agent への統合 | 別 PR |
| Phase 1e | daily batch (Cloud Run Job + Cloud SQL) | 別 PR |
| Phase 2 | XBRL parser (`[xbrl]` extras) | 別 PR |

## 利用

monorepo 内の path dep として:

```toml
# stock-analysis-agent/pyproject.toml
[tool.uv.sources]
edinet-client = { path = "../edinet-client" }

dependencies = [
    "edinet-client",
]
```

## EDINET API key の取得

無料登録 (個人 / 商用とも可):
- <https://disclosure2.edinet-fsa.go.jp/weee0010.aspx> から「API利用申請」

## 開発

```bash
cd edinet-client
uv sync --dev
uv run pytest tests/ -q
uv run ruff check edinet_client tests
```

## ライセンス

EDINET API は金融庁が無料提供する公開 API。 本パッケージは EDINET API の利用規約
(<https://disclosure2.edinet-fsa.go.jp/weee0030.aspx>) に従う。
