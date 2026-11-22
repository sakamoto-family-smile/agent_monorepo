.PHONY: help install test up up-private down ps logs sh-db

COMPOSE = HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose

help:
	@echo "  install     依存をインストール (uv sync)"
	@echo "  test        テスト"
	@echo "  up          backend + Funnel (LINE から届く) で起動"
	@echo "  up-private  backend のみで起動 (Funnel なし)"
	@echo "  down / ps / logs"
	@echo "  sh-db       コンテナの中で golf.db を読み取り専用で開く (ホストからは開かない)"

install:
	uv sync

test:
	uv run pytest

up:
	mkdir -p data
	$(COMPOSE) --profile public up -d --build

up-private:
	mkdir -p data
	$(COMPOSE) up -d --build backend

down:
	$(COMPOSE) --profile public down

ps:
	$(COMPOSE) --profile public ps

logs:
	$(COMPOSE) --profile public logs -f --tail=100

sh-db:
	$(COMPOSE) exec backend sqlite3 -readonly /data/golf.db
