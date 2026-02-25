# Task 11: Deployment Pipeline (DeployProduction Node)

## Goal
Implement Supabase and Vercel provisioning/deployment via native APIs. Deploy only after explicit deploy approval.

## Dependencies
- Task 10 (GitHub — merged code is deployed)
- Task 03 (orchestrator — WaitDeployApproval gate)

## Source of Truth
- `orchestration/state-machine.md` — nodes 11-12
- `PRD.MD` §5.6 — Module 6: Deployment
- `IMPLEMENTATION-PLAN-V2.MD` — Agent-Deploy

## Steps

### 1. Supabase provisioning
- [ ] `backend/app/deploy/supabase.py`
- [ ] Using Supabase Management API:
  - Create project if not exists
  - Run database migrations from code snapshot's SQL files
  - Configure auth settings
  - Return connection strings and publishable keys
- [ ] Store `supabase_url` and `supabase_anon_key` (publishable only)
- [ ] Server-role key stays backend-only — NEVER include in frontend config

### 2. Vercel deployment
- [ ] `backend/app/deploy/vercel.py`
- [ ] Using Vercel API:
  - Create project linked to GitHub repo (if not exists)
  - Trigger deployment from merged main branch
  - Poll deployment status until ready
  - Return production URL
- [ ] Configure environment variables on Vercel:
  - Only publishable keys (NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY)
  - NEVER inject service-role or server-only secrets

### 3. DeployProduction handler
- [ ] `backend/app/orchestrator/handlers/deploy_production.py`
- [ ] Pre-check: verify `deploy` approval event exists
- [ ] Steps:
  1. Provision Supabase (or verify existing)
  2. Run database migrations
  3. Trigger Vercel deployment
  4. Poll until deployment is live
  5. Verify production URL responds (basic health check)
- [ ] Create `DeploymentRecord`:
  - environment = `production`
  - status = `success` or `failed`
  - provider_payload = raw Vercel/Supabase response
  - deployment_url = live URL
- [ ] Create `ProjectArtifact`:
  - artifact_type = `deploy_report`
  - content = deployment details (URLs, provider info, timing)
- [ ] Update `projects.live_deployment_url`
- [ ] On success: transition to `EndSuccess`
- [ ] On failure: transition to `EndFailed` with resume metadata

### 4. Secret safety
- [ ] `backend/app/deploy/secret_filter.py`
- [ ] Before injecting env vars into Vercel:
  - Filter against allowlist of publishable key patterns
  - Reject any key containing `SERVICE_ROLE`, `SECRET`, `PRIVATE`
  - Log all injected keys (names only, not values) to audit trail

### 5. Rollback labeling
- [ ] On deploy failure: label the deployment record as `rollback_candidate`
- [ ] Store enough metadata to retry or manually roll back

### 6. Deploy endpoint implementation
- [ ] Wire `POST /v1/projects/{projectId}/deploy` to:
  1. Verify deploy approval exists
  2. Verify project status is `deploy_ready`
  3. Trigger orchestrator to enter `DeployProduction` node
  4. Return `DeploymentRecordResponse`

## Definition of Done
- [ ] Supabase project is provisioned with migrations applied
- [ ] Vercel deployment succeeds with live production URL
- [ ] Production URL is persisted on project record
- [ ] Only publishable keys are in frontend runtime
- [ ] Server-only credentials never appear in deploy config
- [ ] Failed deploys are resumable or labeled for rollback
- [ ] Matches acceptance test scenario #8 (Secret Safety)
