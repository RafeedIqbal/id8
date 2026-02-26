# ID8 Implementation Tasks

## Task Order & Dependencies

```
00-project-scaffolding
 └─► 01-database-and-models
      └─► 02-api-routes-skeleton
           └─► 03-orchestrator-state-machine
                ├─► 04-llm-router
                │    ├─► 05-prd-generation
                │    ├─► 07-tech-plan-generation
                │    └─► 08-code-generation
                ├─► 06-design-engine (also needs 04)
                └─► 13-observability
09-security-gate ◄── 08-code-generation
10-github-integration ◄── 09-security-gate
11-deployment-pipeline ◄── 10-github-integration
12-frontend-operator-console ◄── 02-api-routes-skeleton
15-project-lifecycle-and-artifact-ux-fixes ◄── 12-frontend-operator-console
14-acceptance-testing ◄── ALL
```

## Parallel Work Opportunities

After Task 03 (orchestrator) is done, these can proceed in parallel:
- Tasks 04-08 (LLM router + all generation nodes)
- Task 12 (frontend — only needs API routes)
- Task 13 (observability — only needs orchestrator hooks)

Tasks 09 → 10 → 11 are sequential (security → GitHub → deploy).
Task 15 is a post-Task-12 polish pass and should complete before Task 14 acceptance testing.

## Task List

| # | Task | Description |
|---|------|-------------|
| 00 | [Project Scaffolding](00-project-scaffolding.md) | Monorepo, package managers, Docker, dev tooling |
| 01 | [Database & Models](01-database-and-models.md) | SQLAlchemy models, Alembic migrations, Pydantic schemas |
| 02 | [API Routes Skeleton](02-api-routes-skeleton.md) | All 8 FastAPI endpoints with DB operations |
| 03 | [Orchestrator State Machine](03-orchestrator-state-machine.md) | Core engine: transitions, checkpointing, retries, resume |
| 04 | [LLM Router](04-llm-router.md) | Gemini model routing, fallback, token tracking |
| 05 | [PRD Generation](05-prd-generation.md) | IngestPrompt + GeneratePRD nodes |
| 06 | [Design Engine](06-design-engine.md) | Stitch MCP adapter, fallback, feedback loop |
| 07 | [Tech Plan Generation](07-tech-plan-generation.md) | GenerateTechPlan node |
| 08 | [Code Generation](08-code-generation.md) | WriteCode node with validation |
| 09 | [Security Gate](09-security-gate.md) | SAST, dependency audit, secret scan |
| 10 | [GitHub Integration](10-github-integration.md) | Repo, branch, PR, checks, merge |
| 11 | [Deployment Pipeline](11-deployment-pipeline.md) | Supabase + Vercel provisioning and deploy |
| 12 | [Frontend Console](12-frontend-operator-console.md) | Next.js operator UI for all workflows |
| 13 | [Observability](13-observability.md) | Metrics, audit events, cost tracking |
| 15 | [Project Lifecycle + Artifact UX Fixes](15-project-lifecycle-and-artifact-ux-fixes.md) | Timeline replay, artifact nav cleanup, delete/restart, stack constraints, viewer fixes |
| 14 | [Acceptance Testing](14-acceptance-testing.md) | All 8 QA scenarios + go/no-go report |
