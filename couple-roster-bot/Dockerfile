# syntax=docker/dockerfile:1.7
#
# couple-roster-bot Cloud Run Service 用イメージ。
#
# FastAPI + uvicorn で LINE webhook / LIFF フォームを提供し、Google スプレッド
# シートに名簿を読み書きする。
#
# build (このディレクトリを context に):
#   DOCKER_BUILDKIT=1 docker build -f couple-roster-bot/Dockerfile \
#     -t couple-roster-bot:local couple-roster-bot
#
# run (local smoke, in-memory / mock OCR):
#   docker run --rm -p 8080:8080 -e PORT=8080 couple-roster-bot:local

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock* /app/
COPY README.md /app/README.md

# 本番は sheets + ocr-drive を有効化（Cloud Vision に切り替える場合は ocr-vision）。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --no-editable \
        --extra sheets --extra ocr-drive

COPY app /app/app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable --extra sheets --extra ocr-drive

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PORT=8080

WORKDIR /app

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

COPY --from=builder --chown=runner:runner /app/.venv /app/.venv
COPY --from=builder --chown=runner:runner /app/app /app/app

USER runner

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
