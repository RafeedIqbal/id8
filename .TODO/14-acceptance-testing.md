# Task 14: Acceptance Testing & QA

## Goal
Execute all 8 acceptance scenarios from `qa/acceptance-test-plan.md`. Produce a go/no-go report.

## Dependencies
- ALL previous tasks (this is the final validation)

## Source of Truth
- `qa/acceptance-test-plan.md` — scenarios and exit criteria

## Steps

### 1. Test environment setup
- [ ] Dedicated test GitHub org or sandbox repo namespace
- [ ] Supabase test project with isolated database
- [ ] Vercel test team credentials
- [ ] Stitch MCP configured with valid test credentials
  - API key path validated (X-Goog-Api-Key)
  - OAuth path validated (Authorization bearer + X-Goog-User-Project)
- [ ] Seed operator user with `admin` role
- [ ] Environment config pointing to all test services

### 2. Scenario 1: Happy Path
- [ ] Create project with sample prompt
- [ ] Approve PRD, design, and tech plan at each gate
- [ ] Approve deploy stage
- [ ] **Assert**: status ends at `deployed`
- [ ] **Assert**: live URL is returned and persisted
- [ ] **Assert**: all 6 artifact types exist (prd, design_spec, tech_plan, code_snapshot, security_report, deploy_report)

### 3. Scenario 2: Stitch Iteration Loop
- [ ] Attempt design generation without Stitch credentials
- [ ] **Assert**: UI/API returns actionable setup prompt to create API key in Stitch Settings
- [ ] Generate initial design using `stitch_mcp`
- [ ] Submit targeted feedback for one screen
- [ ] Approve updated design
- [ ] **Assert**: `design_spec` version increments
- [ ] **Assert**: previous version remains accessible
- [ ] **Assert**: feedback note is linked in artifact metadata
- [ ] **Assert**: artifact metadata includes Stitch usable tool inventory

### 4. Scenario 3: Stitch Outage Fallback
- [ ] Force Stitch MCP adapter error (mock/disconnect endpoint)
- [ ] Trigger design generation
- [ ] **Assert**: system switches to `internal_spec`
- [ ] **Assert**: warning event is logged in audit stream
- [ ] **Assert**: run continues without manual intervention

### 5. Scenario 4: Model Routing
- [ ] Trigger PRD generation and code generation in one run
- [ ] Collect model profile telemetry per node
- [ ] **Assert**: PRD node uses `gemini-3.1-pro-preview`
- [ ] **Assert**: tool-heavy nodes use `gemini-3.1-pro-preview-customtools`
- [ ] **Assert**: fallback model appears only on configured retry conditions

### 6. Scenario 5: Security Block
- [ ] Inject vulnerable dependency and fake secret in generated code
- [ ] Run security gate
- [ ] **Assert**: report marks high/critical findings
- [ ] **Assert**: run does NOT enter deploy states
- [ ] **Assert**: remediation loop returns to `WriteCode`

### 7. Scenario 6: Git Policy Enforcement
- [ ] Attempt automated direct push to protected branch
- [ ] Run normal PR flow
- [ ] **Assert**: direct push path is rejected
- [ ] **Assert**: branch + PR + checks + merge path succeeds

### 8. Scenario 7: Resume Reliability
- [ ] Kill worker during `PreparePR`
- [ ] Resume run by idempotency key
- [ ] **Assert**: no duplicate PR or duplicate deploy is created
- [ ] **Assert**: run continues from last successful checkpoint

### 9. Scenario 8: Secret Safety
- [ ] Deploy app and inspect frontend bundle and artifacts
- [ ] Check logs and audit event payloads
- [ ] **Assert**: no server-only credentials exposed
- [ ] **Assert**: only publishable keys appear in frontend runtime
- [ ] **Assert**: secret values are redacted in logs

### 10. QA report
- [ ] Produce structured go/no-go report:
  ```
  Scenario | Status | Notes
  ---------|--------|------
  1. Happy Path | PASS/FAIL | ...
  2. Stitch Loop | PASS/FAIL | ...
  ...
  ```
- [ ] Any failures include root cause and owner

## Exit Criteria
- [ ] All 8 scenarios pass in CI for two consecutive runs
- [ ] No unresolved critical security findings
- [ ] p95 latencies are within documented SLO limits

## MVP Release Gates (final check)
- [ ] Security gate blocks correctly on high/critical issues
- [ ] Deploy approval stage is enforced
- [ ] Stitch-to-fallback design generation path is verified
- [ ] No server-only credentials leak to frontend artifacts
