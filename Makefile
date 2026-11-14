.PHONY: help install db-up db-down tunnel tunnel-stop tunnel-status migrate migrate-status api web test lint

help:            ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:         ## Install Python (uv) and JS (pnpm) dependencies
	uv sync --all-packages
	pnpm install

db-up:           ## Start TimescaleDB
	docker compose -f infra/compose/timescaledb/docker-compose.yml up -d

db-down:         ## Stop TimescaleDB (keeps data)
	docker compose -f infra/compose/timescaledb/docker-compose.yml down

tunnel:          ## Tunnel localhost:5432 to the dev server's database (SSH)
	scripts/tunnel.sh start

tunnel-stop:     ## Close the dev database tunnel
	scripts/tunnel.sh stop

tunnel-status:   ## Show whether the dev database tunnel is up
	scripts/tunnel.sh status

migrate:         ## Apply pending database migrations
	scripts/migrate.sh up

migrate-status:  ## Show applied/pending migrations
	scripts/migrate.sh status

api:             ## Run the API with reload on :8000
	cd services/api && uv run uvicorn app.main:app --reload --port 8000

web:             ## Run the website on :3000
	pnpm --filter @vynzo/web dev

test:            ## Run all tests
	uv run pytest services
	pnpm -r typecheck

lint:            ## Lint Python and JS
	uv run ruff check services
	uv run ruff format --check services
	pnpm -r lint
