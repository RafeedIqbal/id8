# Task 12: Frontend — Operator Console (Next.js)

## Goal
Build the Next.js operator console for prompt intake, artifact review, approval gates, and run monitoring.

## Dependencies
- Task 02 (API routes — frontend calls these)
- Task 00 (frontend scaffolding)

## Source of Truth
- `PRD.MD` §5.7 — Module 7: Operator Visibility
- `contracts/openapi.yaml` — API contract
- `contracts/domain-types.ts` — shared types

## Steps

### 1. API client layer
- [ ] `frontend/src/lib/api.ts`
- [ ] Typed client matching all 8 API endpoints
- [ ] Use `fetch` or lightweight HTTP client
- [ ] Handle auth headers, error responses
- [ ] React Query hooks for data fetching:
  - `useProject(id)`, `useArtifacts(projectId)`, `useCreateProject()`, etc.

### 2. App layout and routing
- [ ] `frontend/src/app/layout.tsx` — shell with sidebar navigation
- [ ] Routes:
  - `/` — dashboard / project list
  - `/projects/new` — prompt intake form
  - `/projects/[id]` — project detail with status timeline
  - `/projects/[id]/artifacts/[type]` — artifact viewer (PRD, design, tech plan, code, security, deploy)
  - `/projects/[id]/approve/[stage]` — approval gate UI

### 3. Dashboard page
- [ ] List all projects with status badges
- [ ] Show current node for active runs
- [ ] Quick-action: create new project

### 4. Prompt intake page (`/projects/new`)
- [ ] Multi-paragraph text input for initial prompt
- [ ] Optional constraints field (key-value or JSON)
- [ ] Submit → `POST /v1/projects` → redirect to project detail

### 5. Project detail page (`/projects/[id]`)
- [ ] **Status timeline**: visual pipeline showing all 14 nodes
  - Highlight current node, completed nodes, failed nodes
  - Show timestamps for each transition
- [ ] **Run controls**:
  - Start run button → `POST /v1/projects/{id}/runs`
  - Resume from failure button (if status is failed)
- [ ] **Artifact list**: cards for each artifact type with version info
- [ ] **Retry/failure display**: show error messages, retry counts

### 6. Artifact viewer pages
- [ ] **PRD viewer**: render PRD JSON as formatted document (sections, user stories, entities)
- [ ] **Design viewer**: render design spec (screen list, component details, images if available)
- [ ] **Tech plan viewer**: render folder tree, API routes table, component hierarchy
- [ ] **Code viewer**: file tree with syntax-highlighted code display
- [ ] **Security report viewer**: findings table with severity badges, file/line links
- [ ] **Deploy report viewer**: deployment URLs, provider details, status

### 7. Approval gate pages (`/projects/[id]/approve/[stage]`)
- [ ] Show the artifact being reviewed (latest version for that stage)
- [ ] Approve / Reject buttons
- [ ] Notes text field (required on reject, optional on approve)
- [ ] Submit → `POST /v1/projects/{id}/approvals`
- [ ] On submit: show confirmation, redirect to project detail

### 8. Design feedback UI
- [ ] On design approval page: additional "Request Changes" flow
- [ ] Target specific screen or component (dropdowns populated from design artifact)
- [ ] Feedback text input
- [ ] Submit → `POST /v1/projects/{id}/design/feedback`
- [ ] Show new version when regeneration completes

### 9. Stitch credential onboarding + tool visibility
- [ ] When provider is `stitch_mcp`, require explicit auth setup before generation:
  - API key mode (recommended): prompt user to create token in Stitch Settings -> API Keys -> Create API Key
  - OAuth mode: collect access token + project ID for `Authorization` + `X-Goog-User-Project`
- [ ] If backend returns "credentials required", render inline CTA with setup instructions and retry action
- [ ] Never store secrets in localStorage or URL/query params
- [ ] Show a read-only "Usable Stitch Tools" panel sourced from backend metadata:
  - `create_project(name)`
  - `list_projects(filter)`
  - `list_screens(project_id)`
  - `get_project(name)`
  - `get_screen(project_id, screen_id)`
  - `generate_screen_from_text(project_id, prompt, model_id)`

### 10. Model usage and cost display
- [ ] On project detail: summary card showing:
  - Total tokens used (prompt + completion)
  - Model profiles used per node
  - Estimated cost

### 11. Real-time updates (stretch)
- [ ] Poll project status every 5s while a run is active
- [ ] Update status timeline, show new artifacts as they appear
- [ ] Show "Processing..." state for active nodes

## Definition of Done
- [ ] Operator can create a project, view artifacts, approve/reject at each gate
- [ ] Status timeline accurately reflects run progression
- [ ] Design feedback creates new artifact versions visible in UI
- [ ] Stitch generation flow prompts for API key creation when credentials are missing
- [ ] Usable Stitch tool inventory is visible during design workflows
- [ ] Security report is displayed with severity badges
- [ ] Deployed URL is shown after successful deployment
- [ ] All API calls use typed client matching OpenAPI contract
