.PHONY: help setup install env auth db-init \
        dashboard proxy collector analyzer digest \
        scan-mcp scan-skills redteam cron \
        test clean logs

# ── defaults ────────────────────────────────────────────────────────────────
DASHBOARD_PORT ?= 8000
PROXY_PORT     ?= 8080
MCP_TARGET_URL ?= http://localhost:3000

# ── help ────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "  Setup"
	@echo "    setup        Full first-time setup (install + env + auth + db-init)"
	@echo "    install      Install Python dependencies (uv sync)"
	@echo "    env          Copy .env.example → config/.env  (skip if exists)"
	@echo "    auth         Authenticate with Google Cloud (ADC for Vertex AI)"
	@echo "    db-init      Initialize / migrate the SQLite database"
	@echo ""
	@echo "  Services"
	@echo "    dashboard    Start web dashboard  (port $(DASHBOARD_PORT))"
	@echo "    proxy        Start MCP proxy      (port $(PROXY_PORT))"
	@echo "    collector    Fetch latest CVEs from NVD / GitHub Advisory / OSV"
	@echo "    analyzer     Match CVEs to inventory and run LLM analysis"
	@echo "    digest       Send daily notification digest"
	@echo ""
	@echo "  Scanning"
	@echo "    scan-mcp     Scan .mcp.json files for risks"
	@echo "    scan-skills  Scan skills directories"
	@echo "    redteam      Run red team tests (requires Node.js + ANTHROPIC_API_KEY)"
	@echo "    cron         Install cron jobs for automated collection"
	@echo ""
	@echo "  Dev"
	@echo "    test         Run test suite"
	@echo "    logs         Tail live log output"
	@echo "    clean        Remove __pycache__ and .pyc files"
	@echo ""

# ── setup ───────────────────────────────────────────────────────────────────
setup: install env auth db-init
	@echo ""
	@echo "✓ Setup complete. Run 'make dashboard' to start."

install:
	uv sync

env:
	@if [ -f config/.env ]; then \
		echo "config/.env already exists — skipping. Edit it manually if needed."; \
	else \
		cp config/.env.example config/.env; \
		echo "config/.env created. Open it and fill in your values."; \
	fi

auth:
	gcloud auth application-default login

db-init:
	uv run python -m src.db.migrations

# ── services ────────────────────────────────────────────────────────────────
dashboard:
	uv run uvicorn src.dashboard.app:app --host 0.0.0.0 --port $(DASHBOARD_PORT) --reload

proxy:
	MCP_TARGET_URL=$(MCP_TARGET_URL) \
	  uv run uvicorn src.proxy.server:app --host 0.0.0.0 --port $(PROXY_PORT) --reload

collector:
	uv run python -m src.collector.main

analyzer:
	uv run python -m src.analyzer.main

digest:
	uv run python -m src.notifier.digest

# ── scanning ────────────────────────────────────────────────────────────────
scan-mcp:
	./scripts/scan-mcp.sh

scan-skills:
	./scripts/scan-skills.sh

redteam:
	./scripts/redteam.sh

cron:
	./scripts/setup-cron.sh

# ── dev ─────────────────────────────────────────────────────────────────────
test:
	uv run pytest

logs:
	tail -f logs/*.jsonl 2>/dev/null || echo "No log files found in logs/"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
	find . -name "*.pyc" -delete 2>/dev/null; \
	echo "Cleaned."
