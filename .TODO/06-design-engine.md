# Task 06: Design Engine (GenerateDesign + Stitch MCP + Feedback)

## Goal
Implement design generation with Stitch MCP as the primary provider, `internal_spec` fallback, iterative feedback, and versioned artifacts, while handling Stitch's remote MCP authentication requirements (API key and OAuth token modes).

## Dependencies
- Task 03 (orchestrator)
- Task 04 (LLM router — for `internal_spec` fallback)
- Task 12 (frontend credential prompt UI for Stitch auth)

## Source of Truth
- `orchestration/state-machine.md` — nodes 4-5
- `PRD.MD` §5.2 — Module 2: Design Engine
- `TECH-PLAN.MD` §6 — MCP Strategy
- Stitch MCP setup docs: https://stitch.withgoogle.com/docs/mcp/setup?pli=1

## Steps

### 1. Provider adapter interface
- [ ] `backend/app/design/base.py`
  ```python
  class DesignProvider(ABC):
      async def generate(
          self,
          prd_content: dict,
          constraints: dict,
          auth: StitchAuthContext | None = None,
      ) -> DesignOutput

      async def regenerate(
          self,
          previous: DesignOutput,
          feedback: DesignFeedback,
          auth: StitchAuthContext | None = None,
      ) -> DesignOutput
  ```
  - `DesignOutput`: screens (list of screen objects with id, name, components, assets)
  - `DesignFeedback`: target_screen_id, target_component_id, feedback_text
  - `StitchAuthContext`: auth_method + required headers (never log raw secrets)

### 2. Stitch auth model and user prompt contract
- [ ] Add Stitch auth mode support:
  - `api_key` via `X-Goog-Api-Key`
  - `oauth_access_token` via `Authorization: Bearer <token>` and `X-Goog-User-Project`
- [ ] If provider is `stitch_mcp` and credentials are missing/invalid:
  - Return a typed error payload the frontend can render as an action prompt
  - Prompt copy must instruct the user to:
    1. open Stitch Settings
    2. go to API Keys
    3. click Create API Key
    4. paste token into ID8
  - Include fallback note for OAuth mode when key entry is not supported
- [ ] Ensure secrets are never persisted in artifact content, logs, or audit payloads (redact headers)

### 3. Stitch MCP adapter (primary)
- [ ] `backend/app/design/stitch_mcp.py`
- [ ] Use default endpoint `https://stitch.googleapis.com/mcp` (configurable via `STITCH_MCP_ENDPOINT`)
- [ ] Build request headers from selected auth mode
- [ ] Translate approved PRD into Stitch-compatible design prompt constraints
- [ ] Send generation request and parse response into `DesignOutput`
- [ ] For feedback/regeneration: send targeted regeneration request with screen/component IDs
- [ ] Handle Stitch-specific errors (timeout, rate limit, unauthenticated, service unavailable)

### 4. Usable Stitch tool registry
- [ ] Define canonical metadata for tools exposed by Stitch MCP:
  - `create_project(name)`
  - `list_projects(filter)`
  - `list_screens(project_id)`
  - `get_project(name)`
  - `get_screen(project_id, screen_id)`
  - `generate_screen_from_text(project_id, prompt, model_id)`
- [ ] Expose this tool inventory to the app/UI so operators can see what Stitch can execute
- [ ] Persist tool metadata in design artifact metadata (`usable_tools`) for traceability

### 5. Internal spec adapter (fallback)
- [ ] `backend/app/design/internal_spec.py`
- [ ] Use LLM router (`customtools` profile) to generate design spec as structured JSON
- [ ] Prompt: "Given this PRD, produce a screen-by-screen design specification..."
- [ ] Output: same `DesignOutput` format but text-based spec instead of visual assets
- [ ] Supports the same feedback/regeneration interface

### 6. Provider selection and fallback
- [ ] `backend/app/design/provider_factory.py`
- [ ] Default order: `stitch_mcp` -> `internal_spec`
- [ ] On Stitch runtime failure (non-auth setup errors):
  1. Log warning audit event with error details (redacted)
  2. Automatically switch to `internal_spec`
  3. Continue run without manual intervention
- [ ] Provider and auth mode used are recorded in artifact metadata

### 7. GenerateDesign handler
- [ ] `backend/app/orchestrator/handlers/generate_design.py`
- [ ] Load approved PRD artifact (latest version where approval exists)
- [ ] Get design provider (from request or default `stitch_mcp`)
- [ ] For Stitch provider, validate auth payload before generation
- [ ] Call provider.generate()
- [ ] Create `ProjectArtifact`:
  - artifact_type = `design_spec`
  - version = next version
  - content = `DesignOutput` JSON + metadata:
    - provider used
    - auth method used (no secret values)
    - mcp endpoint
    - usable tool list
    - generation time
- [ ] Update project status to `design_draft`
- [ ] If re-generation after rejection: call provider.regenerate() with feedback

### 8. Design feedback endpoint implementation
- [ ] In `POST /v1/projects/{projectId}/design/feedback`:
  - Load current design artifact
  - Call provider.regenerate() with targeted feedback
  - Create new artifact version
  - Link feedback text in artifact metadata
  - Preserve provider/auth/tool metadata for the new version
- [ ] Maintain version history — previous versions remain accessible via `GET /artifacts`

### 9. WaitDesignApproval handler update
- [ ] On rejection: store feedback in `approval_events.notes`
- [ ] On re-entry to GenerateDesign: load feedback from latest rejection event

## Definition of Done
- [ ] Design generation via Stitch MCP produces a `design_spec` artifact
- [ ] Missing Stitch credentials returns a user-actionable prompt (generate API key in Stitch settings)
- [ ] Stitch tool inventory is exposed in app/API and recorded in artifact metadata
- [ ] Stitch outage automatically falls back to `internal_spec` with audit log
- [ ] Design feedback creates new version with incremented version number
- [ ] Previous design versions are preserved and listable
- [ ] Feedback note is linked in artifact metadata
- [ ] Matches acceptance test scenario #2 (Stitch iteration loop) and #3 (Stitch outage fallback)
