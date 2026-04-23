################################################################################
# hotcook-agent Makefile
#
# 使い方:
#   make dev        - ローカル開発環境を起動 (Docker Compose)
#   make run        - ローカルで直接起動
#   make test       - テストを実行
#   make install    - 依存パッケージをインストール
#   make seed       - menu-catalog.json を再生成
################################################################################

.PHONY: dev dev-down dev-logs run install test test-cov seed help

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
	cd app && uv run uvicorn main:app --host 0.0.0.0 --port 8002 --reload

# ---- データ生成 ----------------------------------------------------------

seed:
	uv run python scripts/seed_menu_catalog.py

# ---- テスト -------------------------------------------------------------

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=app --cov-report=term-missing

# ---- ヘルプ --------------------------------------------------------------

help:
	@echo "使い方:"
	@echo "  make dev      - Docker Compose でローカル環境を起動"
	@echo "  make run      - uvicorn でローカル直接起動 (ポート: 8002)"
	@echo "  make seed     - data/skills/hotcook-recipes/menu-catalog.json を再生成"
	@echo "  make install  - 依存パッケージをインストール"
	@echo "  make test     - pytest でテストを実行"
