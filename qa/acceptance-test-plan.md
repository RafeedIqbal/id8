# ID8 MVP v2 Acceptance Test Plan

## Test Environment
1. Dedicated test GitHub org or sandbox repo namespace.
2. Supabase test project and Vercel test team credentials.
3. Stitch MCP configured with valid operator credentials.
4. Seed operator user with `admin` role.

## Scenarios
### 1. Happy Path
Steps:
1. Create project with prompt.
2. Approve PRD, design, and tech plan.
3. Approve deploy stage.
Expected:
1. Status ends at `deployed`.
2. Live URL is returned and persisted.
3. Artifacts include `prd`, `design_spec`, `tech_plan`, `code_snapshot`, `security_report`, `deploy_report`.

### 2. Stitch Iteration Loop
Steps:
1. Generate initial design using `stitch_mcp`.
2. Submit targeted feedback for one screen.
3. Approve updated design.
Expected:
1. `design_spec` version increments.
2. Previous version remains accessible.
3. Feedback note is linked in artifact metadata.

### 3. Stitch Outage Fallback
Steps:
1. Force Stitch MCP adapter error.
2. Trigger design generation.
Expected:
1. System switches to `internal_spec`.
2. Warning event is logged in audit stream.
3. Run continues without manual intervention.

### 4. Model Routing
Steps:
1. Trigger PRD generation and code generation in one run.
2. Collect model profile telemetry per node.
Expected:
1. PRD node uses `gemini-3.1-pro-preview`.
2. Tool-heavy nodes use `gemini-3.1-pro-preview-customtools`.
3. Fallback model appears only on configured retry conditions.

### 5. Security Block
Steps:
1. Inject vulnerable dependency and fake secret in generated code.
2. Run security gate.
Expected:
1. Report marks high/critical findings.
2. Run does not enter deploy states.
3. Remediation loop returns to `WriteCode`.

### 6. Git Policy Enforcement
Steps:
1. Attempt automated direct push to protected branch.
2. Run normal PR flow.
Expected:
1. Direct push path is rejected.
2. Branch + PR + checks + merge path succeeds.

### 7. Resume Reliability
Steps:
1. Kill worker during `PreparePR`.
2. Resume run by idempotency key.
Expected:
1. No duplicate PR or duplicate deploy is created.
2. Run continues from last successful checkpoint.

### 8. Secret Safety
Steps:
1. Deploy app and inspect frontend bundle and artifacts.
2. Check logs and audit event payloads.
Expected:
1. No server-only credentials exposed.
2. Only publishable keys appear in frontend runtime.
3. Secret values are redacted in logs.

## Exit Criteria
1. All scenarios pass in CI for two consecutive runs.
2. No unresolved critical security findings.
3. p95 latencies are within documented SLO limits.
