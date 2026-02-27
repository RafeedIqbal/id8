# Repository Guidelines

## Project Structure & Module Organization
- `backend/app/`: FastAPI API, orchestrator nodes, LLM/design/deploy/security integrations, and SQLAlchemy models.
- `backend/tests/`: Pytest suite (`test_*.py`) covering routes, orchestration, security gate, deployment, and integrations.
- `frontend/src/app/`: Next.js App Router pages (`/`, `/projects/new`, `/projects/[id]`, approval and artifact routes).
- `frontend/src/components/`, `frontend/src/lib/`, `frontend/src/types/`: UI, data hooks/API client, and shared frontend types.
- `contracts/`: Canonical API/domain contracts (`openapi.yaml`, `domain-types.ts`).
- `db/schema.sql` and `backend/alembic/`: Canonical schema plus migration history.
- `qa/`: Acceptance plans/reports; use when validating end-to-end behavior.

## Build, Test, and Development Commands
- `make dev`: Start full stack with Docker (`db`, `migrate`, `api`, `worker`, `frontend`).
- `make dev-db`: Start Postgres only.
- `make dev-api`: Run backend locally (`uvicorn` with reload).
- `make dev-frontend`: Run Next.js dev server on `:3000`.
- `make migrate`: Apply Alembic migrations.
- `make test-backend`: Run backend tests (`pytest -v`).
- `make test-frontend`: Frontend quality gate (`next lint` + `tsc --noEmit`).
- `make lint`: Repo linting (`ruff`, `mypy`, frontend lint).

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints required, `snake_case` modules/functions, `PascalCase` classes.
- Backend standards are enforced by Ruff + MyPy strict mode (`backend/pyproject.toml`), line length `120`.
- TypeScript/React: 2-space indentation, `PascalCase` components, and kebab-case component filenames (for example `project-status-badge.tsx`).
- Keep shared contracts aligned when changing schemas: update `contracts/`, backend schemas/models, and frontend types together.

## Testing Guidelines
- Framework: `pytest` + `pytest-asyncio` in `backend/tests/`.
- Test naming: `test_*.py`; prefer behavior-oriented names (for example `test_resume_does_not_duplicate_pr`).
- Backend tests require Postgres; `conftest.py` auto-creates `id8_test` via `TEST_DATABASE_URL`.
- Frontend currently has no unit test suite; PRs must at least pass lint + typecheck.

## Commit & Pull Request Guidelines
- Recent history includes placeholder commit subjects (`.`). Do not continue that pattern.
- Use clear, imperative commit messages with scope, e.g. `feat(orchestrator): add deploy approval guard`.
- Keep commits focused and logically grouped by feature/fix.
- PRs should include: concise summary, linked issue/task, test evidence (`make test-backend`, `make test-frontend`), and screenshots/GIFs for UI changes.
- For API/DB changes, include contract/migration updates in the same PR (`contracts/openapi.yaml`, `contracts/domain-types.ts`, Alembic, `db/schema.sql`).

## Security & Configuration Tips
- Start from `.env.example`; never commit real tokens or keys.
- Treat backend credentials as server-only; expose only `NEXT_PUBLIC_*` variables to frontend.
- When touching deployment or secret handling, run and update relevant security/deploy tests.
