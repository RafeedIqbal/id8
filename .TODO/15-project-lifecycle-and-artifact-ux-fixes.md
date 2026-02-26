# Task 15: Project Lifecycle + Artifact UX Fixes

## Goal
Add missing lifecycle controls and clean up artifact UX so operators can safely replay flows, navigate artifacts, restart projects, and fix broken viewers.

## Dependencies
- Task 02 (API routes skeleton)
- Task 03 (orchestrator state machine)
- Task 06 (design engine metadata for Stitch links)
- Task 10 (GitHub integration)
- Task 11 (deployment pipeline)
- Task 12 (frontend operator console)

## Source of Truth
- User-requested feature/fix backlog (2026-02-26)
- `PRD.MD` §5.7 — operator visibility and control
- `contracts/openapi.yaml` — API contract updates required

## Steps

### 1. Timeline go-back/retry from any step
- [ ] Extend run controls API to support replay from any canonical node, not only failure resume.
- [ ] Define replay modes:
  - `retry_failed` (same node after failure)
  - `replay_from_node` (go back and regenerate downstream)
- [ ] Enforce backend guardrails:
  - node must exist in canonical workflow
  - terminal-state runs require explicit replay mode
  - invalid transitions return clear 4xx errors
- [ ] UI timeline node actions:
  - Retry from this step
  - Replay from this step
  - Disabled state + reason tooltip when not allowed
- [ ] Record audit events for operator-triggered replay actions.

### 2. Artifacts tab becomes a left-nav dropdown
- [ ] Replace single "Artifacts" link in project sidebar with a collapsible group.
- [ ] Add sub-tabs in left nav:
  - PRD
  - Screens (with Stitch project link when available)
  - Tech Plan
  - Code Base (with GitHub repo link when created)
  - Vercel Site (when deployed)
  - Supabase Dashboard (when deployed)
- [ ] For external links, show empty-state placeholders when unavailable rather than broken links.
- [ ] Ensure keyboard navigation and mobile drawer behavior still work for nested nav items.

### 3. Delete projects
- [ ] Add `DELETE /v1/projects/{projectId}` with soft-delete semantics and audit trail.
- [ ] Define active-run delete behavior (block or cancel first) with explicit user-facing error text.
- [ ] Add frontend danger-zone action with typed confirmation.
- [ ] Exclude deleted projects from default list API response (optionally add `include_deleted=true` for admins).
- [ ] Add route + UI tests for successful and blocked deletes.

### 4. Change initial prompt/stack JSON and restart from step one
- [ ] Add project update endpoint for editable setup fields (`initial_prompt`, `stack_json`).
- [ ] Add restart endpoint/action that creates a fresh run from `IngestPrompt` ("step one").
- [ ] Preserve existing run/artifact history; new run becomes active context.
- [ ] Add UI settings panel to edit prompt/stack and trigger restart with confirmation.
- [ ] Add validation and conflict handling for restart while another run is active.

### 5. Suggested stack by default + hostability constraints
- [ ] Define a typed `stack_json` schema shared between frontend and backend.
- [ ] Pre-populate project setup with a suggested stack by default.
- [ ] Enforce server-side validation so only Vercel/Supabase-hostable stacks are accepted.
- [ ] Mirror validation client-side for immediate UX feedback.
- [ ] Add compatibility tests for accepted/rejected stack combinations.

### 6. Fix artifact screens (broken views)
- [ ] Audit all artifact viewer routes for runtime errors, missing-field crashes, and bad rendering.
- [ ] Fix renderers for:
  - PRD
  - Screens
  - Tech Plan
  - Code Base
  - Security report
  - Deploy report
- [ ] Add artifact parser/adapters with strict type guards and fallback rendering.
- [ ] Add regression tests per artifact viewer route with representative payload fixtures.
- [ ] Add a resilient fallback view (including raw JSON inspector) for unknown artifact versions.

## Definition of Done
- [ ] Operator can replay/retry from any timeline step with clear guardrails.
- [ ] Left sidebar exposes the full artifact dropdown and conditional external links.
- [ ] Project deletion works end-to-end with confirmation and audit logs.
- [ ] Operator can edit prompt/stack JSON and restart from step one.
- [ ] New projects default to suggested stack JSON and reject non-Vercel/Supabase-hostable stacks.
- [ ] All artifact viewer types render without known breakages.
