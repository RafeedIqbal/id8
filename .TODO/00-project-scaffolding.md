# Task 00: Project Scaffolding

## Goal
Set up monorepo structure, package managers, environment configs, and dev tooling for both backend (FastAPI/Python) and frontend (Next.js).

## Steps

### 1. Initialize monorepo structure
```
id8/
├── backend/          # FastAPI Python service
├── frontend/         # Next.js operator console
├── contracts/        # (existing) OpenAPI + domain types
├── db/               # (existing) SQL schema
├── orchestration/    # (existing) state machine spec
├── qa/               # (existing) acceptance test plan
├── .env.example      # Template for all required env vars
└── docker-compose.yml # Local dev: Postgres + API + worker
```

### 2. Backend setup (`backend/`)
- [ ] Create `pyproject.toml` with Python 3.12+
- [ ] Dependencies: `fastapi`, `uvicorn`, `sqlalchemy`, `asyncpg`, `alembic`, `pydantic`, `httpx`, `python-dotenv`
- [ ] Dev dependencies: `pytest`, `pytest-asyncio`, `ruff`, `mypy`
- [ ] Create `backend/app/` package with `__init__.py`, `main.py` (FastAPI app factory)
- [ ] Create `backend/app/config.py` — load env vars with pydantic `BaseSettings`
- [ ] Create `backend/alembic/` — init Alembic for DB migrations
- [ ] Create `backend/alembic/versions/001_initial_schema.py` — translate `db/schema.sql` into Alembic migration

### 3. Frontend setup (`frontend/`)
- [ ] `npx create-next-app@latest frontend --typescript --tailwind --app --src-dir`
- [ ] Add dependencies: `@tanstack/react-query`, `zustand` (or similar state management)
- [ ] Copy `contracts/domain-types.ts` into `frontend/src/types/domain.ts` (or set up path alias)
- [ ] Create API client stub in `frontend/src/lib/api.ts` matching OpenAPI contract

### 4. Environment and configuration
- [ ] Create `.env.example` with all required variables:
  ```
  DATABASE_URL=postgresql+asyncpg://...
  SUPABASE_URL=
  SUPABASE_SERVICE_ROLE_KEY=
  GEMINI_API_KEY=
  GITHUB_APP_PRIVATE_KEY=
  GITHUB_APP_ID=
  VERCEL_TOKEN=
  STITCH_MCP_ENDPOINT=
  ```
- [ ] Create `backend/app/config.py` — validate all env vars at startup
- [ ] Add `.env` to `.gitignore`

### 5. Docker Compose for local dev
- [ ] Postgres 16 service on port 5432
- [ ] Backend API service (uvicorn, hot reload)
- [ ] Worker service (same image, different entrypoint)
- [ ] Frontend dev server

### 6. Dev tooling
- [ ] `Makefile` or `justfile` with common commands:
  - `make dev` — start all services
  - `make migrate` — run Alembic migrations
  - `make test-backend` — run pytest
  - `make test-frontend` — run next test / vitest
  - `make lint` — run ruff + mypy + eslint
- [ ] Pre-commit hooks: ruff format, mypy check

## Definition of Done
- [ ] `make dev` starts all services and API responds on `localhost:8000/docs`
- [ ] Frontend loads on `localhost:3000`
- [ ] Alembic migration applies cleanly to local Postgres
- [ ] All enum values in SQLAlchemy models match `db/schema.sql` and `contracts/domain-types.ts`
