SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv
IMAGE_NAME ?= driving-license-bot
IMAGE_TAG ?= local

.PHONY: help install lint format test check run docker-build docker-run

help:  ## このヘルプを表示
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## 依存をインストール（uv sync）
	$(UV) sync --extra gcs

lint:  ## ruff でチェック
	$(UV) run ruff check app tests

format:  ## ruff で整形
	$(UV) run ruff format app tests
	$(UV) run ruff check --fix app tests

test:  ## pytest 実行
	$(UV) run pytest -q

check: lint test  ## lint + test

run:  ## ローカル起動（要 .env または環境変数）
	$(UV) run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

docker-build:  ## Docker image を build（リポジトリルートから実行する）
	cd .. && DOCKER_BUILDKIT=1 docker build \
		-f driving-license-bot/Dockerfile \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		.

docker-run:  ## Docker image をローカル起動
	docker run --rm -p 8080:8080 \
		-e LINE_CHANNEL_SECRET="$$LINE_CHANNEL_SECRET" \
		-e LINE_CHANNEL_ACCESS_TOKEN="$$LINE_CHANNEL_ACCESS_TOKEN" \
		$(IMAGE_NAME):$(IMAGE_TAG)
