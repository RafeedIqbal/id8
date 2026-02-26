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
- [ ] Typed client matching all API endpoints in `contracts/openapi.yaml`
- [ ] Include project/run visibility endpoints:
  - `GET /v1/projects`
  - `GET /v1/projects/{projectId}/runs/latest`
  - `GET /v1/design/tools`
- [ ] Use `fetch` or lightweight HTTP client
- [ ] Handle auth headers, error responses
- [ ] React Query hooks for data fetching:
  - `useProjects()`, `useProject(id)`, `useLatestRun(id)`, `useArtifacts(projectId)`, `useCreateProject()`, etc.

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
  - Data source must come from `GET /v1/projects/{id}/runs/latest.timeline`
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
- [ ] Include `stitch_auth` payload support on:
  - `POST /v1/projects/{id}/design/generate`
  - `POST /v1/projects/{id}/design/feedback`
- [ ] Never store secrets in localStorage or URL/query params
- [ ] Show a read-only "Usable Stitch Tools" panel sourced from `GET /v1/design/tools` (fallback to artifact metadata when present):
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

## Design Requirements (Mandatory)

### A. Information Architecture
- [ ] Global shell: persistent left sidebar + top bar + content area.
- [ ] Sidebar nav items:
  - Dashboard (`/`)
  - New Project (`/projects/new`)
  - Project sections when inside project context: Overview, Artifacts, Approvals.
- [ ] Breadcrumbs on project routes:
  - `Projects / {projectId}`
  - `Projects / {projectId} / Artifacts / {type}`
  - `Projects / {projectId} / Approve / {stage}`

### B. Layout Rules
- [ ] Desktop breakpoints (`>=1024px`):
  - Sidebar fixed width `240-280px`
  - Main content max width `1280px`
  - Project detail uses 2-column split (`timeline 40%`, `operations 60%`)
- [ ] Tablet/mobile (`<1024px`):
  - Sidebar collapses to drawer
  - Timeline and panels stack vertically
  - Action buttons become full-width
- [ ] Preserve comfortable density:
  - Base spacing scale of 8px
  - Minimum touch target size 40px

### C. Core Component Contracts
- [ ] `ProjectStatusBadge(status)` maps all `ProjectStatus` enum values to consistent colors/labels.
- [ ] `NodeTimeline(nodes, currentNode, timelineEvents)` renders:
  - all 14 canonical nodes
  - completed/current/pending/failed states
  - transition timestamps per node when available
- [ ] `ArtifactCard(type, version, createdAt, modelProfile)` used on detail + artifact index.
- [ ] `ApprovalDecisionPanel(stage)` enforces:
  - reject requires notes
  - approve notes optional
- [ ] `StitchAuthPanel` supports:
  - API key mode
  - OAuth token + `goog_user_project` mode
  - no secret persistence in browser storage

### D. Artifact Viewer Layout Specs
- [ ] Shared viewer frame:
  - Header: artifact type, version picker, created timestamp, model profile
  - Left rail: versions list
  - Main pane: type-specific renderer
- [ ] PRD renderer sections:
  - executive summary
  - user stories (persona/action/benefit)
  - scope boundaries (in/out)
  - entities
  - non-goals
- [ ] Tech plan renderer sections:
  - folder tree
  - database schema
  - API routes table
  - component hierarchy
  - dependencies
  - deployment config
- [ ] Design renderer:
  - screen list
  - selected screen details
  - component property table
  - asset previews/links
  - provider metadata panel
- [ ] Code renderer:
  - file tree + syntax-highlighted source panel
  - build/test command summary
- [ ] Security renderer:
  - summary badges (critical/high/medium/low/total)
  - findings table with severity, rule, file, line, remediation, resolved
- [ ] Deploy renderer:
  - status
  - environment
  - deployment URL
  - provider payload JSON panel

### E. State and Feedback UX
- [ ] Every async action has pending/success/error states.
- [ ] Error banners show backend `error.message` when present.
- [ ] Empty states:
  - no projects
  - no runs for project
  - no artifacts for type
  - no timeline events (show synthetic run start state)

### F. Accessibility and Quality
- [ ] Keyboard navigable sidebar, tabs, and version lists.
- [ ] Proper heading hierarchy (`h1` per page, `h2` for major panels).
- [ ] Color contrast meets WCAG AA.
- [ ] Loading skeletons instead of layout shifts for primary panels.

## Definition of Done
- [ ] Operator can create a project, view artifacts, approve/reject at each gate
- [ ] Status timeline accurately reflects run progression
- [ ] Design feedback creates new artifact versions visible in UI
- [ ] Stitch generation flow prompts for API key creation when credentials are missing
- [ ] Usable Stitch tool inventory is visible during design workflows
- [ ] Security report is displayed with severity badges
- [ ] Deployed URL is shown after successful deployment
- [ ] All API calls use typed client matching OpenAPI contract
