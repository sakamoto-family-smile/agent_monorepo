# couple-roster-bot 開発用ショートカット。

.PHONY: install test lint run clean

install:
	uv sync --dev

test:
	uv run pytest tests/ -q

lint:
	uv run ruff check app tests

# ローカル起動（storage=memory / ocr=mock の default で /health と /liff が動く）。
run:
	uv run uvicorn app.main:app --reload --port 8080

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ app/__pycache__ tests/__pycache__
