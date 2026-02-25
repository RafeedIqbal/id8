# Task 08: Code Generation (WriteCode Node)

## Goal
Implement the `WriteCode` orchestrator node that generates a full code snapshot from approved PRD, design, and tech plan artifacts.

## Dependencies
- Task 04 (LLM router — `customtools` profile)
- Task 07 (tech plan — produces input artifact)

## Source of Truth
- `orchestration/state-machine.md` — node 8
- `PRD.MD` §5.4 — Module 4: Code Generation
- `IMPLEMENTATION-PLAN-V2.MD` — Agent-Codegen

## Steps

### 1. WriteCode handler
- [ ] `backend/app/orchestrator/handlers/write_code.py`
- [ ] Load approved artifacts: PRD, design_spec, tech_plan
- [ ] Use `customtools` model profile (tool-heavy coding)

### 2. Code generation strategy
- [ ] Generate code in structured chunks to stay within token limits:
  1. Backend files (API routes, models, services) based on tech plan's `api_routes` and `database_schema`
  2. Frontend files (pages, components) based on tech plan's `component_hierarchy` and design's `screens`
  3. Configuration files (package.json, requirements.txt, docker configs)
  4. Database migration files
- [ ] Each chunk: separate LLM call with context from previous chunks
- [ ] Assemble into a single `code_snapshot` artifact

### 3. Code snapshot format
- [ ] `backend/app/schemas/code_snapshot.py`:
  ```python
  class CodeFile(BaseModel):
      path: str           # e.g. "backend/app/routes/users.py"
      content: str        # file contents
      language: str       # python, typescript, sql, etc.

  class CodeSnapshotContent(BaseModel):
      files: list[CodeFile]
      build_command: str      # e.g. "npm run build"
      test_command: str       # e.g. "npm test"
      entry_point: str        # e.g. "backend/app/main.py"
  ```

### 4. Compile/test validation
- [ ] After generating code snapshot, run basic validation:
  - Check all import references resolve within the file set
  - Check for syntax errors (basic AST parse for Python, basic parse for TS)
  - Verify required files exist (entry point, config, package manifest)
- [ ] On validation failure: return actionable remediation data in error

### 5. Security gate feedback loop
- [ ] If `SecurityGate` fails and loops back to `WriteCode`:
  - Load security report findings (high/critical items)
  - Include in prompt: "Fix these security issues: {findings}"
  - Generate patched code snapshot as new version

### 6. Artifact creation
- [ ] Create `ProjectArtifact`:
  - artifact_type = `code_snapshot`
  - version = next version
  - content = CodeSnapshotContent JSON
  - model_profile = `customtools`

## Definition of Done
- [ ] Code snapshot contains a buildable set of files
- [ ] Files match the tech plan's folder structure and API routes
- [ ] Validation catches basic syntax/import errors
- [ ] Security remediation loop produces patched code
- [ ] Failures return actionable error messages
