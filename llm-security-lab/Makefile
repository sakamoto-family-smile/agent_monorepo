# llm-security-lab 開発・運用ショートカット (proposal 0008 §4.5).
#
# Phase 0a (本 PR) は scaffold のみ。 Phase 0b/0c で setup-NN / attack-NN /
# defend-NN / eval-all 等を追加する。

.PHONY: install test lint clean \
        setup-base setup-models jupyter down \
        clean-models help

help:
	@echo "llm-security-lab targets (Phase 0a):"
	@echo "  install        - uv sync (dev deps)"
	@echo "  test           - run pytest"
	@echo "  lint           - ruff check"
	@echo "  setup-base     - ollama + jupyter container を up"
	@echo "  setup-models   - mistral / llama3 / llama-guard を ollama に pull"
	@echo "  jupyter        - jupyter container を foreground で起動"
	@echo "  down           - 全 container を停止 + ボリューム保持"
	@echo "  clean          - キャッシュ削除"
	@echo "  clean-models   - ollama に pull 済モデルを全削除 (volume 維持)"
	@echo ""
	@echo "Phase 0b/0c で追加予定: setup-NN / attack-NN / defend-NN / eval-all"

install:
	uv sync --dev

test:
	uv run pytest tests/ -q

lint:
	uv run ruff check shared tests

setup-base:
	docker compose up -d ollama jupyter

setup-models: setup-base
	docker compose exec ollama ollama pull mistral
	docker compose exec ollama ollama pull llama3
	docker compose exec ollama ollama pull llama-guard3:8b

jupyter:
	docker compose up jupyter

down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ shared/__pycache__ tests/__pycache__

clean-models:
	docker compose exec ollama ollama rm mistral llama3 llama-guard3:8b || true
