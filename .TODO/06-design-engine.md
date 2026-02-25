# Task 06: Design Engine (GenerateDesign + Stitch MCP + Feedback)

## Goal
Implement the design generation pipeline: Stitch MCP as first-class provider, `internal_spec` fallback, and iterative feedback loop with versioned artifacts.

## Dependencies
- Task 03 (orchestrator)
- Task 04 (LLM router — for `internal_spec` fallback)

## Source of Truth
- `orchestration/state-machine.md` — nodes 4-5
- `PRD.MD` §5.2 — Module 2: Design Engine
- `TECH-PLAN.MD` §6 — MCP Strategy

## Steps

### 1. Provider adapter interface
- [ ] `backend/app/design/base.py`
  ```python
  class DesignProvider(ABC):
      async def generate(self, prd_content: dict, constraints: dict) -> DesignOutput
      async def regenerate(self, previous: DesignOutput, feedback: DesignFeedback) -> DesignOutput
  ```
  - `DesignOutput`: screens (list of screen objects with id, name, components, assets)
  - `DesignFeedback`: target_screen_id, target_component_id, feedback_text

### 2. Stitch MCP adapter (primary)
- [ ] `backend/app/design/stitch_mcp.py`
- [ ] Connect to Stitch MCP endpoint from config (`STITCH_MCP_ENDPOINT`)
- [ ] Translate approved PRD into Stitch-compatible design prompt constraints
- [ ] Send generation request, parse response into `DesignOutput`
- [ ] For feedback/regeneration: send targeted regeneration request with screen/component IDs
- [ ] Handle Stitch-specific errors (timeout, rate limit, service unavailable)

### 3. Internal spec adapter (fallback)
- [ ] `backend/app/design/internal_spec.py`
- [ ] Use LLM router (`customtools` profile) to generate design spec as structured JSON
- [ ] Prompt: "Given this PRD, produce a screen-by-screen design specification..."
- [ ] Output: same `DesignOutput` format but text-based spec instead of visual assets
- [ ] Supports the same feedback/regeneration interface

### 4. Provider selection and fallback
- [ ] `backend/app/design/provider_factory.py`
- [ ] Default order: `stitch_mcp` → `internal_spec`
- [ ] On Stitch failure:
  1. Log warning audit event with error details
  2. Automatically switch to `internal_spec`
  3. Continue run without manual intervention
- [ ] Provider used is recorded in artifact metadata

### 5. GenerateDesign handler
- [ ] `backend/app/orchestrator/handlers/generate_design.py`
- [ ] Load approved PRD artifact (latest version where approval exists)
- [ ] Get design provider (from request or default `stitch_mcp`)
- [ ] Call provider.generate()
- [ ] Create `ProjectArtifact`:
  - artifact_type = `design_spec`
  - version = next version
  - content = DesignOutput JSON + metadata (provider used, generation time)
- [ ] Update project status to `design_draft`
- [ ] If re-generation after rejection: call provider.regenerate() with feedback

### 6. Design feedback endpoint implementation
- [ ] In `POST /v1/projects/{projectId}/design/feedback`:
  - Load current design artifact
  - Call provider.regenerate() with targeted feedback
  - Create new artifact version
  - Link feedback text in artifact metadata
- [ ] Maintain version history — previous versions remain accessible via `GET /artifacts`

### 7. WaitDesignApproval handler update
- [ ] On rejection: store feedback in approval_events.notes
- [ ] On re-entry to GenerateDesign: load feedback from latest rejection event

## Definition of Done
- [ ] Design generation via Stitch MCP produces a `design_spec` artifact
- [ ] Stitch outage automatically falls back to `internal_spec` with audit log
- [ ] Design feedback creates new version with incremented version number
- [ ] Previous design versions are preserved and listable
- [ ] Feedback note is linked in artifact metadata
- [ ] Matches acceptance test scenario #2 (Stitch iteration loop) and #3 (Stitch outage fallback)
