.PHONY: dev down logs install test lint fmt test-api test-web lint-api lint-web migrate migration seed

## Run everything in Docker (api :8000, web :3000, postgres :5432, redis :6379)
dev:
	@test -f .env || cp .env.example .env
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

## Install local toolchains (for running tests/lint outside Docker)
install:
	cd apps/api && uv sync
	pnpm install

test: test-api test-web

test-api:
	cd apps/api && uv run pytest -q

## Database (run against the compose postgres, or set DATABASE_URL)
migrate:
	cd apps/api && uv run alembic upgrade head

migration:  ## make migration m="add foo"
	cd apps/api && uv run alembic revision --autogenerate -m "$(m)"

seed:
	cd apps/api && uv run python -m scripts.seed

test-web:
	pnpm -r --if-present test

lint: lint-api lint-web

lint-api:
	cd apps/api && uv run ruff check . && uv run ruff format --check .

lint-web:
	pnpm -r lint && pnpm -r typecheck

fmt:
	cd apps/api && uv run ruff format . && uv run ruff check --fix .
