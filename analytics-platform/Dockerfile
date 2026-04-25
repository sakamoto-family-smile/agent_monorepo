# syntax=docker/dockerfile:1.7
#
# analytics-platform dbt Cloud Run Job 用イメージ。
#
# build:
#   docker build -t analytics-platform-dbt:local .
# run (local):
#   docker run --rm \
#     -v ${HOME}/.config/gcloud:/root/.config/gcloud:ro \
#     -e ANALYTICS_BQ_PROJECT=youyaku-ai \
#     -e ANALYTICS_BQ_LOCATION=US \
#     -e ANALYTICS_GCS_BUCKET=youyaku-ai-analytics-raw \
#     analytics-platform-dbt:local run
#
# Cloud Run Jobs では Workload Identity → ADC で BigQuery 認証が通る。
# 認証 JSON を埋め込まず、SA を環境側で割り当てる。

# ---------------------------------------------------------------------------
# Stage 1: builder (uv で deps を解決し、wheel-only な venv を作る)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# uv (公式静的バイナリ) を導入。バージョン pin は Renovate などで更新する。
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# 依存解決のためメタ情報を先にコピー (キャッシュ最適化)
COPY pyproject.toml uv.lock ./

# .venv を /app/.venv に作る。`--no-install-project` で本体は除外して
# 依存ツリーだけ build cache に乗せる。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra gcp --no-install-project --no-dev

# プロジェクト本体 + dbt 設定をコピーして再 sync (本体だけ更新時のキャッシュヒット用)
COPY analytics_platform ./analytics_platform
COPY dbt ./dbt
COPY scripts ./scripts
COPY README.md ./README.md

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra gcp --no-dev

# ---------------------------------------------------------------------------
# Stage 2: runtime (最小 python image + builder の venv のみ)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# tini: PID 1 として SIGTERM を子に伝搬する (Cloud Run Jobs の graceful shutdown)
# bq CLI は不要 (gcloud SDK を入れるとイメージが膨らむため)。
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    DBT_PROFILES_DIR=/app/dbt \
    DBT_PROJECT_DIR=/app/dbt

WORKDIR /app

# 非 root ユーザで実行 (Cloud Run のベストプラクティス)
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

# venv + コードを builder からコピー
COPY --from=builder --chown=runner:runner /app/.venv /app/.venv
COPY --from=builder --chown=runner:runner /app/analytics_platform /app/analytics_platform
COPY --from=builder --chown=runner:runner /app/dbt /app/dbt
COPY --from=builder --chown=runner:runner /app/scripts /app/scripts
COPY --chown=runner:runner pyproject.toml /app/pyproject.toml

# entrypoint
COPY --chown=runner:runner scripts/docker_entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER runner

# tini でシグナルを通す
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]

# 既定は dbt run + dbt test。Cloud Run Job 起動時に args で上書き可能。
CMD ["run-and-test"]
