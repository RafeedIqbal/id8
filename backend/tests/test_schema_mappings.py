from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.approval import ApprovalEventResponse
from app.schemas.artifact import ArtifactResponse, ProjectArtifactResponse
from app.schemas.deploy import DeploymentRecordResponse
from app.schemas.project import ProjectResponse


def test_deployment_record_response_maps_deployment_url_to_url() -> None:
    record = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        environment="production",
        status="succeeded",
        deployment_url="https://example.com/deploy/123",
        created_at=datetime.now(UTC),
    )

    response = DeploymentRecordResponse.model_validate(record)

    assert response.url == "https://example.com/deploy/123"


def test_project_response_includes_owner_user_id() -> None:
    project = SimpleNamespace(
        id=uuid4(),
        owner_user_id=uuid4(),
        initial_prompt="Build me an app",
        status="ideation",
        github_repo_url=None,
        live_deployment_url=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    response = ProjectResponse.model_validate(project)

    assert response.owner_user_id == project.owner_user_id


def test_project_artifact_response_includes_run_id_and_wrapper_shape() -> None:
    artifact = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        run_id=uuid4(),
        artifact_type="prd",
        version=1,
        content={"summary": "ok"},
        model_profile="primary",
        created_at=datetime.now(UTC),
    )

    item = ProjectArtifactResponse.model_validate(artifact)
    response = ArtifactResponse(artifact=item)

    assert response.artifact.run_id == artifact.run_id


def test_approval_event_response_includes_actor_and_run() -> None:
    event = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        run_id=uuid4(),
        stage="prd",
        decision="approved",
        notes="LGTM",
        created_by=uuid4(),
        created_at=datetime.now(UTC),
    )

    response = ApprovalEventResponse.model_validate(event)

    assert response.run_id == event.run_id
    assert response.created_by == event.created_by
