FROM python:3.12-slim

WORKDIR /app

# Install Node.js for npx (MCP server)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY app/ ./app/

# Create non-root user (required by Claude Agent SDK --dangerously-skip-permissions)
RUN useradd -m -u 1000 appuser

# Create data directories and set ownership
RUN mkdir -p data/charts data/cache data/reports data/dictionaries \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENV PYTHONPATH=/app/app

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/app"]
