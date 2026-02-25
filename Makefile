.PHONY: dev dev-db dev-api dev-frontend migrate test-backend test-frontend lint

# Start all services via Docker Compose
dev:
	docker compose up --build

# Start only Postgres
dev-db:
	docker compose up db

# Run backend API locally (requires .venv and running Postgres)
dev-api:
	cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Run frontend locally
dev-frontend:
	cd frontend && npm run dev

# Run Alembic migrations (set DATABASE_URL or use default)
migrate:
	cd backend && source .venv/bin/activate && alembic upgrade head

# Run backend tests
test-backend:
	cd backend && source .venv/bin/activate && pytest -v

# Run frontend lint & type check
test-frontend:
	cd frontend && npm run lint && npx tsc --noEmit

# Lint everything
lint:
	cd backend && source .venv/bin/activate && ruff check app/ && ruff format --check app/ && mypy app/
	cd frontend && npm run lint
