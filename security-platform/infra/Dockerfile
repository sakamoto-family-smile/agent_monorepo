# 脆弱性対応 (intel / analytics) の共通イメージ。docker-compose.yml から使う。
# OS の CA ストア (ca-certificates 20250419~deb12u2) は emSign ECC Root CA - G3 を含まない
#
#   target app        intel / detection / analytics / notify / migrate
#   target extractor  L4 の記事の抽出 (app + Claude Code の CLI)
FROM python:3.15-slim-bookworm AS app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HOME=/home/app \
    DATA_DIR=/app/data

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
RUN useradd --create-home --home-dir /home/app --uid 1000 app

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY src ./src
COPY migrations ./migrations
COPY dbt ./dbt
# L4 のフィード一覧だけ焼き込む (config/ の他のファイルには秘密情報がある)
COPY config/feeds.yaml ./config/feeds.yaml

# DuckDB の sqlite 拡張はビルド時に入れておく (実行時にダウンロードしない)
# compose はホストの UID で動かすので、拡張 (HOME 配下) は誰でも読めるようにする。
# 書き込みは許さない (他のプロセスが拡張を差し替えられないように)
USER app
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL sqlite')" \
    && chmod -R a+rX,go-w /home/app

CMD ["python", "-m", "src.intel", "serve"]

# ── L4: Claude Code の CLI (版と SHA-512 を固定。更新は infra/fetch_claude_code.py の手順で) ─────────
FROM python:3.15-slim-bookworm AS claude-code
ARG TARGETARCH
ARG CLAUDE_CODE_VERSION=2.1.309
ARG CLAUDE_CODE_SHA512_arm64=b5366f2e6d1047977a856b03a4dbdcd7f4278d1cc87c011a19e6606aefad0657b9cf90d3f101917bb219b0fbb20459244b732d49b6efb14c7f8213bccd87367b
ARG CLAUDE_CODE_SHA512_amd64=dfa0fa90c0b47d67562f0040f1761a2534935c45afc3429cdd6418aad7ab89e283b699487d4b04e63bab640622961cce785fae34bf52367e03930850994ad132
COPY infra/fetch_claude_code.py /tmp/
RUN if [ "$TARGETARCH" = arm64 ]; then sha="$CLAUDE_CODE_SHA512_arm64"; else sha="$CLAUDE_CODE_SHA512_amd64"; fi \
    && python /tmp/fetch_claude_code.py "$CLAUDE_CODE_VERSION" "$TARGETARCH" "$sha" /claude

FROM app AS extractor
COPY --from=claude-code /claude /usr/local/bin/claude
CMD ["python", "-m", "src.llm", "serve"]
