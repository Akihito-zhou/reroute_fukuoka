# ---------- 設定 ----------
SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help

WEB_DIR := apps/web
API_DIR := apps/api
COMPOSE_DEV := infra/compose/docker-compose.dev.yml
COMPOSE_PROD := infra/compose/docker-compose.prod.yml

PNPM_VER := 9.0.0
POETRY_VER := 2.2.1

# ---------- ヘルプ ----------
.PHONY: help
help:
	@echo "Re-Route Fukuoka Makefile"
	@echo "  install        安装前后端依赖（本机）"
	@echo "  install-web    仅安装 Web 依赖（pnpm）"
	@echo "  install-api    仅安装 API 依赖（poetry）"
	@echo "  dev-web        启动 Web (Vite dev server)"
	@echo "  dev-api        启动 API (Uvicorn --reload)"
	@echo "  lint-web       Web Lint"
	@echo "  lint-api       API Lint"
	@echo "  up-dev         Docker: 开发环境起全部服务"
	@echo "  down-dev       Docker: 关闭开发环境并清孤儿"
	@echo "  up-prod        Docker: 预发/生产环境起服务"
	@echo "  down-prod      Docker: 关闭预发/生产环境"
	@echo "  logs           Docker: 跟随日志"
	@echo "  sh-web         Docker: 进入 web 容器"
	@echo "  sh-api         Docker: 进入 api 容器"
	@echo "  redis-ping     Redis 健康检查"
	@echo "  redis-flush    Redis 清空（仅本地）"

# ---------- ローカルインストール ----------
.PHONY: install install-web install-api
install: install-web install-api ## フロントエンドとバックエンドの依存をインストール
	@echo "✓ all deps installed"

install-web: ## Web の依存のみ
	@corepack enable
	@corepack prepare pnpm@$(PNPM_VER) --activate
	cd $(WEB_DIR) && pnpm install
	@echo "✓ web deps ok"

install-api: ## API の依存のみ
	@python3 -m pip install --user pipx || true
	@python3 -m pipx ensurepath || true
	@pipx install "poetry==$(POETRY_VER)" || pipx upgrade poetry || true
	cd $(API_DIR) && poetry lock && poetry install
	@echo "✓ api deps ok"

# ---------- ローカル開発サーバー ----------
.PHONY: dev-web dev-api
dev-web:
	cd $(WEB_DIR) && pnpm dev --host 0.0.0.0 --port 5173

dev-api:
	cd $(API_DIR) && poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# ---------- Lint ----------
.PHONY: lint-web lint-api
lint-web:
	cd $(WEB_DIR) && pnpm lint

lint-api:
	@echo "No API linter configured yet."

# ---------- Docker: 開発 ----------
.PHONY: up-dev down-dev logs sh-web sh-api
up-dev:
	docker compose -f $(COMPOSE_DEV) up --build

down-dev:
	docker compose -f $(COMPOSE_DEV) down --remove-orphans

logs:
	docker compose -f $(COMPOSE_DEV) logs -f

sh-web:
	docker compose -f $(COMPOSE_DEV) exec web sh

sh-api:
	docker compose -f $(COMPOSE_DEV) exec api bash -lc "bash || sh"

# ---------- Docker: 本番 / 準本番 ----------
.PHONY: up-prod down-prod
up-prod:
	docker compose -f $(COMPOSE_PROD) up -d --build

down-prod:
	docker compose -f $(COMPOSE_PROD) down

# ---------- Redis ヘルパー ----------
.PHONY: redis-ping redis-flush
redis-ping:
	@docker compose -f $(COMPOSE_DEV) exec redis redis-cli ping

redis-flush:
	@docker compose -f $(COMPOSE_DEV) exec redis redis-cli FLUSHALL
	@echo "✓ redis flushed (dev)"
