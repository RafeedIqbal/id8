# Task 01: Database & SQLAlchemy Models

## Goal
Translate the canonical `db/schema.sql` into SQLAlchemy ORM models and Alembic migrations. Set up the database access layer.

## Dependencies
- Task 00 (project scaffolding)

## Steps

### 1. Define SQLAlchemy enums
- [ ] `backend/app/models/enums.py`
  - `DesignProviderEnum` — `stitch_mcp | internal_spec | manual_upload`
  - `ModelProfileEnum` — `primary | customtools | fallback`
  - `ProjectStatusEnum` — all 13 values from schema
  - `ArtifactTypeEnum` — `prd | design_spec | tech_plan | code_snapshot | security_report | deploy_report`
  - `ApprovalStageEnum` — `prd | design | tech_plan | deploy`

### 2. Define SQLAlchemy models
Each model maps 1:1 to `db/schema.sql`. File per model in `backend/app/models/`:

- [ ] `user.py` — `User` (id, email, role, timestamps)
- [ ] `project.py` — `Project` (id, owner_user_id FK→users, initial_prompt, status, github_repo_url, live_deployment_url, timestamps)
- [ ] `project_run.py` — `ProjectRun` (id, project_id FK→projects, status, current_node, idempotency_key unique, retry_count, error fields, timestamps)
- [ ] `project_artifact.py` — `ProjectArtifact` (id, project_id, run_id, artifact_type, version, content JSONB, model_profile, created_at; unique on project_id+artifact_type+version)
- [ ] `approval_event.py` — `ApprovalEvent` (id, project_id, run_id, stage, decision, notes, created_by FK→users, created_at)
- [ ] `provider_credential.py` — `ProviderCredential` (id, user_id, provider, encrypted_secret, secret_scope, last_rotated_at, timestamps; unique on user_id+provider+secret_scope)
- [ ] `deployment_record.py` — `DeploymentRecord` (id, project_id, run_id, environment check('production'), status, provider_payload JSONB, deployment_url, timestamps)
- [ ] `retry_job.py` — `RetryJob` (id, run_id, node_name, retry_attempt, scheduled_for, payload JSONB, created_at, processed_at)
- [ ] `audit_event.py` — `AuditEvent` (id, project_id nullable, actor_user_id nullable, event_type, event_payload JSONB, created_at)
- [ ] `__init__.py` — re-export all models

### 3. Create Alembic initial migration
- [ ] Auto-generate from models: `alembic revision --autogenerate -m "initial_schema"`
- [ ] Verify generated migration matches `db/schema.sql` exactly (indexes, constraints, enums)
- [ ] Ensure `pgcrypto` extension is enabled in migration

### 4. Database session/connection layer
- [ ] `backend/app/db.py` — async engine, session factory, `get_db` dependency
- [ ] Use `asyncpg` driver with `create_async_engine`
- [ ] Configure connection pooling (pool_size=5, max_overflow=10 for MVP)

### 5. Pydantic schemas (request/response)
- [ ] `backend/app/schemas/` — Pydantic v2 models matching OpenAPI contract
  - `project.py` — `CreateProjectRequest`, `ProjectResponse`
  - `run.py` — `CreateRunRequest`, `ProjectRunResponse`
  - `artifact.py` — `ArtifactResponse`, `ArtifactListResponse`
  - `design.py` — `DesignGenerateRequest`, `DesignFeedbackRequest`
  - `approval.py` — `ApprovalRequest`, `ApprovalEventResponse`
  - `deploy.py` — `DeployRequest`, `DeploymentRecordResponse`

## Definition of Done
- [ ] `alembic upgrade head` applies cleanly to empty Postgres
- [ ] All 9 tables created with correct columns, types, constraints, and indexes
- [ ] Enum values match across SQLAlchemy models, Pydantic schemas, `db/schema.sql`, and `contracts/domain-types.ts`
- [ ] Round-trip test: create a project via ORM, read it back, verify all fields
