# llm-gateway

エージェントの LLM 呼び出しを集める gateway 一式 (設計: [PROPOSAL-0014](../docs/PROPOSALS/0014-llm-gateway.md))。
LiteLLM Proxy と Langfuse をローカルの docker compose で動かす (GCP 版は PROPOSAL-0014 の PR4)。

| 部品 | 中身 | 公開先 |
|---|---|---|
| `litellm` | LiteLLM Proxy v1.108.3 (ダイジェスト固定)。別名 `stock-analysis` / `stock-analysis-next` | `127.0.0.1:4000` と、エージェント用のネットワーク `llm-gateway-agents` (`http://litellm:4000`) |
| `litellm-db` | gateway 用の Postgres (バーチャルキー・予算・利用額) | compose 内のみ |
| Langfuse | 公式 compose (`langfuse/upstream-docker-compose.yml`, v4.76.0) + `langfuse/override.yml` | 画面 `127.0.0.1:3000` |

## 起動

```bash
cp config/gateway.env.example config/gateway.env    # 値を入れる
cp config/langfuse.env.example config/langfuse.env  # 値を入れる
make up
make health
```

## バーチャルキーの発行

エージェントごとにキーを分け、使える別名・30 日あたりの上限 (API 料金換算の USD)・1 分あたりの回数を付ける。
キーは `ENV_FILE` の `LLM_GATEWAY_KEY` に書き込まれ、画面には出ない。

```bash
make key ALIAS=stock-analysis-agent ENV_FILE=../stock-analysis-agent/config/local.env
# 上限を変える: python3 scripts/issue_key.py stock-analysis-agent --budget 50 --rpm 20 --env-file ...
```

定額プランの間も、上限は LiteLLM が API 料金換算で数えるので、超えると呼び出しが断られる。

## エージェント側の設定 (Agent SDK / Claude Code)

stock-analysis-agent は `LLM_GATEWAY_URL` / `LLM_GATEWAY_KEY` / `LLM_GATEWAY_MODEL` / `LLM_MODEL` を設定すると、
下の環境変数と `modelOverrides` を自分で組み立てる (`app/agents/llm_options.py`)。
ローカル本番の compose は `llm-gateway-agents` ネットワークに入るので、先にここで `make up` しておく。

| 環境変数 | 値 |
|---|---|
| `ANTHROPIC_BASE_URL` | gateway の URL |
| `ANTHROPIC_CUSTOM_HEADERS` | `x-litellm-api-key: Bearer <バーチャルキー>` と、分析ごとの `x-litellm-trace-id: <32 桁の 16 進>` を改行で並べる |
| `CLAUDE_CODE_OAUTH_TOKEN` | 定額プランのトークン (Vertex AI に移るまで)。gateway がそのまま Anthropic に渡す |
| `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` | 設定しない (定額プランのトークンの代わりに送られる) |

Claude Code の設定 `modelOverrides` で別名を既知のモデルに対応付ける (例: `{"claude-opus-5-5": "stock-analysis"}`)。
対応付けがないと CLI は別名を未知のモデルとして扱い、毎回 1 本目の呼び出しが 400 で失敗してから送り直す。

## Langfuse v4 の注意

- v4 は OpenTelemetry でしかトレースを受けない。LiteLLM の callback は `langfuse_otel` を使う。
- `x-litellm-trace-id` は Langfuse の **session ID** になる (トレースは呼び出しごと)。分析 1 回 = 1 セッションとして扱う。
- 従来のトレース・スコア読み出し API は使えない。スコアの書き込み (`POST /api/public/scores`、`sessionId` 指定可)、データセット、Annotation Queue、`/api/public/v2/observations`、`/api/public/v2/metrics` は使える。
