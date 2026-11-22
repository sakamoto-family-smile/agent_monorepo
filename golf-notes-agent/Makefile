.PHONY: help install test up up-private down ps logs sh-db reprocess backup-now offsite offsite-install offsite-uninstall

COMPOSE = HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose

help:
	@echo "  install     依存をインストール (uv sync)"
	@echo "  test        テスト"
	@echo "  up          backend + Funnel (LINE から届く) で起動"
	@echo "  up-private  backend のみで起動 (Funnel なし)"
	@echo "  down / ps / logs"
	@echo "  sh-db       コンテナの中で golf.db を読み取り専用で開く (ホストからは開かない)"
	@echo "  reprocess   原本から作り直す KIND=lesson|raw [SINCE=2026-11-01] [DRY_RUN=1]"
	@echo "  backup-now  今日のバックアップを今すぐ作る (data/backup/)"
	@echo "  offsite     外部 SSD にコピー (GOLF_OFFSITE_DIR=...)。offsite-install で毎日 4:30 に"

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

reprocess:
	$(COMPOSE) exec backend python -m app.reprocess $(KIND) $(if $(SINCE),--since $(SINCE)) $(if $(DRY_RUN),--dry-run)

backup-now:
	$(COMPOSE) exec backend python -m app.backup

offsite:
	scripts/offsite_backup.sh copy

offsite-install:
	scripts/offsite_backup.sh install

offsite-uninstall:
	scripts/offsite_backup.sh uninstall
