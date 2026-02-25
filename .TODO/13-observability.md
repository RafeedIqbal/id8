# Task 13: Observability (Metrics, Audit, Telemetry)

## Goal
Emit structured metrics, audit events, and cost tracking across the entire pipeline. Enable operator visibility into performance and costs.

## Dependencies
- Task 03 (orchestrator — emit events at each node transition)
- Task 04 (LLM router — token/cost data)

## Source of Truth
- `TECH-PLAN.MD` §8 — SLOs and Observability
- `PRD.MD` §5.7 — Module 7: Operator Visibility
- `IMPLEMENTATION-PLAN-V2.MD` — Agent-Observability

## Steps

### 1. Audit event emitter
- [ ] `backend/app/observability/audit.py`
- [ ] `async def emit_audit_event(project_id, actor_user_id, event_type, event_payload, db)`
- [ ] Writes to `audit_events` table
- [ ] Event types to emit:
  - `run.started`, `run.node_entered`, `run.node_completed`, `run.failed`, `run.completed`
  - `approval.submitted` (with stage, decision)
  - `design.provider_fallback` (Stitch → internal_spec)
  - `deploy.started`, `deploy.succeeded`, `deploy.failed`
  - `security.scan_completed` (with summary)
  - `github.repo_created`, `github.pr_created`, `github.pr_merged`

### 2. Node latency tracking
- [ ] In orchestrator engine, wrap each node execution:
  ```python
  start = time.monotonic()
  result = await handler.execute(context)
  duration_ms = (time.monotonic() - start) * 1000
  ```
- [ ] Store in audit event payload: `{"node": "...", "duration_ms": ..., "attempt": ...}`
- [ ] Aggregate for p50/p95 reporting

### 3. Retry and failure metrics
- [ ] Track per node:
  - Retry count
  - Terminal failure reasons (categorized: provider_error, rate_limit, validation_error, policy_violation)
  - Time spent in retries
- [ ] Store in audit event stream

### 4. Token usage and cost tracking
- [ ] After each LLM call, record:
  - model_profile, model_id
  - prompt_tokens, completion_tokens
  - Estimated cost (based on per-token pricing config)
- [ ] Aggregate per project and per run
- [ ] Store in artifact metadata and emit as audit events

### 5. API endpoint for metrics
- [ ] `GET /v1/projects/{projectId}/metrics` (optional, for frontend consumption)
  - Return: node latencies, total tokens, total cost, retry counts
  - Derived from audit_events table

### 6. SLO monitoring helpers
- [ ] Performance targets from TECH-PLAN.MD:
  - PRD generation: p50 ≤ 45s, p95 ≤ 120s
  - Design generation: p50 ≤ 90s, p95 ≤ 240s
  - End-to-end: p50 ≤ 12m, p95 ≤ 30m
- [ ] Log warnings when individual node latencies exceed p95 targets
- [ ] Deployment success rate tracking

## Definition of Done
- [ ] Every node transition emits an audit event with timing data
- [ ] Token usage and cost visible per project
- [ ] Provider fallback events are logged
- [ ] Approval actions are audited with actor and decision
- [ ] p50 and p95 metrics available for key pipeline stages
- [ ] Cost and token usage visible by model profile
