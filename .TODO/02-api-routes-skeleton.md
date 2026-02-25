# Task 02: FastAPI Routes Skeleton

## Goal
Implement all 8 API endpoints from `contracts/openapi.yaml` as FastAPI routes. Initially return stubs that do DB reads/writes but delegate orchestration logic to later tasks.

## Dependencies
- Task 01 (database & models)

## Steps

### 1. Create router modules
- [ ] `backend/app/routes/__init__.py`
- [ ] `backend/app/routes/projects.py` — project CRUD
- [ ] `backend/app/routes/runs.py` — run management
- [ ] `backend/app/routes/design.py` — design generation + feedback
- [ ] `backend/app/routes/approvals.py` — approval submission
- [ ] `backend/app/routes/artifacts.py` — artifact listing
- [ ] `backend/app/routes/deploy.py` — deploy trigger

### 2. Implement endpoints (stub logic, real DB)

#### `POST /v1/projects` — `createProject`
- [ ] Accept `CreateProjectRequest` (initial_prompt, optional constraints)
- [ ] Create `Project` row with status=`ideation`
- [ ] Return `ProjectResponse` (201)

#### `GET /v1/projects/{projectId}` — `getProject`
- [ ] Lookup by UUID, 404 if missing
- [ ] Return `ProjectResponse`

#### `POST /v1/projects/{projectId}/runs` — `createRun`
- [ ] Accept optional `CreateRunRequest` (resume_from_node, model_profile)
- [ ] Check `Idempotency-Key` header — return existing run if duplicate
- [ ] Create `ProjectRun` row, set current_node to `IngestPrompt` (or resume node)
- [ ] Kick off orchestrator (stub: just return 202 with run data)
- [ ] Return `ProjectRunResponse` (202)

#### `POST /v1/projects/{projectId}/design/generate` — `generateDesign`
- [ ] Validate project is in `design_draft` or `prd_approved` status
- [ ] Accept `DesignGenerateRequest` (provider, model_profile, prompt_constraints)
- [ ] Queue design generation job (stub: return 202)
- [ ] Return `ArtifactResponse`

#### `POST /v1/projects/{projectId}/design/feedback` — `submitDesignFeedback`
- [ ] Validate project is in `design_draft` status
- [ ] Accept `DesignFeedbackRequest` (target_screen_id, target_component_id, feedback_text)
- [ ] Queue regeneration job (stub: return 202)
- [ ] Return `ArtifactResponse`

#### `POST /v1/projects/{projectId}/approvals` — `submitApproval`
- [ ] Accept `ApprovalRequest` (stage, decision, optional notes)
- [ ] Validate stage matches current project status (e.g. `prd` stage only valid when status=`prd_draft`)
- [ ] Create `ApprovalEvent` row
- [ ] Transition project status based on decision (approved → next status, rejected → keep at current)
- [ ] Return `ApprovalEventResponse` (200)

#### `GET /v1/projects/{projectId}/artifacts` — `listArtifacts`
- [ ] Return all artifacts for project, ordered by type then version desc
- [ ] Return `ArtifactListResponse`

#### `POST /v1/projects/{projectId}/deploy` — `deployProject`
- [ ] Validate `deploy` approval exists for this project
- [ ] Validate project status is `deploy_ready`
- [ ] Queue deploy job (stub: return 202)
- [ ] Return `DeploymentRecordResponse`

### 3. Wire routers into app
- [ ] Register all routers in `backend/app/main.py` under `/v1` prefix
- [ ] Add CORS middleware (allow frontend origin)
- [ ] Add request ID middleware

### 4. Idempotency key handling
- [ ] Create reusable dependency/middleware for `Idempotency-Key` header
- [ ] On duplicate key: return cached response, do not re-execute
- [ ] Store idempotency key → response mapping in `project_runs.idempotency_key`

### 5. Error handling
- [ ] Global exception handlers for 400, 404, 409, 422, 500
- [ ] Consistent error response shape: `{ "error": { "code": "...", "message": "..." } }`

## Definition of Done
- [ ] All 8 endpoints respond with correct HTTP status codes
- [ ] OpenAPI docs at `/docs` match `contracts/openapi.yaml` schema names
- [ ] Idempotency key returns same response for duplicate `createRun` calls
- [ ] Invalid state transitions return 409 Conflict
- [ ] Pytest tests cover each endpoint's happy path and one error case
