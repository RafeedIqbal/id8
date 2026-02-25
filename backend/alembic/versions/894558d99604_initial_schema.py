"""initial_schema

Revision ID: 894558d99604
Revises:
Create Date: 2026-02-25 19:55:56.839048

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "894558d99604"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum definitions matching db/schema.sql
design_provider_enum = ENUM(
    "stitch_mcp", "internal_spec", "manual_upload",
    name="design_provider_enum", create_type=False,
)
model_profile_enum = ENUM(
    "primary", "customtools", "fallback",
    name="model_profile_enum", create_type=False,
)
project_status_enum = ENUM(
    "ideation", "prd_draft", "prd_approved", "design_draft", "design_approved",
    "tech_plan_draft", "tech_plan_approved", "codegen", "security_gate",
    "deploy_ready", "deploying", "deployed", "failed",
    name="project_status_enum", create_type=False,
)
artifact_type_enum = ENUM(
    "prd", "design_spec", "tech_plan", "code_snapshot", "security_report", "deploy_report",
    name="artifact_type_enum", create_type=False,
)
approval_stage_enum = ENUM(
    "prd", "design", "tech_plan", "deploy",
    name="approval_stage_enum", create_type=False,
)


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Enums
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'design_provider_enum') THEN
                CREATE TYPE design_provider_enum AS ENUM ('stitch_mcp', 'internal_spec', 'manual_upload');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'model_profile_enum') THEN
                CREATE TYPE model_profile_enum AS ENUM ('primary', 'customtools', 'fallback');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_status_enum') THEN
                CREATE TYPE project_status_enum AS ENUM (
                    'ideation', 'prd_draft', 'prd_approved', 'design_draft', 'design_approved',
                    'tech_plan_draft', 'tech_plan_approved', 'codegen', 'security_gate',
                    'deploy_ready', 'deploying', 'deployed', 'failed'
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'artifact_type_enum') THEN
                CREATE TYPE artifact_type_enum AS ENUM (
                    'prd', 'design_spec', 'tech_plan', 'code_snapshot', 'security_report', 'deploy_report'
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'approval_stage_enum') THEN
                CREATE TYPE approval_stage_enum AS ENUM ('prd', 'design', 'tech_plan', 'deploy');
            END IF;
        END$$;
    """)

    # users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('operator', 'admin')", name="ck_users_role"),
    )

    # projects
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("initial_prompt", sa.Text(), nullable=False),
        sa.Column("status", project_status_enum, nullable=False, server_default="ideation"),
        sa.Column("github_repo_url", sa.Text()),
        sa.Column("live_deployment_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # project_runs
    op.create_table(
        "project_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", project_status_enum, nullable=False),
        sa.Column("current_node", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), unique=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # project_artifacts
    op.create_table(
        "project_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("project_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", artifact_type_enum, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model_profile", model_profile_enum),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "artifact_type", "version"),
    )

    # approval_events
    op.create_table(
        "approval_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("project_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", approval_stage_enum, nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approval_decision"),
    )

    # provider_credentials
    op.create_table(
        "provider_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_scope", sa.Text(), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "provider", "secret_scope"),
    )

    # deployment_records
    op.create_table(
        "deployment_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("project_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_payload", JSONB(), nullable=False),
        sa.Column("deployment_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("environment IN ('production')", name="ck_deploy_environment"),
    )

    # retry_jobs
    op.create_table(
        "retry_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("project_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.Text(), nullable=False),
        sa.Column("retry_attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )

    # audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Indexes (matching db/schema.sql)
    op.create_index("idx_projects_owner", "projects", ["owner_user_id"])
    op.create_index("idx_runs_project_status", "project_runs", ["project_id", "status", sa.text("updated_at DESC")])
    op.create_index("idx_artifacts_project_type", "project_artifacts", ["project_id", "artifact_type", sa.text("created_at DESC")])
    op.create_index("idx_approval_events_project_stage", "approval_events", ["project_id", "stage", sa.text("created_at DESC")])
    op.create_index("idx_retry_jobs_schedule", "retry_jobs", ["scheduled_for", "processed_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("retry_jobs")
    op.drop_table("deployment_records")
    op.drop_table("provider_credentials")
    op.drop_table("approval_events")
    op.drop_table("project_artifacts")
    op.drop_table("project_runs")
    op.drop_table("projects")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS approval_stage_enum")
    op.execute("DROP TYPE IF EXISTS artifact_type_enum")
    op.execute("DROP TYPE IF EXISTS project_status_enum")
    op.execute("DROP TYPE IF EXISTS model_profile_enum")
    op.execute("DROP TYPE IF EXISTS design_provider_enum")
