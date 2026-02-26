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
- [x] `frontend/src/lib/api.ts`
- [x] Typed client matching all API endpoints in `contracts/openapi.yaml`
- [x] Include project/run visibility endpoints:
  - `GET /v1/projects`
  - `GET /v1/projects/{projectId}/runs/latest`
  - `GET /v1/design/tools`
- [x] Use `fetch` or lightweight HTTP client
- [x] Handle auth headers, error responses
- [x] React Query hooks for data fetching:
  - `useProjects()`, `useProject(id)`, `useLatestRun(id)`, `useArtifacts(projectId)`, `useCreateProject()`, etc.

### 2. App layout and routing
- [x] `frontend/src/app/layout.tsx` — shell with sidebar navigation
- [x] Routes:
  - `/` — dashboard / project list
  - `/projects/new` — prompt intake form
  - `/projects/[id]` — project detail with status timeline
  - `/projects/[id]/artifacts/[type]` — artifact viewer (PRD, design, tech plan, code, security, deploy)
  - `/projects/[id]/approve/[stage]` — approval gate UI

### 3. Dashboard page
- [x] List all projects with status badges
- [x] Show current node for active runs
- [x] Quick-action: create new project

### 4. Prompt intake page (`/projects/new`)
- [x] Multi-paragraph text input for initial prompt
- [x] Optional constraints field (key-value or JSON)
- [x] Submit → `POST /v1/projects` → redirect to project detail

### 5. Project detail page (`/projects/[id]`)
- [x] **Status timeline**: visual pipeline showing all 14 nodes
  - Highlight current node, completed nodes, failed nodes
  - Show timestamps for each transition
  - Data source must come from `GET /v1/projects/{id}/runs/latest.timeline`
- [x] **Run controls**:
  - Start run button → `POST /v1/projects/{id}/runs`
  - Resume from failure button (if status is failed)
- [x] **Artifact list**: cards for each artifact type with version info
- [x] **Retry/failure display**: show error messages, retry counts

### 6. Artifact viewer pages
- [x] **PRD viewer**: render PRD JSON as formatted document (sections, user stories, entities)
- [x] **Design viewer**: render design spec (screen list, component details, images if available)
- [x] **Tech plan viewer**: render folder tree, API routes table, component hierarchy
- [x] **Code viewer**: file tree with syntax-highlighted code display
- [x] **Security report viewer**: findings table with severity badges, file/line links
- [x] **Deploy report viewer**: deployment URLs, provider details, status

### 7. Approval gate pages (`/projects/[id]/approve/[stage]`)
- [x] Show the artifact being reviewed (latest version for that stage)
- [x] Approve / Reject buttons
- [x] Notes text field (required on reject, optional on approve)
- [x] Submit → `POST /v1/projects/{id}/approvals`
- [x] On submit: show confirmation, redirect to project detail

### 8. Design feedback UI
- [x] On design approval page: additional "Request Changes" flow
- [x] Target specific screen or component (dropdowns populated from design artifact)
- [x] Feedback text input
- [x] Submit → `POST /v1/projects/{id}/design/feedback`
- [x] Show new version when regeneration completes

### 9. Stitch credential onboarding + tool visibility
- [x] When provider is `stitch_mcp`, require explicit auth setup before generation:
  - API key mode (recommended): prompt user to create token in Stitch Settings -> API Keys -> Create API Key
  - OAuth mode: collect access token + project ID for `Authorization` + `X-Goog-User-Project`
- [x] If backend returns "credentials required", render inline CTA with setup instructions and retry action
- [x] Include `stitch_auth` payload support on:
  - `POST /v1/projects/{id}/design/generate`
  - `POST /v1/projects/{id}/design/feedback`
- [x] Never store secrets in localStorage or URL/query params
- [x] Show a read-only "Usable Stitch Tools" panel sourced from `GET /v1/design/tools` (fallback to artifact metadata when present):
  - `create_project(name)`
  - `list_projects(filter)`
  - `list_screens(project_id)`
  - `get_project(name)`
  - `get_screen(project_id, screen_id)`
  - `generate_screen_from_text(project_id, prompt, model_id)`

