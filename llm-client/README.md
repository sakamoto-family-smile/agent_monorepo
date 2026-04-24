# llm-client

モノレポ横断の薄い Anthropic Claude API ラッパ。prompt caching・複数ターン会話・observability フック (on_call) を提供する。

## 位置付け

| プロジェクト | 用途 |
|---|---|
| `llm-client` (本パッケージ) | 単発 / 複数ターンの `messages.create` + prompt caching。簡単な要約・分類・QA・相談 |
| `claude-agent-sdk` | 多ターンエージェント + MCP ツール利用。`stock-analysis-agent` / `hotcook-agent` / `kanie-lab-agent` が採用 |

両者は直交し、共存できる。

## 消費者

| プロジェクト | ステータス |
|---|---|
| `lifeplanner-agent` | ✅ 利用中 (shim 経由) |
| `piyolog-analytics` Phase 3 (相談機能) | 🔜 予定 |
| `tech-news-agent` Phase 1 (要約・スコアリング) / Phase 2 (QA) | 🔜 予定 |

## 使い方

```python
from llm_client import AnthropicLLMClient, MockLLMClient
from llm_client.analytics import make_analytics_on_call

# observability (analytics-platform 連携、optional)
def _get_logger():
    try:
        from instrumentation import get_analytics_logger
        return get_analytics_logger()
    except Exception:
        return None

client = AnthropicLLMClient(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    model="claude-sonnet-4-6",
    max_tokens=1024,
    on_call=make_analytics_on_call(_get_logger),
)

# 単発 (system に cache_control 付与)
reply = await client.complete(
    system="You are a helpful assistant...",
    user="Hello",
    cache_system=True,
)

# 複数ターン
reply = await client.complete_messages(
    system="You are...",
    messages=[
        {"role": "user", "content": "過去の質問"},
        {"role": "assistant", "content": "過去の回答"},
        {"role": "user", "content": "今回の質問"},
    ],
    cache_system=True,
)
```

## 設計方針

- **Settings ハードコードなし**: API key / model / max_tokens は明示的に渡す
- **observability は callback で疎結合**: `on_call` が呼ばれるだけ。analytics-platform などへの emit は消費者が決める
- **analytics-platform 連携は optional モジュール**: `llm_client.analytics.make_analytics_on_call` でほぼボイラープレートなしに連携可能、ただし import しなければ analytics-platform への依存は発生しない
- **MockLLMClient**: `fixed_reply` でテスト時に差し替え可能

## API

### Public exports (`llm_client`)

| 名前 | 種別 | 用途 |
|---|---|---|
| `LLMClient` | Protocol | テストで差替え可能な抽象 |
| `AnthropicLLMClient` | class | Anthropic API 直 |
| `VertexAnthropicLLMClient` | class | GCP Vertex AI (ADC 認証) |
| `MockLLMClient` | class | オフライン・テスト用 |
| `ChatMessage` | TypedDict | `{"role": "user" | "assistant", "content": str}` |
| `OnCallCallback` | Callable | `(LlmCallEvent) -> None` |
| `LlmCallEvent` | TypedDict | provider / model / resp / latency_ms / error |
| `system_payload(text, *, cache: bool)` | function | system プロンプトを cache_control 付きブロック or 生 str に変換 |

### Analytics helper (`llm_client.analytics`)

| 名前 | 用途 |
|---|---|
| `make_analytics_on_call(logger_factory)` | `analytics-platform` の `AnalyticsLogger` に `llm_call` event を emit する `on_call` を生成 |

## Tests

```bash
cd llm-client
uv sync
uv run pytest -v
```

17 件 (system_payload / Mock / Anthropic wire format / on_call / analytics helper)。

## 依存関係

- `anthropic >= 0.30.0` (AsyncAnthropic + AsyncAnthropicVertex を含む)
- その他なし (pydantic / pydantic-settings 不要、consumer が持てば良い)
