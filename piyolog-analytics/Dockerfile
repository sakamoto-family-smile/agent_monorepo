# syntax=docker/dockerfile:1.7
#
# piyolog-analytics Cloud Run service 用イメージ。
#
# build (リポジトリルートから):
#   DOCKER_BUILDKIT=1 docker build -f piyolog-analytics/Dockerfile -t piyolog-analytics:local .
#
# `pyproject.toml` が path dep (`../analytics-platform`) を持つため、
# build context は **リポジトリルート** であることが必須。
# `make docker-build` がそれを面倒見る。
#
# run (local SQLite):
#   docker run --rm -p 8200:8200 \
#     -e LINE_CHANNEL_SECRET=... -e LINE_CHANNEL_ACCESS_TOKEN=... \
#     -e FAMILY_USER_IDS=Uxxx,Uyyy \
#     piyolog-analytics:local
#
# Cloud Run service にデプロイすると、Cloud SQL connector が `/cloudsql/<conn>`
# Unix socket を生やすので、DATABASE_URL に
# `postgresql+asyncpg://user:pass@/dbname?host=/cloudsql/<conn>` を入れる。

# ---------------------------------------------------------------------------
# Stage 1: builder (uv で deps を解決し、wheel-only な venv を作る)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# uv (公式静的バイナリ)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# `..` 相対パス解決のため、analytics-platform は /app の sibling (`/analytics-platform`) に配置。
# venv は /app/.venv に作るので、runtime でも同じ /app/.venv で動作する (shebang が一致)。
COPY analytics-platform /analytics-platform
COPY piyolog-analytics/pyproject.toml piyolog-analytics/uv.lock /app/

WORKDIR /app

# 依存解決のみ (本体はまだコピーしない、キャッシュ利用)。
# `--no-editable` で path dep (analytics-platform) を site-packages にコピー化し、
# runtime に source ディレクトリを持ち込まなくても import できるようにする。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-editable

# 本体コピー + プロジェクト本体を install (これも非 editable で site-packages に焼き込み)
COPY piyolog-analytics/app ./app
COPY piyolog-analytics/alembic ./alembic
COPY piyolog-analytics/alembic.ini ./alembic.ini

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Stage 2: runtime (最小 image + builder の venv のみ)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# tini: PID 1 として SIGTERM を child に伝搬する (Cloud Run の graceful shutdown)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/app \
    PORT=8200

WORKDIR /app

# 非 root user (Cloud Run のベストプラクティス)
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

# venv + コードを builder からコピー (path は /app/ のまま揃えてあるので shebang 整合)
COPY --from=builder --chown=runner:runner /app/.venv /app/.venv
COPY --from=builder --chown=runner:runner /app/app /app/app
COPY --from=builder --chown=runner:runner /app/alembic /app/alembic
COPY --from=builder --chown=runner:runner /app/alembic.ini /app/alembic.ini

# Cloud Run は SQLite ファイルをエフェメラルにしか保持できないので、
# 本番では DATABASE_URL=postgresql+asyncpg://... + DB_AUTO_CREATE=false が前提。
# dev/SQLite 用途で書ける場所として data/ を用意する。
RUN mkdir -p /app/data /app/data/analytics && \
    chown -R runner:runner /app/data

USER runner

EXPOSE 8200

# Cloud Run の health check は `GET /healthz` を叩く。
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# `PORT` は Cloud Run が注入する。tini でシグナルを通す。
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8200} --app-dir /app/app"]
