from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ArtifactType, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.user import User


@pytest.mark.asyncio
async def test_create_and_read_user(db):
    user = User(email="test@id8.dev", role="operator")
    db.add(user)
    await db.flush()

    result = await db.execute(select(User).where(User.email == "test@id8.dev"))
    loaded = result.scalar_one()
    assert loaded.id is not None
    assert loaded.email == "test@id8.dev"
    assert loaded.role == "operator"
    assert loaded.created_at is not None


@pytest.mark.asyncio
async def test_project_roundtrip(db):
    user = User(email=f"owner-{uuid.uuid4()}@id8.dev", role="admin")
    db.add(user)
    await db.flush()

    project = Project(
        owner_user_id=user.id,
        initial_prompt="Build a todo app with auth",
    )
    db.add(project)
    await db.flush()

    result = await db.execute(select(Project).where(Project.id == project.id))
    loaded = result.scalar_one()
    assert loaded.initial_prompt == "Build a todo app with auth"
    assert loaded.status == ProjectStatus.IDEATION
    assert loaded.github_repo_url is None
    assert loaded.live_deployment_url is None
    assert loaded.owner_user_id == user.id


@pytest.mark.asyncio
async def test_run_with_artifact_and_approval(db):
    # Create user + project
    user = User(email=f"op-{uuid.uuid4()}@id8.dev", role="operator")
    db.add(user)
    await db.flush()

    project = Project(owner_user_id=user.id, initial_prompt="Build a CRM")
    db.add(project)
    await db.flush()

    # Create run
    run = ProjectRun(
        project_id=project.id,
        status=ProjectStatus.PRD_DRAFT,
        current_node="GeneratePRD",
        idempotency_key=f"run-{uuid.uuid4()}",
    )
    db.add(run)
    await db.flush()

    assert run.retry_count == 0
    assert run.last_error_code is None

    # Create artifact
    artifact = ProjectArtifact(
        project_id=project.id,
        run_id=run.id,
        artifact_type=ArtifactType.PRD,
        version=1,
        model_profile=ModelProfile.PRIMARY,
        content={"executive_summary": "A CRM system", "user_stories": []},
    )
    db.add(artifact)
    await db.flush()

    result = await db.execute(
        select(ProjectArtifact).where(
            ProjectArtifact.project_id == project.id,
            ProjectArtifact.artifact_type == ArtifactType.PRD,
        )
    )
    loaded_artifact = result.scalar_one()
    assert loaded_artifact.version == 1
    assert loaded_artifact.content["executive_summary"] == "A CRM system"
    assert loaded_artifact.model_profile == ModelProfile.PRIMARY

    # Create approval event
    approval = ApprovalEvent(
        project_id=project.id,
        run_id=run.id,
        stage=ApprovalStage.PRD,
        decision="approved",
        notes="Looks good",
        created_by=user.id,
    )
    db.add(approval)
    await db.flush()

    result = await db.execute(
        select(ApprovalEvent).where(
            ApprovalEvent.project_id == project.id,
            ApprovalEvent.stage == ApprovalStage.PRD,
        )
    )
    loaded_approval = result.scalar_one()
    assert loaded_approval.decision == "approved"
    assert loaded_approval.notes == "Looks good"
    assert loaded_approval.created_by == user.id


@pytest.mark.asyncio
async def test_artifact_unique_constraint(db):
    """Verify the unique constraint on (project_id, artifact_type, version)."""
    from sqlalchemy.exc import IntegrityError

    user = User(email=f"dup-{uuid.uuid4()}@id8.dev", role="operator")
    db.add(user)
    await db.flush()

    project = Project(owner_user_id=user.id, initial_prompt="Test constraints")
    db.add(project)
    await db.flush()

    run = ProjectRun(
        project_id=project.id,
        status=ProjectStatus.PRD_DRAFT,
        current_node="GeneratePRD",
    )
    db.add(run)
    await db.flush()

    artifact1 = ProjectArtifact(
        project_id=project.id,
        run_id=run.id,
        artifact_type=ArtifactType.PRD,
        version=1,
        content={"v": 1},
    )
    db.add(artifact1)
    await db.flush()

    # Use a savepoint so the IntegrityError doesn't poison the outer transaction
    nested = await db.begin_nested()
    artifact2 = ProjectArtifact(
        project_id=project.id,
        run_id=run.id,
        artifact_type=ArtifactType.PRD,
        version=1,
        content={"v": "duplicate"},
    )
    db.add(artifact2)
    with pytest.raises(IntegrityError):
        await db.flush()
    await nested.rollback()

    # Verify v2 with different version succeeds
    artifact3 = ProjectArtifact(
        project_id=project.id,
        run_id=run.id,
        artifact_type=ArtifactType.PRD,
        version=2,
        content={"v": 2},
    )
    db.add(artifact3)
    await db.flush()
    assert artifact3.id is not None
