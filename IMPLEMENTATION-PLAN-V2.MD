# ID8 MVP v2 Implementation Plan For AI Agents

## Scope
This runbook is decision-complete for implementing ID8 MVP v2 as an internal operator tool using Stitch MCP for design generation and Gemini 3.1 Pro model routing.

## Global Defaults
1. Primary model: `gemini-3.1-pro-preview`
2. Tool-heavy model: `gemini-3.1-pro-preview-customtools`
3. Fallback model: `gemini-2.5-pro`
4. Design provider order: `stitch_mcp` then `internal_spec`
5. Deployment target: production only after explicit deploy approval

## Agent Sequence
### 1. Agent-Docs
Tasks:
1. Align PRD and technical plan to v2.
2. Validate links and references for Stitch and Gemini.
Outputs:
1. Updated `PRD.MD`
2. Updated `TECH-PLAN.MD`
Definition of done:
1. All v2 decisions are reflected in both docs.
2. No direct push-to-main wording remains.

### 2. Agent-Contracts
Tasks:
1. Publish API contract in OpenAPI.
2. Publish shared domain types used by API, DB, and workers.
Outputs:
1. `contracts/openapi.yaml`
2. `contracts/domain-types.ts`
Definition of done:
1. Endpoint list exactly matches the PRD and tech plan.
2. Enums are consistent across all contracts.

### 3. Agent-Data
Tasks:
1. Implement canonical SQL schema and enum definitions.
2. Add indexes for status timeline, retries, and artifacts.
Outputs:
1. `db/schema.sql`
Definition of done:
1. Schema supports all statuses, artifacts, approvals, and deploy records.
2. Idempotency and retry metadata are stored.

### 4. Agent-Orchestrator
Tasks:
1. Implement persisted state machine transitions.
2. Implement checkpointing, retries, and resume-from-node.
Outputs:
1. Orchestrator module using `orchestration/state-machine.md` as source of truth.
Definition of done:
1. All nodes and transitions are executable.
2. Failed runs can resume without duplicate side effects.

### 5. Agent-Design
Tasks:
1. Implement Stitch MCP adapter as the default provider.
2. Implement fallback `internal_spec` adapter.
3. Implement iterative design feedback endpoint behavior.
Outputs:
1. Provider adapter interfaces and implementations.
Definition of done:
1. Design generation works with Stitch MCP.
2. Outage fallback to internal provider is automatic and logged.

### 6. Agent-LLM
Tasks:
1. Implement model routing by node type.
2. Persist model profile and token usage per artifact.
Outputs:
1. LLM router and telemetry bindings.
Definition of done:
1. Planning nodes use `primary`.
2. Tool-heavy nodes use `customtools`.
3. Fallback used on retry conditions only.

### 7. Agent-Codegen
Tasks:
1. Generate code snapshots from approved PRD, design, and tech plan.
2. Run compile/test checks before PR preparation.
Outputs:
1. Versioned `code_snapshot` artifacts.
Definition of done:
1. Buildable code snapshot is produced.
2. Failures return actionable remediation data.

### 8. Agent-Security
Tasks:
1. Integrate SAST, dependency audit, and secret scan.
2. Mark findings with severity and remediation state.
Outputs:
1. `security_report` artifacts.
Definition of done:
1. Critical/high unresolved findings block deployment.
2. Report is machine-readable and shown in operator UI.

### 9. Agent-GitHub
Tasks:
1. Create repository if absent.
2. Push branch, open PR, poll checks, merge on pass.
Outputs:
1. PR URL and merge status in artifacts.
Definition of done:
1. Branch protection policy is respected.
2. No automation path pushes directly to protected branches.

### 10. Agent-Deploy
Tasks:
1. Provision Supabase and Vercel using native APIs.
2. Deploy merged build to production after deploy approval.
Outputs:
1. `deploy_report` artifact with live url and provider payload.
Definition of done:
1. Production URL is available and persisted on project.
2. Deploy failures are resumable or rollback-labeled.

### 11. Agent-Observability
Tasks:
1. Emit node latency, retries, failure classes, and cost metrics.
2. Emit audit events for approvals and deploy actions.
Outputs:
1. Telemetry and audit event stream.
Definition of done:
1. p50 and p95 metrics available for PRD/design/full pipeline.
2. Cost and token usage visible by model profile.

### 12. Agent-QA
Tasks:
1. Execute the acceptance scenarios in `qa/acceptance-test-plan.md`.
2. Produce go/no-go report.
Outputs:
1. QA signoff report.
Definition of done:
1. All critical scenarios pass.
2. Any failures include root cause and owner.

## Release Gate
MVP can launch only when all items are true:
1. Security gate blocks correctly on high/critical issues.
2. Deploy approval stage is enforced.
3. Stitch-to-fallback design generation path is verified.
4. No server-only credentials leak to frontend artifacts.