### 10. Model usage and cost display
- [x] On project detail: summary card showing:
  - Total tokens used (prompt + completion)
  - Model profiles used per node
  - Estimated cost

### 11. Real-time updates (stretch)
- [x] Poll project status every 5s while a run is active
- [x] Update status timeline, show new artifacts as they appear
- [x] Show "Processing..." state for active nodes

## Design Requirements (Mandatory)

### A. Information Architecture
- [x] Global shell: persistent left sidebar + top bar + content area.
- [x] Sidebar nav items:
  - Dashboard (`/`)
  - New Project (`/projects/new`)
  - Project sections when inside project context: Overview, Artifacts, Approvals.
- [x] Breadcrumbs on project routes:
  - `Projects / {projectId}`
  - `Projects / {projectId} / Artifacts / {type}`
  - `Projects / {projectId} / Approve / {stage}`

### B. Layout Rules
- [x] Desktop breakpoints (`>=1024px`):
  - Sidebar fixed width `240-280px`
  - Main content max width `1280px`
  - Project detail uses 2-column split (`timeline 40%`, `operations 60%`)
- [x] Tablet/mobile (`<1024px`):
  - Sidebar collapses to drawer
  - Timeline and panels stack vertically
  - Action buttons become full-width
- [x] Preserve comfortable density:
  - Base spacing scale of 8px
  - Minimum touch target size 40px

### C. Core Component Contracts
- [x] `ProjectStatusBadge(status)` maps all `ProjectStatus` enum values to consistent colors/labels.
- [x] `NodeTimeline(nodes, currentNode, timelineEvents)` renders:
  - all 14 canonical nodes
  - completed/current/pending/failed states
  - transition timestamps per node when available
- [x] `ArtifactCard(type, version, createdAt, modelProfile)` used on detail + artifact index.
- [x] `ApprovalDecisionPanel(stage)` enforces:
  - reject requires notes
  - approve notes optional
- [x] `StitchAuthPanel` supports:
  - API key mode
  - OAuth token + `goog_user_project` mode
  - no secret persistence in browser storage

### D. Artifact Viewer Layout Specs
- [x] Shared viewer frame:
  - Header: artifact type, version picker, created timestamp, model profile
  - Left rail: versions list
  - Main pane: type-specific renderer
- [x] PRD renderer sections:
  - executive summary
  - user stories (persona/action/benefit)
  - scope boundaries (in/out)
  - entities
  - non-goals
- [x] Tech plan renderer sections:
  - folder tree
  - database schema
  - API routes table
  - component hierarchy
  - dependencies
  - deployment config
- [x] Design renderer:
  - screen list
  - selected screen details
  - component property table
  - asset previews/links
  - provider metadata panel
- [x] Code renderer:
  - file tree + syntax-highlighted source panel
  - build/test command summary
- [x] Security renderer:
  - summary badges (critical/high/medium/low/total)
  - findings table with severity, rule, file, line, remediation, resolved
- [x] Deploy renderer:
  - status
  - environment
  - deployment URL
  - provider payload JSON panel

### E. State and Feedback UX
- [x] Every async action has pending/success/error states.
- [x] Error banners show backend `error.message` when present.
- [x] Empty states:
  - no projects
  - no runs for project
  - no artifacts for type
  - no timeline events (show synthetic run start state)

### F. Accessibility and Quality
- [x] Keyboard navigable sidebar, tabs, and version lists.
- [x] Proper heading hierarchy (`h1` per page, `h2` for major panels).
- [x] Color contrast meets WCAG AA.
- [x] Loading skeletons instead of layout shifts for primary panels.

## Definition of Done
- [x] Operator can create a project, view artifacts, approve/reject at each gate
- [x] Status timeline accurately reflects run progression
- [x] Design feedback creates new artifact versions visible in UI
- [x] Stitch generation flow prompts for API key creation when credentials are missing
- [x] Usable Stitch tool inventory is visible during design workflows
- [x] Security report is displayed with severity badges
- [x] Deployed URL is shown after successful deployment
- [x] All API calls use typed client matching OpenAPI contract
