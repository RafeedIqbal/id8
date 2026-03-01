# ID8

**AI-powered application generator that turns natural language prompts into production-deployed web apps.**

Built for the [Wealthsimple AI Builder Program](https://www.wealthsimple.com). ID8 is an internal operator tool that orchestrates the full lifecycle — from idea to deployed application — with human-in-the-loop approval gates at every critical stage.

---

## How It Works

Describe what you want to build in plain English. ID8 handles the rest:

```
"Build a portfolio tracker that lets users add stocks and see their total value"
```

The orchestration engine runs through a structured pipeline, pausing at each gate for human review:

```
Prompt → PRD → [Approve] → Design → [Approve] → Code → Security Scan → PR → [Approve] → Deploy
```

Each approval gate lets you review, provide feedback, and reject with structured comments that loop back to the generation step — keeping a human in control of every decision.

---

## Architecture

### State Machine

The core of ID8 is a 10-node orchestration state machine:

| Node | Description |
|------|-------------|
| **IngestPrompt** | Parse and validate the user's natural language input |
| **GeneratePRD** | LLM generates a product requirements document |
| **WaitPRDApproval** | Human reviews and approves/rejects the PRD |
| **GenerateDesign** | Design spec generated via Stitch MCP |
| **WaitDesignApproval** | Human reviews and approves/rejects the design |
| **WriteCode** | Multi-phase template-aware code generation |
| **SecurityGate** | SAST, secret scanning, and dependency audit |
| **PreparePR** | Creates a GitHub PR with the generated code |
| **WaitDeployApproval** | Human reviews the PR and approves deployment |
| **DeployProduction** | Deploys to Vercel + Supabase |

Rejection at any gate loops back to the generation step with structured feedback. Every step is idempotent and resumable from the last checkpoint.

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, Pydantic v2 |
| **Frontend** | Next.js 15 (App Router), React 19, TanStack Query 5, Tailwind CSS 4 |
| **Database** | PostgreSQL 16 |
| **LLM** | Google Gemini via `google-genai` SDK |
| **Design** | Stitch MCP (primary), internal spec fallback |
| **Deployment** | Vercel (frontend) + Supabase (database/backend) |
| **CI/Git** | GitHub REST API for repo and PR management |

### Service Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│   FastAPI    │────▶│  PostgreSQL  │
│  Next.js 15  │     │   REST API   │     │     16       │
│   :3000      │     │   :8000      │     │   :5432      │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │                      ▲
                    ┌──────▼───────┐              │
                    │   Worker     │──────────────┘
                    │  (poller)    │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌────────┐  ┌─────────┐  ┌─────────┐
         │ Gemini │  │ GitHub  │  │ Vercel  │
         │  API   │  │  API    │  │  API    │
         └────────┘  └─────────┘  └─────────┘
```

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- API keys for: Google Gemini, GitHub, Vercel, Stitch MCP (see below)

### 1. Clone and configure

```bash
git clone https://github.com/your-org/id8.git
cd id8
cp .env.example .env
```

Fill in your `.env`:

```env
GEMINI_API_KEY=your-gemini-key
GITHUB_TOKEN=your-github-pat
VERCEL_TOKEN=your-vercel-token
VERCEL_TEAM_ID=your-vercel-team
STITCH_MCP_ENDPOINT=your-stitch-endpoint
STITCH_MCP_API_KEY=your-stitch-key
```

### 2. Start everything

```bash
make dev
```

This spins up all five services via Docker Compose:

| Service | Port | Description |
|---------|------|-------------|
| **db** | 5432 | PostgreSQL 16 |
| **migrate** | — | Runs Alembic migrations on startup |
| **api** | 8000 | FastAPI with hot reload |
| **worker** | — | Background orchestration poller |
| **frontend** | 3000 | Next.js dev server |

Open [http://localhost:3000](http://localhost:3000) to start building.

### Local Development (without Docker)

For faster iteration, run services individually:

```bash
# Terminal 1 — Database only
make dev-db

# Terminal 2 — Backend API
cd backend && source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 3 — Background worker
cd backend && source .venv/bin/activate
python -m app.worker

# Terminal 4 — Frontend
cd frontend && npm run dev
```

---

## Project Structure

```
id8/
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── orchestrator/     # State machine engine + 10 node handlers
│   │   ├── llm/              # Gemini client, model router, prompt templates
│   │   ├── design/           # Stitch MCP + internal spec design providers
│   │   ├── codegen/          # Template project loader and merger
│   │   ├── security/         # SAST, secret scan, dependency audit
│   │   ├── deploy/           # Vercel + Supabase deployment clients
│   │   ├── github/           # GitHub REST API client
│   │   ├── models/           # SQLAlchemy ORM models (9 tables)
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── routes/           # FastAPI endpoint routers
│   │   └── observability/    # Audit logging, metrics, cost tracking
│   ├── alembic/              # Database migrations
│   └── tests/
├── frontend/                 # Next.js 15 application
│   └── src/
│       ├── app/              # App router pages
│       ├── components/       # UI components
│       ├── lib/              # API client, hooks, utilities
│       └── types/            # TypeScript domain types
├── exampleApp/               # Next.js template used as codegen base
├── contracts/                # OpenAPI spec + canonical TypeScript types
├── db/                       # PostgreSQL schema reference
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Development

### Commands

| Command | Description |
|---------|-------------|
| `make dev` | Start all services (Docker) |
| `make dev-db` | Start only PostgreSQL |
| `make dev-api` | Run API server locally |
| `make dev-frontend` | Run frontend dev server |
| `make migrate` | Run database migrations |
| `make test-backend` | Run backend test suite |
| `make test-frontend` | Lint + typecheck frontend |
| `make lint` | Lint everything (ruff, mypy, eslint) |

### Linting

**Backend** — Ruff (format + check) and mypy (strict mode with Pydantic plugin):
```bash
cd backend && ruff check app/ && ruff format --check app/ && mypy app/
```

**Frontend** — ESLint with Next.js + TypeScript config:
```bash
cd frontend && npm run lint
```

Pre-commit hooks automatically run `ruff format`, `ruff check`, and `mypy` on staged Python files.

---

## Key Design Decisions

- **Idempotent execution** — Every orchestration step is keyed by `run_id + node_name`, making retries safe and resumable from any checkpoint.
- **Template-aware codegen** — Generated code is merged into a real Next.js project template (`exampleApp/`), not built from scratch, ensuring consistent structure and working builds.
- **Mandatory security gate** — High/critical findings from SAST, secret scanning, or dependency audit block deployment. No bypasses.
- **Credential isolation** — Server-side secrets never leak into frontend artifacts or generated code.
- **Native API integrations** — GitHub, Vercel, and Supabase use direct REST APIs for reliability. MCP adapters are optional and feature-flagged.

---

## License

Internal tool — not open-source.
