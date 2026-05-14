# syntax=docker/dockerfile:1.7
#
# fujisawa-platform ETL Cloud Run Job 用イメージ。
#
# 1 つの image で 7 種類の Job (weekly_crawl / half_yearly_facility /
# biyearly_admission / monthly_vacancy / yearly_navi / monthly_stats_compute /
# wayback_backfill) を扱う。Cloud Run Job ごとに `--args` で job 名を渡す。
#
# build (リポジトリルートから):
#   DOCKER_BUILDKIT=1 docker build -f fujisawa-platform/Dockerfile -t fujisawa-etl:local .
#
# run (local smoke):
#   docker run --rm \
#     -e FUJISAWA_ETL_DB_HOST=host.docker.internal \
#     -e FUJISAWA_ETL_DB_USER=etl_user \
#     -e FUJISAWA_ETL_DB_PASSWORD=... \
#     -e FUJISAWA_ETL_USER_AGENT="fujisawa-etl/0.1 (https://example.com)" \
#     -e FUJISAWA_ETL_SITEMAP_URL=https://www.city.fujisawa.kanagawa.jp/sitemap.xml \
#     fujisawa-etl:local monthly_stats_compute --current-year 2026 --dry-run

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

# fujisawa-platform 単体 build (path dep なし、analytics-platform 不要)
COPY fujisawa-platform/pyproject.toml /app/
COPY fujisawa-platform/uv.lock* /app/

WORKDIR /app

# 依存解決のみ (本体は後段でコピー)。
# 4 つの extras を全部入れる: ETL Cloud Run Job は重い deps を全部必要とする。
#   - pgvector: asyncpg + pgvector (本番 DB)
#   - vertex:   google-cloud-aiplatform (本番 embedding)
#   - pdf:      docling (PDF 構造化、ETL 必須)
#   - gcs:      google-cloud-storage (PdfArchive 本番)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --no-editable \
        --extra pgvector --extra vertex --extra pdf --extra gcs

# アプリ本体をコピー (skills / db は pyproject.toml の force-include で含まれる)
COPY fujisawa-platform/fujisawa_platform /app/fujisawa_platform

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable \
        --extra pgvector --extra vertex --extra pdf --extra gcs

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# tini: signal handling (Cloud Run Job の SIGTERM を Python に届ける)
# ca-certificates: HTTPS 検証 (httpx + Wayback + Vertex)
# curl: 健全性確認 (Cloud Run Job 自身は不要だが docker run smoke で便利)
# libxcb1 / libgl1 / libgomp1 / libglib2.0-0:
#   Docling PDF pipeline (Pillow + torch + pdfium) が動的 link する system libs。
#   未導入だと `ImportError: libxcb.so.1: cannot open shared object file` 等で
#   wayback_backfill / biyearly_admission など PDF parse 系 Job が落ちる
#   (2026-05-13 実 Cloud Run Job 実行で発覚)。
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tini ca-certificates curl \
        libxcb1 libgl1 libgomp1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# 非 root ユーザ
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

COPY --from=builder --chown=runner:runner /app/.venv /app/.venv
COPY --from=builder --chown=runner:runner /app/fujisawa_platform /app/fujisawa_platform

USER runner

# tini で PID 1 を取り、Python に SIGTERM が届くようにする
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "fujisawa_platform.etl.cli"]

# Cloud Run Job は `--args=<job_name>,<flag1>,...` で起動するため、
# default CMD は help を出すだけにしておく (誤って素 docker run で起動した時の安全)。
CMD ["--help"]
