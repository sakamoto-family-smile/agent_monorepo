################################################################################
# stock-analysis-agent Makefile
#
# 使い方:
#   make dev        - ローカル開発環境を起動（Docker Compose）
#   make run        - ローカルで直接起動
#   make test       - テストを実行
#   make install    - 依存パッケージをインストール
################################################################################

.PHONY: dev dev-down run install test lint help

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

# ---- ヘルプ --------------------------------------------------------------

help:
	@echo "使い方:"
	@echo "  make dev     - Docker Compose でローカル環境を起動"
	@echo "  make run     - uvicorn でローカル直接起動 (ポート: 8001)"
	@echo "  make install - 依存パッケージをインストール"
	@echo "  make test    - pytest でテストを実行"
	@echo ""
	@echo "環境変数 (.env):"
	@echo "  ANTHROPIC_API_KEY  - Anthropic API キー (必須)"
	@echo "  BRAVE_API_KEY      - Brave Search API キー (センチメント分析用)"
	@echo "  GOOGLE_CLOUD_PROJECT - GCP プロジェクト ID (VertexAI 用)"
