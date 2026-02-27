## Project Overview

ID8 is an AI-powered application generation platform that turns natural language prompts into production-deployed web apps with strict Human-In-The-Loop (HITL) approval gates. Internal operator tool (MVP) for the Wealthsimple AI builder program.

## Development Commands

### Full stack (Docker)
```bash
make dev              # Start all services (db, migrate, api, worker, frontend)
make dev-db           # Start only Postgres
```

### Backend (local, requires .venv and running Postgres)
```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000         # Run API
python -m app.worker                                # Run background worker
alembic upgrade head                                # Run migrations
```

### Frontend
```bash
cd frontend && npm run dev                          # Dev server on :3000
```


### Linting
```bash
make lint                                           # Everything
# Backend individually:
cd backend && ruff check app/ && ruff format --check app/ && mypy app/
# Frontend individually:
cd frontend && npm run lint
```

Pre-commit hooks run: `ruff format`, `ruff check`, `mypy` (backend only).

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, Pydantic v2 — Python 3.14
- **Frontend:** Next.js 15 (app router), React 19, TanStack Query 5, Tailwind CSS 4 — TypeScript 5
- **Database:** PostgreSQL 16 (Docker or Supabase)
- **LLM:** Google Gemini via `google-genai` SDK, model routing by node type
- **Design Generation:** Stitch MCP (primary), `internal_spec` fallback
- **Deployment Targets:** Supabase (DB/backend) + Vercel (frontend)

## Architecture

### Orchestration State Machine (14 nodes)

`IngestPrompt → GeneratePRD → WaitPRDApproval → GenerateDesign → WaitDesignApproval → GenerateTechPlan → WaitTechPlanApproval → WriteCode → SecurityGate → PreparePR → WaitDeployApproval → DeployProduction → EndSuccess/EndFailed`

Four HITL approval gates (PRD, Design, Tech Plan, Deploy). Rejection loops back to the generation node with structured feedback.

### Backend Layout (`backend/app/`)

| Package | Purpose |
|---------|---------|
| `models/` | SQLAlchemy ORM models (9 tables). `enums.py` has all DB enums. |
| `schemas/` | Pydantic request/response schemas (13 files) |
| `routes/` | FastAPI endpoint routers (projects, runs, approvals, artifacts, design, deploy) |
| `orchestrator/` | State machine engine (`engine.py`) + 14 node handlers in `handlers/` |
| `llm/` | Gemini client (`client.py`), model router, prompt templates in `prompts/` |
| `design/` | Design providers: Stitch MCP (`stitch_mcp.py`), internal spec fallback |
| `security/` | SAST, dependency audit, secret scanning |
| `deploy/` | Supabase + Vercel deployment clients, credential filtering |
| `github/` | GitHub REST API client for repo/PR management |
| `observability/` | Audit logging, metrics, LLM cost tracking |

Entry points: `main.py` (FastAPI app), `worker.py` (background processor), `config.py` (pydantic-settings).

### Frontend Layout (`frontend/src/`)

| Directory | Purpose |
|-----------|---------|
| `app/` | Next.js app router pages: project list, project detail, approval gates, artifact viewers |
| `components/` | UI components (sidebar, node-timeline, approval panel, artifact viewers) |
| `lib/` | API client (`api.ts`), hooks (`hooks.ts`), constants, utils, type guards |
| `types/` | TypeScript domain types mirroring backend schemas |

Key pages: `/` (project list), `/projects/new`, `/projects/[id]`, `/projects/[id]/approve/[stage]`, `/projects/[id]/artifacts/[type]`

### Model Routing

| Profile | Model | Usage |
|---------|-------|-------|
| `primary` | `gemini-3.1-pro-preview` | Planning/reasoning nodes |
| `customtools` | `gemini-3.1-pro-preview-customtools` | Tool-heavy coding/orchestration |
| `fallback` | `gemini-2.5-pro` | Retry conditions only |

### Database

PostgreSQL 16 with 9 tables: `users`, `projects`, `project_runs`, `project_artifacts`, `approval_events`, `provider_credentials`, `deployment_records`, `retry_jobs`, `audit_events`. Migrations via Alembic (`backend/alembic/`). Tests use a separate `id8_test` database (auto-created).

### Docker Compose Services

`db` (Postgres:5432) → `migrate` (Alembic) → `api` (:8000, hot-reload) + `worker` (background) → `frontend` (:3000)

## Key Invariants

- Every run step is **idempotent** by `run_id` + `node_name` + optional idempotency key
- Failures are **resumable** from the last successful checkpoint
- Artifacts are **versioned** (version column on `project_artifacts`)
- Security gate is **mandatory** — high/critical unresolved findings block deployment
- Deploy requires **explicit approval event** (`ApprovalStage=deploy`)
- Server-only credentials **never** leak to frontend artifacts

## Key Enums (must stay consistent across all contracts)

- `DesignProvider`: `stitch_mcp | internal_spec | manual_upload`
- `ModelProfile`: `primary | customtools | fallback`
- `ProjectStatus`: `ideation | prd_draft | prd_approved | design_draft | design_approved | tech_plan_draft | tech_plan_approved | codegen | security_gate | deploy_ready | deploying | deployed | failed`
- `ApprovalStage`: `prd | design | tech_plan | deploy`
- `ArtifactType`: `prd | design_spec | tech_plan | code_snapshot | security_report | deploy_report`

## Linting Configuration

- **Ruff:** Python 3.14 target, 120 char line length, rules: E, F, I, N, W, UP
- **MyPy:** Strict mode, pydantic plugin
- **ESLint:** Next.js core-web-vitals + typescript config
- **TypeScript:** Strict mode, `@/*` path alias to `./src/*`

## Canonical Source Files

| File | Purpose |
|------|---------|
| `PRD.MD` | Product requirements |
| `TECH-PLAN.MD` | Technical architecture |
| `IMPLEMENTATION-PLAN-V2.MD` | AI agent implementation runbook (12 phases) |
| `contracts/openapi.yaml` | OpenAPI 3.1.0 API contract (8 endpoints) |
| `contracts/domain-types.ts` | Canonical TypeScript type definitions |
| `db/schema.sql` | PostgreSQL schema (9 tables, enums) |
| `orchestration/state-machine.md` | State machine node/transition spec |
| `qa/acceptance-test-plan.md` | 8 acceptance scenarios and exit criteria |
| `.TODO/` | Per-phase implementation guides (00-15) |

## Integration Strategy

- **Native APIs** for production-critical paths: GitHub REST/GraphQL, Supabase management API, Vercel deployment API
- **MCP adapters** (GitHub/Supabase/Vercel) are optional and feature-flagged, never default
- **Stitch MCP**
