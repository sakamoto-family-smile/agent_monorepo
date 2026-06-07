# syntax=docker/dockerfile:1.7
#
# stock-analysis-agent Cloud Run Service 用イメージ (PROPOSAL-0011 P1)。
#
# FastAPI + uvicorn で LINE webhook を受け、ticker 解決 → yfinance → 指標 →
# mplfinance チャート → Claude (claude-agent-sdk, OAuth token 経由) で統合レポートを
# 生成し、要約 Flex / チャート画像 / 全文 Markdown を LINE に返す。
#
# build context は **リポジトリルート** であること必須:
#   pyproject.toml が path dep (`../analytics-platform` / `../edinet-client`) を持つため。
#   DOCKER_BUILDKIT=1 docker build -f stock-analysis-agent/Dockerfile -t stock-analysis-agent:local .
#
# Claude Agent SDK は `claude` CLI (npm @anthropic-ai/claude-code) を subprocess 起動
# するため、runtime に Node.js + claude-code を同梱する。brave-search MCP も npx 起動。

# ---------------------------------------------------------------------------
# Stage 1: builder (uv で deps を解決し wheel-only な venv を作る)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

# `..` 相対 path dep を解決するため、analytics-platform / edinet-client を /app の
# sibling に配置 (pyproject の ../analytics-platform → /analytics-platform)。
# venv は /app/.venv に作り、runtime でも同じ /app/.venv に置いて shebang を揃える。
COPY analytics-platform /analytics-platform
COPY edinet-client /edinet-client
COPY stock-analysis-agent/pyproject.toml stock-analysis-agent/uv.lock /app/

WORKDIR /app

# 依存解決のみ (本体はまだコピーしない、キャッシュ利用)。
# `--no-editable` で path dep を site-packages に焼き込み、runtime に source を
# 持ち込まなくても import できるようにする。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-editable

COPY stock-analysis-agent/app ./app
COPY stock-analysis-agent/alembic ./alembic
COPY stock-analysis-agent/alembic.ini ./alembic.ini

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# tini: PID 1 として SIGTERM を child に伝搬 (Cloud Run graceful shutdown)
# ca-certificates / curl: HTTPS (yfinance / LINE / Brave) + healthcheck
# fonts-noto-cjk: mplfinance チャートの日本語ラベル描画
# nodejs/npm: claude-agent-sdk の `claude` CLI + brave-search MCP (npx)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      tini ca-certificates curl gnupg \
      fonts-noto-cjk fonts-noto-cjk-extra && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code @modelcontextprotocol/server-brave-search && \
    npm cache clean --force && \
    apt-get purge -y gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/app \
    PORT=8080

WORKDIR /app

# 非 root user (Cloud Run ベストプラクティス + claude CLI は root 起動を嫌う)
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

COPY --from=builder --chown=runner:runner /app/.venv /app/.venv
COPY --from=builder --chown=runner:runner /app/app /app/app
COPY --from=builder --chown=runner:runner /app/alembic /app/alembic
COPY --from=builder --chown=runner:runner /app/alembic.ini /app/alembic.ini

# ephemeral SQLite / チャート出力用の data ディレクトリ (MVP は揮発で割り切り)
RUN mkdir -p /app/data/charts /app/data/cache /app/data/reports \
      /app/data/dictionaries /app/data/analytics && \
    chown -R runner:runner /app/data

USER runner

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# prod (Postgres) は RUN_MIGRATIONS=true で起動時に alembic upgrade head を実行
# (DB_AUTO_CREATE=false と併用)。dev/sqlite は未設定で skip し init_db が create_all。
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"true\" ]; then alembic upgrade head; fi; exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --app-dir /app/app"]
