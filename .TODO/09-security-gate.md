# Task 09: Security Gate (SecurityGate Node)

## Goal
Implement the mandatory security gate that runs SAST, dependency audit, and secret scanning on generated code. High/critical unresolved findings block deployment.

## Dependencies
- Task 08 (code generation — produces the code snapshot to scan)

## Source of Truth
- `orchestration/state-machine.md` — node 9
- `PRD.MD` §5.4 — Module 4: Security
- `IMPLEMENTATION-PLAN-V2.MD` — Agent-Security

## Steps

### 1. SecurityGate handler
- [ ] `backend/app/orchestrator/handlers/security_gate.py`
- [ ] Load latest `code_snapshot` artifact
- [ ] Write code files to a temp directory for scanning
- [ ] Run all three scanners
- [ ] Aggregate results into security report
- [ ] Determine pass/fail based on severity

### 2. SAST scanner
- [ ] `backend/app/security/sast.py`
- [ ] Use `bandit` (Python) and/or `semgrep` for multi-language SAST
- [ ] Parse findings into normalized format:
  ```python
  class SecurityFinding(BaseModel):
      rule_id: str
      severity: str        # critical, high, medium, low
      file_path: str
      line_number: int
      message: str
      remediation: str
      resolved: bool = False
  ```

### 3. Dependency audit
- [ ] `backend/app/security/dependency_audit.py`
- [ ] For Python: scan `requirements.txt` / `pyproject.toml` against known vulnerability DB
- [ ] For Node.js: parse `package.json` and check with `npm audit --json` equivalent
- [ ] Map vulnerabilities to same `SecurityFinding` format

### 4. Secret scanner
- [ ] `backend/app/security/secret_scan.py`
- [ ] Scan all generated files for patterns:
  - API keys (known patterns: `sk-`, `AKIA`, etc.)
  - Hardcoded passwords, tokens
  - Private keys, certificates
- [ ] Use regex-based detection or `detect-secrets` library
- [ ] Any secret found = `critical` severity

### 5. Security report artifact
- [ ] `backend/app/schemas/security_report.py`:
  ```python
  class SecurityReportContent(BaseModel):
      findings: list[SecurityFinding]
      summary: SecuritySummary  # counts by severity
      scan_tools: list[str]     # tools used
      passed: bool              # no unresolved high/critical
  ```
- [ ] Create `ProjectArtifact`:
  - artifact_type = `security_report`
  - content = SecurityReportContent

### 6. Pass/fail logic
- [ ] `passed = True` only if zero unresolved high or critical findings
- [ ] If passed: `NodeResult(outcome="passed")` → transition to `PreparePR`
- [ ] If failed: `NodeResult(outcome="failed")` → transition back to `WriteCode`
  - Include findings in context for code remediation

### 7. Report display
- [ ] Security report must be machine-readable (JSON)
- [ ] Include enough detail for the operator UI to display findings with file/line references

## Definition of Done
- [ ] Security gate runs all three scanners on generated code
- [ ] High/critical findings block progression to deploy
- [ ] Failed gate loops back to `WriteCode` with findings context
- [ ] Clean code passes the gate and proceeds to `PreparePR`
- [ ] Matches acceptance test scenario #5 (Security Block)
- [ ] No false blocking on clean, well-formed code
