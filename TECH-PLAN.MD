# Technical Implementation Plan: ID8 MVP v2

## 1. Architecture Overview
ID8 uses a persisted orchestration backend to manage project state, HITL gates, and provider integrations.

### Core Components
1. Frontend: Next.js operator console for prompt intake, artifact review, approvals, and run monitoring.
2. Orchestrator API: FastAPI service exposing project/run endpoints and state transitions.
3. Worker runtime: async job processor for long-running model and provider steps.
4. Database: PostgreSQL (Supabase-hosted) for state, artifacts, approvals, retries, and audit logs.
5. LLM router: model-profile based routing for planning vs tool-heavy execution.
6. Provider adapters:
`stitch_mcp`, `github_api`, `supabase_api`, `vercel_api`, optional MCP adapters behind feature flags.

### Model Routing
1. `primary` -> `gemini-3.1-pro-preview`
2. `customtools` -> `gemini-3.1-pro-preview-customtools`
3. `fallback` -> `gemini-2.5-pro`

## 2. Canonical Domain Types
### Enums
1. `DesignProvider = stitch_mcp | internal_spec | manual_upload`
2. `ModelProfile = primary | customtools | fallback`
3. `ProjectStatus = ideation | prd_draft | prd_approved | design_draft | design_approved | tech_plan_draft | tech_plan_approved | codegen | security_gate | deploy_ready | deploying | deployed | failed`
4. `ApprovalStage = prd | design | tech_plan | deploy`

### Artifact Types
1. `prd`
2. `design_spec`
3. `tech_plan`
4. `code_snapshot`
5. `security_report`
6. `deploy_report`

## 3. API Surface (MVP)
1. `POST /v1/projects`
2. `GET /v1/projects/{id}`
3. `POST /v1/projects/{id}/runs`
4. `POST /v1/projects/{id}/design/generate`
5. `POST /v1/projects/{id}/design/feedback`
6. `POST /v1/projects/{id}/approvals`
7. `GET /v1/projects/{id}/artifacts`
8. `POST /v1/projects/{id}/deploy`

### Key Contract Rules
1. Every mutating endpoint supports an idempotency key.
2. Every run step writes a structured artifact or failure record.
3. `deploy` calls are rejected unless `ApprovalStage=deploy` is approved.

## 4. Database Schema (Logical)
### `users`
1. `id` uuid primary key
2. `email` text unique
3. `role` text check in (`operator`, `admin`)
4. `created_at`, `updated_at`

### `projects`
1. `id` uuid primary key
2. `owner_user_id` uuid references `users(id)`
3. `initial_prompt` text not null
4. `status` project_status_enum not null
5. `github_repo_url` text null
6. `live_deployment_url` text null
7. `created_at`, `updated_at`

### `project_runs`
1. `id` uuid primary key
2. `project_id` uuid references `projects(id)`
3. `status` project_status_enum not null
4. `current_node` text not null
5. `idempotency_key` text unique
6. `last_error_code` text null
7. `last_error_message` text null
8. `created_at`, `updated_at`

### `project_artifacts`
1. `id` uuid primary key
2. `project_id` uuid references `projects(id)`
3. `run_id` uuid references `project_runs(id)`
4. `artifact_type` artifact_type_enum not null
5. `version` int not null
6. `content` jsonb not null
7. `model_profile` model_profile_enum null
8. `created_at`

### `approval_events`
1. `id` uuid primary key
2. `project_id` uuid references `projects(id)`
3. `run_id` uuid references `project_runs(id)`
4. `stage` approval_stage_enum not null
5. `decision` text check in (`approved`, `rejected`)
6. `notes` text null
7. `created_by` uuid references `users(id)`
8. `created_at`

### `provider_credentials`
1. `id` uuid primary key
2. `user_id` uuid references `users(id)`
3. `provider` text not null
4. `encrypted_secret` text not null
5. `secret_scope` text not null
6. `last_rotated_at` timestamptz null
7. `created_at`, `updated_at`

### `audit_events`
1. `id` uuid primary key
2. `project_id` uuid null references `projects(id)`
3. `actor_user_id` uuid null references `users(id)`
4. `event_type` text not null
5. `event_payload` jsonb not null
6. `created_at`

## 5. State Machine
### Nodes
1. `IngestPrompt`
2. `GeneratePRD`
3. `WaitPRDApproval`
4. `GenerateDesign` (provider defaults to `stitch_mcp`)
5. `WaitDesignApproval`
6. `GenerateTechPlan`
7. `WaitTechPlanApproval`
8. `WriteCode`
9. `SecurityGate`
10. `PreparePR`
11. `WaitDeployApproval`
12. `DeployProduction`
13. `EndSuccess`
14. `EndFailed`

### Transition Rules
1. Rejection at PRD, design, or tech plan loops back to corresponding generation node with structured feedback payload.
2. Security failure loops to `WriteCode` with failing findings context.
3. Deploy requires explicit `deploy` approval event.
4. Any non-retryable provider failure transitions to `EndFailed` with resume metadata.

## 6. Integration Strategy
### Production-Critical Path
1. GitHub: native REST/GraphQL APIs for repo, branch, pull request, and checks state.
2. Supabase: native management and SQL migration path.
3. Vercel: native deployment APIs.

### MCP Strategy
1. Stitch MCP is first-class for design generation.
2. Optional MCP adapters for GitHub/Vercel/Supabase are feature flagged and non-default.

## 7. Security and Secrets
1. Service-role and server-only keys stay backend-only.
2. Frontend receives publishable runtime values only.
3. Secrets are encrypted at rest and redacted in logs.
4. Security gate blocks deploy on unresolved high/critical findings.

## 8. SLOs and Observability
### Performance Targets
1. PRD generation p50 <= 45s, p95 <= 120s.
2. Design generation p50 <= 90s, p95 <= 240s.
3. End-to-end build and deploy p50 <= 12m, p95 <= 30m.

### Required Metrics
1. Node latency histogram by run step.
2. Retry count and terminal failure reasons.
3. Token usage and cost by model profile.
4. Deployment success rate and time-to-live-url.

## 9. Agent Execution Sequence
1. Docs: align PRD and technical docs to v2.
2. Contracts: publish OpenAPI and shared enums.
3. Orchestrator: implement persisted state machine and idempotency.
4. Design: implement Stitch MCP adapter and fallback provider.
5. LLM: configure model profiles and router.
6. Codegen: implement file generation pipeline from approved artifacts.
7. Security: wire SAST, dependency audit, and secret scan gate.
8. GitHub: implement branch, PR, checks, merge workflow.
9. Deploy: implement Supabase and Vercel native provisioning/deploy.
10. Observability: emit structured metrics and traces.
11. QA: run acceptance suite and publish go/no-go.

## 10. Validation Scenarios
1. Happy path prompt to production URL.
2. Design feedback loop with versioned artifacts.
3. Stitch outage fallback to `internal_spec`.
4. Model routing correctness by node type.
5. Security failure blocks deployment.
6. Branch protection prevents direct push.
7. Resume from failure without artifact loss.
8. No server-only credentials in frontend artifacts.
