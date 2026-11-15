################################################################################
# stock-analysis-agent Makefile
#
# 使い方:
#   make dev        - ローカル開発環境を起動（Docker Compose）
#   make run        - ローカルで直接起動
#   make test       - テストを実行
#   make install    - 依存パッケージをインストール
################################################################################

.PHONY: dev dev-down run install test lint help \
	local-up local-up-private local-down local-logs local-ps local-config \
	local-backup local-restore local-edinet-index local-offsite-install local-offsite-uninstall local-offsite-status \
	cutover-to-local cutover-to-gcp secrets-diff secrets-pull secrets-push webhook-get

# ---- ローカル開発 -------------------------------------------------------

dev:
	docker compose up --build

dev-down:
	docker compose down

dev-logs:
	docker compose logs -f

# ---- ローカル直接起動 ---------------------------------------------------

install:
	uv sync

run: install
	cd app && uv run uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# ---- テスト -------------------------------------------------------------

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=app --cov-report=term-missing

# ---- ローカル本番 (Mac mini 常駐, PROPOSAL-0013) -------------------------
# 設定: config/local.env (+ Funnel を使うなら config/tailscale.env)。雛形は *.env.example

LOCAL_COMPOSE := docker compose -f docker-compose.local.yml

local-up:
	mkdir -p $${STOCK_LOCAL_DATA_DIR:-data/local}
	$(LOCAL_COMPOSE) --profile public up -d --build

local-up-private:
	mkdir -p $${STOCK_LOCAL_DATA_DIR:-data/local}
	$(LOCAL_COMPOSE) up -d --build backend

local-down:
	$(LOCAL_COMPOSE) --profile public down

local-logs:
	$(LOCAL_COMPOSE) --profile public logs -f

local-ps:
	$(LOCAL_COMPOSE) --profile public ps

# compose の設定を展開して検証する (秘密情報は出さない)
local-config:
	$(LOCAL_COMPOSE) --profile public config --quiet && echo "docker-compose.local.yml: OK"

# 定期処理 (backup / EDINET index) を今すぐ 1 回動かす。SQLite を VM の外 (ホスト) から書かないよう、
# backend コンテナの中で実行する
local-backup:
	$(LOCAL_COMPOSE) exec backend python -c "import asyncio; from services.backup import run_backup; print(asyncio.run(run_backup()))"

local-edinet-index:
	$(LOCAL_COMPOSE) exec backend python -m batch.edinet_index_etl $(ARGS)

# backup から戻す (backend を止めてから)。BACKUP=path/to/file で指定、省略時は最新
local-restore:
	scripts/local/restore.sh $(BACKUP)

# backup を外部ディスク / iCloud にコピーする launchd (毎日 04:00)
local-offsite-install:
	scripts/local/offsite_backup_launchd.sh install

local-offsite-uninstall:
	scripts/local/offsite_backup_launchd.sh uninstall

local-offsite-status:
	scripts/local/offsite_backup_launchd.sh status

# ---- ローカル ⇄ GCP の切替 (PROPOSAL-0013) --------------------------------
# DRY_RUN=1 を付けると、実行するコマンドを表示するだけ

cutover-to-local:
	scripts/cutover/to_local.sh

cutover-to-gcp:
	scripts/cutover/to_gcp.sh

# config/local.env と Secret Manager の秘密情報 (値は表示しない)
secrets-diff:
	cd app && uv run python -m ops.secrets_sync diff

secrets-pull:
	cd app && uv run python -m ops.secrets_sync pull

secrets-push:
	cd app && uv run python -m ops.secrets_sync push

# 今の LINE Webhook URL
webhook-get:
	cd app && uv run python -m ops.line_webhook get

# ---- ヘルプ --------------------------------------------------------------

help:
	@echo "使い方:"
	@echo "  make dev     - Docker Compose でローカル環境を起動"
	@echo "  make run     - uvicorn でローカル直接起動 (ポート: 8001)"
	@echo "  make install - 依存パッケージをインストール"
	@echo "  make test    - pytest でテストを実行"
	@echo "  make local-up  - ローカル本番 (Mac mini) を Funnel 付きで起動 (local-up-private で Funnel なし)"
	@echo ""
	@echo "環境変数 (.env):"
	@echo "  CLAUDE_CODE_OAUTH_TOKEN - Claude Code OAuth トークン (必須)"
	@echo "  BRAVE_API_KEY      - Brave Search API キー (センチメント分析用)"
	@echo "  GOOGLE_CLOUD_PROJECT - GCP プロジェクト ID (VertexAI 用)"
