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
- [x] `backend/app/orchestrator/handlers/security_gate.py`
- [x] Load latest `code_snapshot` artifact
- [x] Write code files to a temp directory for scanning
- [x] Run all three scanners
- [x] Aggregate results into security report
- [x] Determine pass/fail based on severity

### 2. SAST scanner
- [x] `backend/app/security/sast.py`
- [x] Use `bandit` (Python) and/or `semgrep` for multi-language SAST
- [x] Parse findings into normalized format:
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
- [x] `backend/app/security/dependency_audit.py`
- [x] For Python: scan `requirements.txt` / `pyproject.toml` against known vulnerability DB
- [x] For Node.js: parse `package.json` and check with `npm audit --json` equivalent
- [x] Map vulnerabilities to same `SecurityFinding` format

### 4. Secret scanner
- [x] `backend/app/security/secret_scan.py`
- [x] Scan all generated files for patterns:
  - API keys (known patterns: `sk-`, `AKIA`, etc.)
  - Hardcoded passwords, tokens
  - Private keys, certificates
- [x] Use regex-based detection or `detect-secrets` library
- [x] Any secret found = `critical` severity

### 5. Security report artifact
- [x] `backend/app/schemas/security_report.py`:
  ```python
  class SecurityReportContent(BaseModel):
      findings: list[SecurityFinding]
      summary: SecuritySummary  # counts by severity
      scan_tools: list[str]     # tools used
      passed: bool              # no unresolved high/critical
  ```
- [x] Create `ProjectArtifact`:
  - artifact_type = `security_report`
  - content = SecurityReportContent

### 6. Pass/fail logic
- [x] `passed = True` only if zero unresolved high or critical findings
- [x] If passed: `NodeResult(outcome="passed")` → transition to `PreparePR`
- [x] If failed: `NodeResult(outcome="failed")` → transition back to `WriteCode`
  - Include findings in context for code remediation

### 7. Report display
- [x] Security report must be machine-readable (JSON)
- [x] Include enough detail for the operator UI to display findings with file/line references

## Definition of Done
- [x] Security gate runs all three scanners on generated code
- [x] High/critical findings block progression to deploy
- [x] Failed gate loops back to `WriteCode` with findings context
- [x] Clean code passes the gate and proceeds to `PreparePR`
- [x] Matches acceptance test scenario #5 (Security Block)
- [x] No false blocking on clean, well-formed code
