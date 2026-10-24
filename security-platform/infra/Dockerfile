# 脆弱性対応 (intel / analytics) の共通イメージ。docker-compose.yml から使う。
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HOME=/home/app \
    DATA_DIR=/app/data

RUN pip install --no-cache-dir uv \
    && useradd --create-home --home-dir /home/app --uid 1000 app

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY src ./src
COPY migrations ./migrations
COPY dbt ./dbt

# DuckDB の sqlite 拡張はビルド時に入れておく (実行時にダウンロードしない)
# compose は ホストの UID で動かすので、拡張のキャッシュ (HOME 配下) は誰でも読めるようにする
USER app
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL sqlite')" \
    && chmod -R a+rwX /home/app

CMD ["python", "-m", "src.intel", "serve"]
