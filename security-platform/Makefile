.PHONY: help setup install env auth db-init \
        dashboard proxy collector analyzer digest \
        scan-mcp scan-skills redteam cron \
        test clean logs \
        vuln-migrate intel-bootstrap intel-osv intel-osv-full intel-kev intel-epss \
        intel-health detection-scan detection-findings detection-images detection-exceptions notify-test notify-digest notify-health analytics duck-ui up down ps logs-vuln

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
	@echo "  Vulnerability response (A1 intel / analytics) — data/ 配下にローカル集約"
	@echo "    up             docker compose up -d --build (intel + analytics を常駐)"
	@echo "    down           docker compose down"
	@echo "    ps / logs-vuln docker compose の状態 / ログ"
	@echo "    (以下の書き込みを伴うコマンドは docker compose run でコンテナ内から実行する)"
	@echo "    vuln-migrate   SQLite 3 ファイル (intel/detection/remediation) を最新スキーマに"
	@echo "    intel-bootstrap 初回全量取り込み (OSV 全エコシステム + KEV + EPSS、再開可)"
	@echo "    intel-osv      OSV 差分取得       intel-osv-full  OSV 全量の再取得"
	@echo "    intel-kev      CISA KEV           intel-epss      FIRST EPSS"
	@echo "    intel-health   情報源ごとの最終成功時刻 (古ければ exit 1)"
	@echo "    detection-scan lockfile・本番イメージを照合して findings を更新  detection-findings  未対応の Finding 一覧"
	@echo "    detection-images 本番イメージの SBOM を作る (ホストで gcloud・docker を使う。デプロイのたびに実行)"
	@echo "    detection-exceptions ARGS='list|add ...|revoke <id>'  例外 (誤検知・リスク受容) の管理"
	@echo "    notify-test    LINE にテスト送信   notify-digest  日次まとめを今すぐ送る   notify-health  監視項目の状態"
	@echo "    analytics      dbt build → data/security.duckdb を差し替え"
	@echo "    duck-ui        DuckDB UI を読み取り専用で開く (http://localhost:4213)"
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

# ── vulnerability response (A1 intel / analytics) ───────────────────────────
# SQLite への書き込みはコンテナ内からだけ行う (ホストと VM をまたいだ WAL 共有を避ける)。
# 常駐中の intel と同時に走らせても、data/.locks のロックで片方がすぐ失敗する
COMPOSE   = HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose
INTEL_RUN = $(COMPOSE) run --rm --no-deps intel python -m src.intel

up:
	mkdir -p data
	$(COMPOSE) up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs-vuln:
	docker compose logs -f --tail=100 intel analytics

vuln-migrate:
	$(COMPOSE) run --rm --no-deps migrate

intel-bootstrap:
	$(INTEL_RUN) bootstrap

intel-osv:
	$(INTEL_RUN) osv

intel-osv-full:
	$(INTEL_RUN) osv-full

intel-kev:
	$(INTEL_RUN) kev

intel-epss:
	$(INTEL_RUN) epss

intel-health:
	$(INTEL_RUN) health

detection-scan:
	$(COMPOSE) run --rm --no-deps detection python -m src.detection scan

detection-findings:
	$(COMPOSE) run --rm --no-deps detection python -m src.detection findings

detection-exceptions:
	$(COMPOSE) run --rm --no-deps detection python -m src.detection exceptions $(ARGS)

notify-test:
	$(COMPOSE) run --rm --no-deps notify python -m src.notify test

notify-digest:
	$(COMPOSE) run --rm --no-deps notify python -m src.notify digest

notify-health:
	$(COMPOSE) run --rm --no-deps notify python -m src.notify health

# ホストで実行する (gcloud の認証と docker を使う。SQLite には触らず data/sbom/images/ に書くだけ)
detection-images:
	mkdir -p data/sbom/images
	uv run python -m src.detection images

analytics:
	$(COMPOSE) run --rm --no-deps analytics python -m src.analytics build

duck-ui:
	uv run python -m src.analytics ui

# ── dev ─────────────────────────────────────────────────────────────────────
test:
	uv run pytest

logs:
	tail -f logs/*.jsonl 2>/dev/null || echo "No log files found in logs/"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
	find . -name "*.pyc" -delete 2>/dev/null; \
	echo "Cleaned."
