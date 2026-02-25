# Task 07: Tech Plan Generation (GenerateTechPlan Node)

## Goal
Implement the `GenerateTechPlan` orchestrator node that produces a technical plan from approved PRD and design artifacts.

## Dependencies
- Task 04 (LLM router)
- Task 05 (PRD generation — produces input artifacts)
- Task 06 (Design engine — produces input artifacts)

## Source of Truth
- `orchestration/state-machine.md` — node 6
- `PRD.MD` §5.3 — Module 3: Planning

## Steps

### 1. GenerateTechPlan handler
- [x] `backend/app/orchestrator/handlers/generate_tech_plan.py`
- [x] Load latest approved PRD artifact and latest approved design artifact
- [x] Build prompt using `primary` model profile:
  - System prompt: "You are a senior software architect. Generate a technical implementation plan..."
  - Include: PRD content, design spec content
  - Output format: JSON with required sections
- [x] Call LLM router
- [x] Parse and validate response

### 2. Tech plan output schema
- [x] `backend/app/schemas/tech_plan.py`:
  ```python
  class TechPlanContent(BaseModel):
      folder_structure: dict          # directory tree
      database_schema: dict           # tables, columns, relationships
      api_routes: list[ApiRoute]      # method, path, description
      component_hierarchy: dict       # frontend component tree
      dependencies: list[Dependency]  # packages with versions
      deployment_config: dict         # infrastructure requirements
  ```

### 3. Rejection feedback loop
- [x] On rejection from `WaitTechPlanApproval`:
  - [x] Load previous tech plan artifact + rejection notes
  - [x] Include in re-generation prompt: "Previous plan was rejected. Feedback: {notes}"
  - [x] Produce new artifact version

### 4. Update project status
- [x] On success: status → `tech_plan_draft`
- [x] After approval: status → `tech_plan_approved`

## Definition of Done
- [x] Tech plan artifact contains all required sections (folder structure, DB schema, API routes, component hierarchy)
- [x] Artifact references both the PRD and design artifacts it was built from
- [x] Rejection loop produces revised plan addressing feedback
- [x] Token usage and model profile recorded
