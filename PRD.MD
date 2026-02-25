# Product Requirements Document (PRD): ID8 MVP v2

## 1. Executive Summary
**Product Name:** ID8  
**Release Mode:** Internal operator tool (MVP)  
**Vision:** Turn a natural language app concept into a production web app with explicit Human-In-The-Loop (HITL) approvals.  
**Core Value Proposition:** A stateful AI system that generates product artifacts, code, and deployment outputs while preserving review gates, security controls, and auditability.

This v2 PRD sets these product defaults:
1. Stitch MCP is a first-class design generation provider.
2. Gemini 3.1 Pro is the default LLM family.
3. Deployment critical steps use native APIs first, with MCP as optional adapters.

## 2. Goals and Non-Goals
### Goals
1. Go from prompt to production URL with explicit approval gates.
2. Keep all artifacts versioned and resumable.
3. Enforce pre-deploy security checks.
4. Support iterative design refinement before code generation.

### Non-Goals (MVP)
1. Fully self-serve external SaaS onboarding.
2. Native mobile app generation.
3. Legacy monolith migration and large repository import.
4. Post-deploy analytics product suite.

## 3. Target Audience
1. Internal operators building MVPs for founders and product teams.
2. Product teams validating new workflows quickly with production-like outputs.
3. Engineers accelerating first implementation drafts with approved architecture and security gates.

## 4. User Flow and Approval Gates
The system follows a strict state machine with resumable checkpoints.

1. User submits prompt and constraints.
2. System generates PRD draft.
3. Gate 1: PRD approve or request revision.
4. System generates design artifacts via Stitch MCP.
5. Gate 2: design approve or request targeted screen revisions.
6. System generates technical plan.
7. Gate 3: technical plan approve or request revision.
8. System generates code and runs quality checks.
9. System runs mandatory security gate.
10. System opens Git branch and pull request, executes checks, merges on pass.
11. Gate 4: explicit deploy approval.
12. System deploys to production and returns deployment report.

## 5. Functional Requirements
### Module 1: Prompt Intake and Product Definition
1. Accept multi-paragraph text, attachments, and constraints.
2. Produce structured PRD with user stories, scope boundaries, and entity list.
3. Allow section-level edit, reject, and approve actions.

### Module 2: Design Engine
1. Translate approved PRD into design prompt constraints.
2. Use `DesignProvider` with these values:
`stitch_mcp | internal_spec | manual_upload`.
3. Generate screen-level outputs and maintain version history.
4. Support iterative feedback by screen and component target.

### Module 3: Planning and LLM Routing
1. Produce technical plan with folder structure, DB schema, API routes, and component hierarchy.
2. Route models by node type:
`planning/reasoning => gemini-3.1-pro-preview`  
`tool-heavy coding/orchestration => gemini-3.1-pro-preview-customtools`  
`fallback => gemini-2.5-pro`
3. Record model and prompt metadata for every generated artifact.

### Module 4: Code Generation and Security
1. Generate backend and frontend code from approved artifacts.
2. Run mandatory security gate before deploy:
SAST, dependency audit, and secret scanning.
3. Block deployment on unresolved critical/high findings.
4. Persist machine-readable security report artifacts.

### Module 5: Repository and Merge Workflow
1. Authenticate GitHub access.
2. Create repository if missing.
3. Push to generated branch, open pull request, run checks, merge on pass.
4. Direct push to `main` is disallowed for automation.

### Module 6: Deployment
1. Provision and configure Supabase and Vercel via native APIs for production-critical reliability.
2. Keep MCP adapters optional and feature-flagged.
3. Inject only publishable keys into frontend runtime.
4. Keep server-only credentials on backend only.

### Module 7: Operator Visibility
1. Show status timeline for every project run.
2. Show retries, failures, and resume actions.
3. Show model usage and token-cost summaries.

## 6. Public Interfaces and Types
### Enums
1. `DesignProvider = stitch_mcp | internal_spec | manual_upload`
2. `ModelProfile = primary | customtools | fallback`
3. `ProjectStatus = ideation | prd_draft | prd_approved | design_draft | design_approved | tech_plan_draft | tech_plan_approved | codegen | security_gate | deploy_ready | deploying | deployed | failed`

### Required API Endpoints
1. `POST /v1/projects/{id}/design/generate` with `provider`, `model_profile`, and `prompt_constraints`.
2. `POST /v1/projects/{id}/design/feedback` for targeted regeneration.
3. `POST /v1/projects/{id}/approvals` with `stage=prd|design|tech_plan|deploy`.

## 7. Non-Functional Requirements
### Performance SLOs
1. PRD generation: p50 <= 45s, p95 <= 120s.
2. Design generation: p50 <= 90s, p95 <= 240s.
3. Full build and deploy: p50 <= 12m, p95 <= 30m.

### Reliability
1. Retries with backoff for transient provider failures.
2. Idempotency keys for run and deploy requests.
3. Resume from last successful node after failure.

### Security
1. Encrypt provider credentials at rest.
2. Redact secrets in logs and artifacts.
3. Enforce role-based operator access and audit trails.

### Extensibility
1. Provider adapter interfaces isolate external integration logic.
2. MCP and native API adapters share common contracts.

## 8. Assumptions and Defaults
1. Stitch MCP setup docs are authoritative for integration.
2. Gemini 3.1 Pro Preview is acceptable for MVP with explicit fallback.
3. Internal operator tool is the go-to-market mode for MVP.
4. Direct production deployment requires explicit final approval event.

## 9. References
1. Stitch MCP setup: https://stitch.withgoogle.com/docs/mcp/setup/?pli=1
2. Gemini models index: https://ai.google.dev/gemini-api/docs/models
3. Gemini 3.1 Pro details: https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview
