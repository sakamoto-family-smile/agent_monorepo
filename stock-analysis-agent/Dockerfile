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

# Create data directories
RUN mkdir -p data/charts data/cache data/reports data/dictionaries

EXPOSE 8000

ENV PYTHONPATH=/app/app

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/app"]
