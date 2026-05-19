# fujisawa-info-bot 開発用ショートカット。
# Phase 0 では最低限のコマンドのみ。 Phase 1+ で deploy / cloudbuild ターゲットを追加予定。

.PHONY: install test lint run clean

install:
	uv sync --dev

test:
	uv run pytest tests/ -q

lint:
	uv run ruff check app tests

# ローカル起動 (Phase 0: /health のみ)。 Phase 1 で LINE webhook 起動例を追加する。
run:
	uv run uvicorn app.main:app --reload --port 8080

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ app/__pycache__ tests/__pycache__
