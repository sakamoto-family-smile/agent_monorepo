# syntax=docker/dockerfile:1.7
#
# fujisawa-info-bot Cloud Run Service 用イメージ。
#
# FastAPI + uvicorn で LINE webhook を受け、 LangGraph (Intent + RAG) で
# fujisawa_kb_db (pgvector) を検索し、 出典 URL 付きで返信する。
#
# build (リポジトリルートから — fujisawa-platform / llm-client を path dep で
# 参照するため):
#   DOCKER_BUILDKIT=1 docker build -f fujisawa-info-bot/Dockerfile \
#     -t fujisawa-info-bot:local .
#
# run (local smoke):
#   docker run --rm -p 8080:8080 \
#     -e FUJISAWA_INFO_BOT_LLM_PROVIDER=mock \
#     -e FUJISAWA_INFO_BOT_KB_STORE_MODE=inmemory \
#     -e PORT=8080 \
#     fujisawa-info-bot:local

# ---------------------------------------------------------------------------
# Stage 1: builder (uv で deps を解決し、 wheel-only な venv を作る)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# path dep が解決できるよう、 fujisawa-platform と llm-client を image に同梱する。
# pyproject.toml の path 解決パスは ../fujisawa-platform / ../llm-client なので、
# fujisawa-info-bot を `/app/fujisawa-info-bot` に置く構成にする。
COPY fujisawa-platform/pyproject.toml /app/fujisawa-platform/pyproject.toml
COPY fujisawa-platform/uv.lock* /app/fujisawa-platform/
COPY fujisawa-platform/README.md /app/fujisawa-platform/README.md
COPY fujisawa-platform/fujisawa_platform /app/fujisawa-platform/fujisawa_platform

COPY llm-client/pyproject.toml /app/llm-client/pyproject.toml
COPY llm-client/README.md /app/llm-client/README.md
COPY llm-client/llm_client /app/llm-client/llm_client

COPY fujisawa-info-bot/pyproject.toml /app/fujisawa-info-bot/pyproject.toml
COPY fujisawa-info-bot/uv.lock* /app/fujisawa-info-bot/
COPY fujisawa-info-bot/README.md /app/fujisawa-info-bot/README.md

WORKDIR /app/fujisawa-info-bot

# 依存解決 (本体 import まで成立させる必要があるので extra も含める)。
#   - vertex:    本番 LLM (anthropic[vertex])
#   - pgvector:  本番 KB (asyncpg + pgvector + fujisawa-platform pgvector extra)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --no-editable \
        --extra vertex --extra pgvector

COPY fujisawa-info-bot/app /app/fujisawa-info-bot/app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable \
        --extra vertex --extra pgvector

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# tini: signal handling (Cloud Run の SIGTERM を uvicorn に届ける)
# ca-certificates: HTTPS 検証 (httpx + Vertex + LINE API)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/fujisawa-info-bot/.venv/bin:${PATH}" \
    PORT=8080

WORKDIR /app/fujisawa-info-bot

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

COPY --from=builder --chown=runner:runner /app/fujisawa-info-bot/.venv /app/fujisawa-info-bot/.venv
COPY --from=builder --chown=runner:runner /app/fujisawa-info-bot/app /app/fujisawa-info-bot/app
COPY --from=builder --chown=runner:runner /app/fujisawa-platform/fujisawa_platform /app/fujisawa-platform/fujisawa_platform
COPY --from=builder --chown=runner:runner /app/llm-client/llm_client /app/llm-client/llm_client

USER runner

EXPOSE 8080

# Cloud Run は $PORT を渡してくる。 uvicorn は :8080 default だが念のため env 経由。
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
