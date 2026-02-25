# Task 02: FastAPI Routes Skeleton

## Goal
Implement all 8 API endpoints from `contracts/openapi.yaml` as FastAPI routes. Initially return stubs that do DB reads/writes but delegate orchestration logic to later tasks.

## Dependencies
- Task 01 (database & models)

## Steps

### 1. Create router modules
- [x] `backend/app/routes/__init__.py`
- [x] `backend/app/routes/projects.py` — project CRUD
- [x] `backend/app/routes/runs.py` — run management
- [x] `backend/app/routes/design.py` — design generation + feedback
- [x] `backend/app/routes/approvals.py` — approval submission
- [x] `backend/app/routes/artifacts.py` — artifact listing
- [x] `backend/app/routes/deploy.py` — deploy trigger

### 2. Implement endpoints (stub logic, real DB)

#### `POST /v1/projects` — `createProject`
- [x] Accept `CreateProjectRequest` (initial_prompt, optional constraints)
- [x] Create `Project` row with status=`ideation`
- [x] Return `ProjectResponse` (201)

#### `GET /v1/projects/{projectId}` — `getProject`
- [x] Lookup by UUID, 404 if missing
- [x] Return `ProjectResponse`

#### `POST /v1/projects/{projectId}/runs` — `createRun`
- [x] Accept optional `CreateRunRequest` (resume_from_node, model_profile)
- [x] Check `Idempotency-Key` header — return existing run if duplicate
- [x] Create `ProjectRun` row, set current_node to `IngestPrompt` (or resume node)
- [x] Kick off orchestrator (stub: just return 202 with run data)
- [x] Return `ProjectRunResponse` (202)

#### `POST /v1/projects/{projectId}/design/generate` — `generateDesign`
- [x] Validate project is in `design_draft` or `prd_approved` status
- [x] Accept `DesignGenerateRequest` (provider, model_profile, prompt_constraints)
- [x] Queue design generation job (stub: return 202)
- [x] Return `ArtifactResponse`

#### `POST /v1/projects/{projectId}/design/feedback` — `submitDesignFeedback`
- [x] Validate project is in `design_draft` status
- [x] Accept `DesignFeedbackRequest` (target_screen_id, target_component_id, feedback_text)
- [x] Queue regeneration job (stub: return 202)
- [x] Return `ArtifactResponse`

#### `POST /v1/projects/{projectId}/approvals` — `submitApproval`
- [x] Accept `ApprovalRequest` (stage, decision, optional notes)
- [x] Validate stage matches current project status (e.g. `prd` stage only valid when status=`prd_draft`)
- [x] Create `ApprovalEvent` row
- [x] Transition project status based on decision (approved → next status, rejected → keep at current)
- [x] Return `ApprovalEventResponse` (200)

#### `GET /v1/projects/{projectId}/artifacts` — `listArtifacts`
- [x] Return all artifacts for project, ordered by type then version desc
- [x] Return `ArtifactListResponse`

#### `POST /v1/projects/{projectId}/deploy` — `deployProject`
- [x] Validate `deploy` approval exists for this project
- [x] Validate project status is `deploy_ready`
- [x] Queue deploy job (stub: return 202)
- [x] Return `DeploymentRecordResponse`

### 3. Wire routers into app
- [x] Register all routers in `backend/app/main.py` under `/v1` prefix
- [x] Add CORS middleware (allow frontend origin)
- [x] Add request ID middleware

### 4. Idempotency key handling
- [x] Create reusable dependency/middleware for `Idempotency-Key` header
- [x] On duplicate key: return cached response, do not re-execute
- [x] Store idempotency key → response mapping in `project_runs.idempotency_key`

### 5. Error handling
- [x] Global exception handlers for 400, 404, 409, 422, 500
- [x] Consistent error response shape: `{ "error": { "code": "...", "message": "..." } }`

## Definition of Done
- [x] All 8 endpoints respond with correct HTTP status codes
- [x] OpenAPI docs at `/docs` match `contracts/openapi.yaml` schema names
- [x] Idempotency key returns same response for duplicate `createRun` calls
- [x] Invalid state transitions return 409 Conflict
- [x] Pytest tests cover each endpoint's happy path and one error case
