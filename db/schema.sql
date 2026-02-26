-- ID8 MVP v2 canonical schema

create extension if not exists "pgcrypto";

do $$
begin
  if not exists (select 1 from pg_type where typname = 'design_provider_enum') then
    create type design_provider_enum as enum ('stitch_mcp', 'internal_spec', 'manual_upload');
  end if;

  if not exists (select 1 from pg_type where typname = 'model_profile_enum') then
    create type model_profile_enum as enum ('primary', 'customtools', 'fallback');
  end if;

  if not exists (select 1 from pg_type where typname = 'project_status_enum') then
    create type project_status_enum as enum (
      'ideation',
      'prd_draft',
      'prd_approved',
      'design_draft',
      'design_approved',
      'tech_plan_draft',
      'tech_plan_approved',
      'codegen',
      'security_gate',
      'deploy_ready',
      'deploying',
      'deployed',
      'failed'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'artifact_type_enum') then
    create type artifact_type_enum as enum (
      'prd',
      'design_spec',
      'tech_plan',
      'code_snapshot',
      'security_report',
      'deploy_report'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'approval_stage_enum') then
    create type approval_stage_enum as enum ('prd', 'design', 'tech_plan', 'deploy');
  end if;
end$$;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  role text not null check (role in ('operator', 'admin')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references users(id),
  initial_prompt text not null,
  status project_status_enum not null default 'ideation',
  github_repo_url text,
  live_deployment_url text,
  deleted_at timestamptz default null,
  stack_json jsonb default null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists project_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  status project_status_enum not null,
  current_node text not null,
  idempotency_key text unique,
  retry_count int not null default 0,
  last_error_code text,
  last_error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists project_artifacts (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  run_id uuid not null references project_runs(id) on delete cascade,
  artifact_type artifact_type_enum not null,
  version int not null,
  model_profile model_profile_enum,
  content jsonb not null,
  created_at timestamptz not null default now(),
  unique (project_id, artifact_type, version)
);

create table if not exists approval_events (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  run_id uuid not null references project_runs(id) on delete cascade,
  stage approval_stage_enum not null,
  decision text not null check (decision in ('approved', 'rejected')),
  notes text,
  created_by uuid not null references users(id),
  created_at timestamptz not null default now()
);

create table if not exists provider_credentials (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  provider text not null,
  encrypted_secret text not null,
  secret_scope text not null,
  last_rotated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, provider, secret_scope)
);

create table if not exists deployment_records (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  run_id uuid not null references project_runs(id) on delete cascade,
  environment text not null check (environment in ('production')),
  status text not null,
  provider_payload jsonb not null,
  deployment_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists retry_jobs (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references project_runs(id) on delete cascade,
  node_name text not null,
  retry_attempt int not null default 0,
  scheduled_for timestamptz not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  processed_at timestamptz
);

create table if not exists audit_events (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references projects(id) on delete set null,
  actor_user_id uuid references users(id) on delete set null,
  event_type text not null,
  event_payload jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_projects_owner on projects(owner_user_id);
create index if not exists idx_runs_project_status on project_runs(project_id, status, updated_at desc);
create index if not exists idx_artifacts_project_type on project_artifacts(project_id, artifact_type, created_at desc);
create index if not exists idx_approval_events_project_stage on approval_events(project_id, stage, created_at desc);
create index if not exists idx_retry_jobs_schedule on retry_jobs(scheduled_for, processed_at);
