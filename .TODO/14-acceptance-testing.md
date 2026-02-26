# Task 14: Acceptance Testing & QA

## Goal
Execute all 8 acceptance scenarios from `qa/acceptance-test-plan.md`. Produce a go/no-go report.

## Dependencies
- ALL previous tasks (this is the final validation)

## Source of Truth
- `qa/acceptance-test-plan.md` — scenarios and exit criteria

## Steps

### 1. Test environment setup
- [x] Dedicated test GitHub org or sandbox repo namespace
- [x] Supabase test project with isolated database
- [x] Vercel test team credentials
- [x] Stitch MCP configured with valid test credentials
  - API key path validated (X-Goog-Api-Key)
  - OAuth path validated (Authorization bearer + X-Goog-User-Project)
- [x] Seed operator user with `admin` role
- [x] Environment config pointing to all test services

### 2. Scenario 1: Happy Path
- [x] Create project with sample prompt
- [x] Approve PRD, design, and tech plan at each gate
- [x] Approve deploy stage
- [x] **Assert**: status ends at `deployed`
- [x] **Assert**: live URL is returned and persisted
- [x] **Assert**: all 6 artifact types exist (prd, design_spec, tech_plan, code_snapshot, security_report, deploy_report)

### 3. Scenario 2: Stitch Iteration Loop
- [x] Attempt design generation without Stitch credentials
- [x] **Assert**: UI/API returns actionable setup prompt to create API key in Stitch Settings
- [x] Generate initial design using `stitch_mcp`
- [x] Submit targeted feedback for one screen
- [x] Approve updated design
- [x] **Assert**: `design_spec` version increments
- [x] **Assert**: previous version remains accessible
- [x] **Assert**: feedback note is linked in artifact metadata
- [x] **Assert**: artifact metadata includes Stitch usable tool inventory

### 4. Scenario 3: Stitch Outage Fallback
- [x] Force Stitch MCP adapter error (mock/disconnect endpoint)
- [x] Trigger design generation
- [x] **Assert**: system switches to `internal_spec`
- [x] **Assert**: warning event is logged in audit stream
- [x] **Assert**: run continues without manual intervention

### 5. Scenario 4: Model Routing
- [x] Trigger PRD generation and code generation in one run
- [x] Collect model profile telemetry per node
- [x] **Assert**: PRD node uses `gemini-3.1-pro-preview`
- [x] **Assert**: tool-heavy nodes use `gemini-3.1-pro-preview-customtools`
- [x] **Assert**: fallback model appears only on configured retry conditions

### 6. Scenario 5: Security Block
- [x] Inject vulnerable dependency and fake secret in generated code
- [x] Run security gate
- [x] **Assert**: report marks high/critical findings
- [x] **Assert**: run does NOT enter deploy states
- [x] **Assert**: remediation loop returns to `WriteCode`

### 7. Scenario 6: Git Policy Enforcement
- [x] Attempt automated direct push to protected branch
- [x] Run normal PR flow
- [x] **Assert**: direct push path is rejected
- [x] **Assert**: branch + PR + checks + merge path succeeds

### 8. Scenario 7: Resume Reliability
- [x] Kill worker during `PreparePR`
- [x] Resume run by idempotency key
- [x] **Assert**: no duplicate PR or duplicate deploy is created
- [x] **Assert**: run continues from last successful checkpoint

### 9. Scenario 8: Secret Safety
- [x] Deploy app and inspect frontend bundle and artifacts
- [x] Check logs and audit event payloads
- [x] **Assert**: no server-only credentials exposed
- [x] **Assert**: only publishable keys appear in frontend runtime
- [x] **Assert**: secret values are redacted in logs

### 10. QA report
- [x] Produce structured go/no-go report:
  ```
  Scenario | Status | Notes
  ---------|--------|------
  1. Happy Path | PASS/FAIL | ...
  2. Stitch Loop | PASS/FAIL | ...
  ...
  ```
- [x] Any failures include root cause and owner

## Exit Criteria
- [x] All 8 scenarios pass in automated acceptance runs for two consecutive executions
- [x] No unresolved critical security findings
- [x] p95 latency guardrails are covered by automated metrics checks

## MVP Release Gates (final check)
- [x] Security gate blocks correctly on high/critical issues
- [x] Deploy approval stage is enforced
- [x] Stitch-to-fallback design generation path is verified
- [x] No server-only credentials leak to frontend artifacts

## Implementation Evidence
- Automated acceptance suite: `backend/tests/test_acceptance_testing.py`
- Go/no-go report: `qa/acceptance-go-no-go-report.md`
- Verification command (executed twice consecutively): `backend/.venv/bin/pytest -q backend/tests/test_acceptance_testing.py`
