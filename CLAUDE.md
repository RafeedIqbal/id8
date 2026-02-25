# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ID8 is an AI-powered application generation platform that turns natural language prompts into production-deployed web apps with strict Human-In-The-Loop (HITL) approval gates. It is an internal operator tool (MVP) submitted for the Wealthsimple AI builder program.

**Current state:** Specification-complete, awaiting implementation. The repo contains only design documents, contracts, and schemas — no runtime code yet.

## Planned Tech Stack

- **Backend:** FastAPI (Python)
- **Frontend:** Next.js (operator console)
- **Database:** PostgreSQL on Supabase
- **LLM:** Google Gemini 3.1 Pro (primary), with model routing by node type
- **Design Generation:** Stitch MCP (first-class), with `internal_spec` fallback
- **Deployment Targets:** Supabase (DB/backend) + Vercel (frontend)
- **VCS:** GitHub with branch protection (no direct push to main)

## Architecture

The system is a **persisted orchestration state machine** with 14 nodes:

`IngestPrompt → GeneratePRD → WaitPRDApproval → GenerateDesign → WaitDesignApproval → GenerateTechPlan → WaitTechPlanApproval → WriteCode → SecurityGate → PreparePR → WaitDeployApproval → DeployProduction → EndSuccess/EndFailed`

Four HITL approval gates: PRD, Design, Tech Plan, Deploy. Rejection loops back to the corresponding generation node with structured feedback.

### Key Architectural Invariants

- Every run step is **idempotent** by `run_id` + `node_name` + optional idempotency key
- Failures are **resumable** from the last successful checkpoint
- Artifacts are **versioned** (version column on `project_artifacts`)
- Security gate is **mandatory** — high/critical unresolved findings block deployment
- Deploy requires **explicit approval event** (`ApprovalStage=deploy`)
- Server-only credentials **never** leak to frontend artifacts

### Model Routing

| Profile | Model | Usage |
|---------|-------|-------|
| `primary` | `gemini-3.1-pro-preview` | Planning/reasoning nodes |
| `customtools` | `gemini-3.1-pro-preview-customtools` | Tool-heavy coding/orchestration |
| `fallback` | `gemini-2.5-pro` | Retry conditions only |

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

## Implementation Sequence

Follow `IMPLEMENTATION-PLAN-V2.MD` in order. Each agent phase has explicit inputs, outputs, and definition of done:

1. **Docs** → 2. **Contracts** → 3. **Data** → 4. **Orchestrator** → 5. **Design** → 6. **LLM** → 7. **Codegen** → 8. **Security** → 9. **GitHub** → 10. **Deploy** → 11. **Observability** → 12. **QA**

## Key Enums (must stay consistent across all contracts)

- `DesignProvider`: `stitch_mcp | internal_spec | manual_upload`
- `ModelProfile`: `primary | customtools | fallback`
- `ProjectStatus`: `ideation | prd_draft | prd_approved | design_draft | design_approved | tech_plan_draft | tech_plan_approved | codegen | security_gate | deploy_ready | deploying | deployed | failed`
- `ApprovalStage`: `prd | design | tech_plan | deploy`
- `ArtifactType`: `prd | design_spec | tech_plan | code_snapshot | security_report | deploy_report`

## Integration Strategy

- **Native APIs** for production-critical paths: GitHub REST/GraphQL, Supabase management API, Vercel deployment API
- **MCP adapters** (GitHub/Supabase/Vercel) are optional and feature-flagged, never default
- **Stitch MCP** is the exception — it is first-class for design generation

## MVP Release Gates

All must be true before launch:
1. Security gate blocks correctly on high/critical issues
2. Deploy approval stage is enforced
3. Stitch-to-fallback design generation path is verified
4. No server-only credentials leak to frontend artifacts
