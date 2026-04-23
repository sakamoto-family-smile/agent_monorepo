FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY app/ ./app/
COPY data/ ./data/

# Create non-root user (required by Claude Agent SDK --dangerously-skip-permissions)
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data/local /app/data/analytics \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENV PYTHONPATH=/app/app

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/app"]
