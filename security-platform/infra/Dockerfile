# 脆弱性対応 (intel / analytics) の共通イメージ。docker-compose.yml から使う。
# OS の CA ストア (ca-certificates 20250419~deb12u2) は emSign ECC Root CA - G3 を含まない
FROM python:3.15-slim-bookworm

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
