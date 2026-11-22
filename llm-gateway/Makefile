# LLM gateway (PROPOSAL-0014)。秘密は config/*.env (git 管理外) にだけ置く。
COMPOSE = docker compose --env-file config/gateway.env --env-file config/langfuse.env

.PHONY: up down ps logs health key

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) stop

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail 100 litellm

health:
	@curl -fsS http://127.0.0.1:4000/health/liveliness && echo
	@curl -fsS http://127.0.0.1:3000/api/public/health && echo

# エージェント用のバーチャルキーを発行する。例:
#   make key ALIAS=stock-analysis-agent ENV_FILE=../stock-analysis-agent/config/local.env
key:
	@python3 scripts/issue_key.py $(ALIAS) $(if $(ENV_FILE),--env-file $(ENV_FILE))
