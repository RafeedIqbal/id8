# Task 05: PRD Generation (IngestPrompt + GeneratePRD Nodes)

## Goal
Implement the first two orchestrator nodes: `IngestPrompt` parses the user's prompt, and `GeneratePRD` calls the LLM to produce a structured PRD artifact.

## Dependencies
- Task 03 (orchestrator — node handler interface)
- Task 04 (LLM router — `generate()` with `primary` profile)

## Source of Truth
- `orchestration/state-machine.md` — nodes 1-2
- `PRD.MD` §5.1 — Module 1 requirements

## Steps

### 1. IngestPrompt handler
- [ ] `backend/app/orchestrator/handlers/ingest_prompt.py`
- [ ] Load `project.initial_prompt` and `project.constraints` (from CreateProjectRequest)
- [ ] Validate prompt is non-empty and within token limits
- [ ] Package as `prd_generation_payload` in run context
- [ ] Update project status to `prd_draft`
- [ ] Return `NodeResult(outcome="success")`

### 2. GeneratePRD handler
- [ ] `backend/app/orchestrator/handlers/generate_prd.py`
- [ ] Build prompt from template:
  - System prompt: "You are a product manager. Generate a structured PRD..."
  - User prompt: initial_prompt + constraints
  - Output format: JSON with sections (executive_summary, user_stories, scope_boundaries, entity_list, non_goals)
- [ ] Call LLM router with `primary` profile
- [ ] Parse LLM response into structured PRD JSON
- [ ] If this is a re-generation (after rejection): include rejection feedback in prompt
  - Load latest `approval_events` where stage=prd, decision=rejected
  - Append rejection notes to prompt context
- [ ] Create `ProjectArtifact`:
  - artifact_type = `prd`
  - version = latest version + 1 (or 1 if first)
  - content = parsed PRD JSON
  - model_profile = profile used
- [ ] Return `NodeResult(outcome="success")`

### 3. PRD output schema
- [ ] Define expected PRD structure in `backend/app/schemas/prd.py`:
  ```python
  class PrdContent(BaseModel):
      executive_summary: str
      user_stories: list[UserStory]
      scope_boundaries: ScopeBoundaries
      entity_list: list[Entity]
      non_goals: list[str]
  ```
- [ ] Validate LLM output against this schema
- [ ] On validation failure: retry with more explicit formatting instructions

### 4. Rejection feedback loop
- [ ] When `WaitPRDApproval` returns `rejected`, orchestrator loops to `GeneratePRD`
- [ ] `GeneratePRD` loads previous PRD artifact + rejection notes
- [ ] Prompt includes: "The previous PRD was rejected. Feedback: {notes}. Previous PRD: {content}. Please revise."

## Definition of Done
- [ ] Creating a project and starting a run produces a `prd` artifact with all required sections
- [ ] PRD artifact is valid JSON matching the expected schema
- [ ] Rejecting the PRD and re-running produces a new version that addresses the feedback
- [ ] Token usage is recorded on the artifact
- [ ] Test with mocked LLM verifies prompt includes rejection feedback on v2+
