# syntax=docker/dockerfile:1.7
#
# driving-license-bot Cloud Run service 用イメージ。
#
# build (リポジトリルートから):
#   DOCKER_BUILDKIT=1 docker build -f driving-license-bot/Dockerfile -t driving-license-bot:local .
#
# `pyproject.toml` が path dep (`../analytics-platform`) を持つため、
# build context は **リポジトリルート** であることが必須。
# `make docker-build` がそれを面倒見る。
#
# run (local):
#   docker run --rm -p 8080:8080 \
#     -e LINE_CHANNEL_SECRET=... -e LINE_CHANNEL_ACCESS_TOKEN=... \
#     driving-license-bot:local

# ---------------------------------------------------------------------------
# Stage 1: builder (uv で deps を解決し、wheel-only な venv を作る)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# path dep 解決のため analytics-platform を sibling 配置
COPY analytics-platform /analytics-platform
COPY driving-license-bot/pyproject.toml /app/
# uv.lock があれば使う（無い時は `uv sync` で生成される）
COPY driving-license-bot/uv.lock* /app/

WORKDIR /app

# 依存解決のみ（本体は後段でコピー）
# pgvector extra も含める: 同一 image を line-bot service / batch Job 両方で使うため。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --no-editable --extra pgvector

# アプリ本体 + バッチスクリプト（Cloud Run Job が `python -m scripts.run_batch` 起動）
COPY driving-license-bot/app /app/app
COPY driving-license-bot/scripts /app/scripts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable --extra pgvector

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends tini ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PORT=8080

WORKDIR /app

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

COPY --from=builder --chown=runner:runner /app/.venv /app/.venv
COPY --from=builder --chown=runner:runner /app/app /app/app
COPY --from=builder --chown=runner:runner /app/scripts /app/scripts

USER runner

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
