"""HTTP-layer tests for all 8 API endpoints.

These tests use httpx.AsyncClient against the real FastAPI app
with the DB dependency overridden to use a per-test transactional session
(rolled back after each test — no data leaks).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import get_db
from app.design.base import DesignOutput, Screen
from app.main import create_app
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ArtifactType, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def db():
    """Transactional session rolled back after every test."""
    conn = await _engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    yield session
    await session.close()
    await txn.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    """AsyncClient that shares the transactional session with the app."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seed_user(db: AsyncSession) -> User:
    """Ensure a scaffold user exists, plus the hardcoded route scaffold owner."""
    # The approvals route hardcodes created_by to this UUID
    scaffold_owner_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    scaffold_owner = User(id=scaffold_owner_id, email="operator+scaffold@id8.local", role="operator")
    db.add(scaffold_owner)

    user = User(id=_SCAFFOLD_USER_ID, email="test-route@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    """Create a project in ideation status."""
    project = Project(owner_user_id=seed_user.id, initial_prompt="Build me a todo app")
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def seed_run(db: AsyncSession, seed_project: Project) -> ProjectRun:
    """Create a run for the seed project."""
    run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.IDEATION,
        current_node="IngestPrompt",
    )
    db.add(run)
    await db.flush()
    return run


# ---------------------------------------------------------------------------
# POST /v1/projects — createProject
# ---------------------------------------------------------------------------


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient, seed_user: User) -> None:
        resp = await client.post("/v1/projects", json={"initial_prompt": "Build a CRM"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["initial_prompt"] == "Build a CRM"
        assert data["status"] == "ideation"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_missing_prompt_returns_422(self, client: AsyncClient, seed_user: User) -> None:
        resp = await client.post("/v1/projects", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body


# ---------------------------------------------------------------------------
# GET /v1/projects/{projectId} — getProject
# ---------------------------------------------------------------------------


class TestGetProject:
    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient, seed_project: Project) -> None:
        resp = await client.get(f"/v1/projects/{seed_project.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(seed_project.id)

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient, seed_user: User) -> None:
        fake_id = uuid.uuid4()
        resp = await client.get(f"/v1/projects/{fake_id}")
        assert resp.status_code == 404
        assert "error" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/projects/{projectId}/runs — createRun
# ---------------------------------------------------------------------------


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient, seed_project: Project) -> None:
        resp = await client.post(f"/v1/projects/{seed_project.id}/runs")
        assert resp.status_code == 202
        data = resp.json()
        assert data["project_id"] == str(seed_project.id)
        assert data["current_node"] == "IngestPrompt"

    @pytest.mark.asyncio
    async def test_idempotency_key_returns_same_run(self, client: AsyncClient, seed_project: Project) -> None:
        idem_key = f"test-{uuid.uuid4()}"
        headers = {"Idempotency-Key": idem_key}
        r1 = await client.post(f"/v1/projects/{seed_project.id}/runs", headers=headers)
        r2 = await client.post(f"/v1/projects/{seed_project.id}/runs", headers=headers)
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["id"] == r2.json()["id"]

    @pytest.mark.asyncio
    async def test_project_not_found(self, client: AsyncClient, seed_user: User) -> None:
        fake_id = uuid.uuid4()
        resp = await client.post(f"/v1/projects/{fake_id}/runs")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_idempotency_key_conflict_across_projects(
        self,
        client: AsyncClient,
        db: AsyncSession,
        seed_user: User,
    ) -> None:
        project_one = Project(owner_user_id=seed_user.id, initial_prompt="Project one")
        project_two = Project(owner_user_id=seed_user.id, initial_prompt="Project two")
        db.add(project_one)
        db.add(project_two)
        await db.flush()

        idem_key = f"cross-project-{uuid.uuid4()}"
        headers = {"Idempotency-Key": idem_key}
        ok_resp = await client.post(f"/v1/projects/{project_one.id}/runs", headers=headers)
        conflict_resp = await client.post(f"/v1/projects/{project_two.id}/runs", headers=headers)

        assert ok_resp.status_code == 202
        assert conflict_resp.status_code == 409
        assert "different project" in conflict_resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_requires_failed_run(
        self, client: AsyncClient, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        resp = await client.post(
            f"/v1/projects/{seed_project.id}/runs",
            json={"resume_from_node": "IngestPrompt"},
        )
        assert resp.status_code == 409
        assert "failed run" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_requires_previously_reached_node(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_run.status = ProjectStatus.FAILED
        seed_run.current_node = "EndFailed"
        await db.flush()

        resp = await client.post(
            f"/v1/projects/{seed_project.id}/runs",
            json={"resume_from_node": "DeployProduction"},
        )
        assert resp.status_code == 409
        assert "not reached" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_reuses_failed_run(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_run.status = ProjectStatus.FAILED
        seed_run.current_node = "EndFailed"
        seed_run.last_error_code = "TEST"
        seed_run.last_error_message = "boom"

        artifact = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.PRD,
            version=1,
            content={"__node_name": "GeneratePRD", "summary": "existing"},
            model_profile=ModelProfile.PRIMARY,
        )
        db.add(artifact)
        await db.flush()

        resp = await client.post(
            f"/v1/projects/{seed_project.id}/runs",
            json={"resume_from_node": "GeneratePRD"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["id"] == str(seed_run.id)
        assert data["current_node"] == "GeneratePRD"
        assert data["last_error_code"] is None


# ---------------------------------------------------------------------------
# POST /v1/projects/{projectId}/design/generate — generateDesign
# ---------------------------------------------------------------------------


class TestGenerateDesign:
    @pytest.mark.asyncio
    async def test_happy_path(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        # Set project to prd_approved so design generation is valid
        seed_project.status = ProjectStatus.PRD_APPROVED
        await db.flush()

        body = {
            "provider": "stitch_mcp",
            "model_profile": "primary",
            "stitch_auth": {
                "auth_method": "api_key",
                "api_key": "secret-api-key-123",
            },
        }
        resp = await client.post(f"/v1/projects/{seed_project.id}/design/generate", json=body)
        assert resp.status_code == 202
        data = resp.json()
        assert data["artifact"]["artifact_type"] == "design_spec"
        assert data["artifact"]["version"] == 1
        assert data["artifact"]["content"]["stitch_auth_method"] == "api_key"
        assert "stitch_auth" not in data["artifact"]["content"]

    @pytest.mark.asyncio
    async def test_invalid_status_returns_409(
        self, client: AsyncClient, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        # Project is in ideation — design generation should fail
        body = {"provider": "stitch_mcp", "model_profile": "primary"}
        resp = await client.post(f"/v1/projects/{seed_project.id}/design/generate", json=body)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /v1/projects/{projectId}/design/feedback — submitDesignFeedback
# ---------------------------------------------------------------------------


class TestDesignFeedback:
    @pytest.mark.asyncio
    async def test_happy_path(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_project.status = ProjectStatus.DESIGN_DRAFT
        prior = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.DESIGN_SPEC,
            version=1,
            content={
                "screens": [{"id": "screen-1", "name": "Dashboard", "components": [], "assets": []}],
                "__design_metadata": {
                    "provider_used": "internal_spec",
                    "usable_tools": ["x"],
                },
            },
            model_profile=ModelProfile.CUSTOMTOOLS,
        )
        db.add(prior)
        await db.flush()

        body = {"feedback_text": "Make the header bigger"}
        regenerated = DesignOutput(
            screens=[Screen(id="screen-1", name="Dashboard V2")],
            metadata={"provider": "internal_spec", "generation_time_ms": 12.3},
        )
        with patch(
            "app.routes.design.regenerate_with_fallback",
            new=AsyncMock(return_value=(regenerated, "internal_spec")),
        ):
            resp = await client.post(f"/v1/projects/{seed_project.id}/design/feedback", json=body)

        assert resp.status_code == 202
        data = resp.json()
        assert data["artifact"]["version"] == 2
        assert data["artifact"]["content"]["screens"][0]["name"] == "Dashboard V2"
        assert data["artifact"]["content"]["__design_metadata"]["feedback_text"] == "Make the header bigger"
        assert data["artifact"]["content"]["__design_metadata"]["usable_tools"] == ["x"]

    @pytest.mark.asyncio
    async def test_wrong_status_returns_409(
        self, client: AsyncClient, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        body = {"feedback_text": "Make the header bigger"}
        resp = await client.post(f"/v1/projects/{seed_project.id}/design/feedback", json=body)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/design/tools — listDesignTools
# ---------------------------------------------------------------------------


class TestDesignTools:
    @pytest.mark.asyncio
    async def test_lists_stitch_tools(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/design/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "stitch_mcp"
        names = {tool["name"] for tool in data["usable_tools"]}
        assert "generate_screen_from_text" in names


# ---------------------------------------------------------------------------
# POST /v1/projects/{projectId}/approvals — submitApproval
# ---------------------------------------------------------------------------


class TestSubmitApproval:
    @pytest.mark.asyncio
    async def test_happy_path_approve(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_project.status = ProjectStatus.PRD_DRAFT
        seed_run.current_node = "WaitPRDApproval"
        await db.flush()

        body = {"stage": "prd", "decision": "approved"}
        resp = await client.post(f"/v1/projects/{seed_project.id}/approvals", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "prd"
        assert data["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_invalid_state_transition_returns_409(
        self, client: AsyncClient, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        # Project is in ideation, cannot submit prd approval
        body = {"stage": "prd", "decision": "approved"}
        resp = await client.post(f"/v1/projects/{seed_project.id}/approvals", json=body)
        assert resp.status_code == 409
        assert "error" in resp.json()

    @pytest.mark.asyncio
    async def test_rejection_keeps_status(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_project.status = ProjectStatus.PRD_DRAFT
        seed_run.current_node = "WaitPRDApproval"
        await db.flush()

        body = {"stage": "prd", "decision": "rejected", "notes": "Needs more detail"}
        resp = await client.post(f"/v1/projects/{seed_project.id}/approvals", json=body)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "rejected"

        # Verify project status unchanged
        get_resp = await client.get(f"/v1/projects/{seed_project.id}")
        assert get_resp.json()["status"] == "prd_draft"

    @pytest.mark.asyncio
    async def test_stage_must_match_wait_node(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_project.status = ProjectStatus.PRD_DRAFT
        seed_run.current_node = "WaitDesignApproval"
        await db.flush()

        body = {"stage": "prd", "decision": "approved"}
        resp = await client.post(f"/v1/projects/{seed_project.id}/approvals", json=body)
        assert resp.status_code == 409
        assert "only valid at" in resp.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# GET /v1/projects/{projectId}/artifacts — listArtifacts
# ---------------------------------------------------------------------------


class TestListArtifacts:
    @pytest.mark.asyncio
    async def test_happy_path_empty(self, client: AsyncClient, seed_project: Project) -> None:
        resp = await client.get(f"/v1/projects/{seed_project.id}/artifacts")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    @pytest.mark.asyncio
    async def test_returns_artifacts(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        artifact = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.PRD,
            version=1,
            content={"summary": "Test PRD"},
            model_profile=ModelProfile.PRIMARY,
        )
        db.add(artifact)
        await db.flush()

        resp = await client.get(f"/v1/projects/{seed_project.id}/artifacts")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["artifact_type"] == "prd"

    @pytest.mark.asyncio
    async def test_project_not_found(self, client: AsyncClient, seed_user: User) -> None:
        fake_id = uuid.uuid4()
        resp = await client.get(f"/v1/projects/{fake_id}/artifacts")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/projects/{projectId}/deploy — deployProject
# ---------------------------------------------------------------------------


class TestDeployProject:
    @pytest.mark.asyncio
    async def test_happy_path(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun, seed_user: User
    ) -> None:
        # Setup: project must be deploy_ready with a deploy approval
        seed_project.status = ProjectStatus.DEPLOY_READY
        approval = ApprovalEvent(
            project_id=seed_project.id,
            run_id=seed_run.id,
            stage=ApprovalStage.DEPLOY,
            decision="approved",
            created_by=seed_user.id,
        )
        db.add(approval)
        await db.flush()

        resp = await client.post(f"/v1/projects/{seed_project.id}/deploy")
        assert resp.status_code == 202
        data = resp.json()
        assert data["environment"] == "production"
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_wrong_status_returns_409(
        self, client: AsyncClient, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        resp = await client.post(f"/v1/projects/{seed_project.id}/deploy")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_no_approval_returns_409(
        self, client: AsyncClient, db: AsyncSession, seed_project: Project, seed_run: ProjectRun
    ) -> None:
        seed_project.status = ProjectStatus.DEPLOY_READY
        await db.flush()

        resp = await client.post(f"/v1/projects/{seed_project.id}/deploy")
        assert resp.status_code == 409
        assert "approval" in resp.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Middleware: X-Request-Id
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    @pytest.mark.asyncio
    async def test_generates_request_id(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert "x-request-id" in resp.headers
        # Should be a valid UUID
        uuid.UUID(resp.headers["x-request-id"])

    @pytest.mark.asyncio
    async def test_echoes_provided_request_id(self, client: AsyncClient) -> None:
        custom_id = "my-custom-request-id-123"
        resp = await client.get("/health", headers={"X-Request-Id": custom_id})
        assert resp.headers["x-request-id"] == custom_id


# ---------------------------------------------------------------------------
# OpenAPI contract alignment
# ---------------------------------------------------------------------------


class TestOpenAPIContract:
    @pytest.mark.asyncio
    async def test_uses_contract_path_and_operation_ids(self, client: AsyncClient) -> None:
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()

        assert "/v1/projects/{projectId}" in spec["paths"]
        assert "/v1/projects/{project_id}" not in spec["paths"]

        expected_operation_ids = {
            ("/v1/projects", "post"): "createProject",
            ("/v1/projects/{projectId}", "get"): "getProject",
            ("/v1/projects/{projectId}/runs", "post"): "createRun",
            ("/v1/projects/{projectId}/design/generate", "post"): "generateDesign",
            ("/v1/projects/{projectId}/design/feedback", "post"): "submitDesignFeedback",
            ("/v1/projects/{projectId}/approvals", "post"): "submitApproval",
            ("/v1/projects/{projectId}/artifacts", "get"): "listArtifacts",
            ("/v1/projects/{projectId}/deploy", "post"): "deployProject",
        }
        for (path, method), operation_id in expected_operation_ids.items():
            assert spec["paths"][path][method]["operationId"] == operation_id

    @pytest.mark.asyncio
    async def test_uses_contract_schema_names(self, client: AsyncClient) -> None:
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        schemas = set(resp.json()["components"]["schemas"].keys())

        expected = {
            "CreateProjectRequest",
            "CreateRunRequest",
            "DesignGenerateRequest",
            "DesignFeedbackRequest",
            "ApprovalRequest",
            "DeployRequest",
            "Project",
            "ProjectRun",
            "ProjectArtifact",
            "ArtifactResponse",
            "ApprovalEvent",
            "DeploymentRecord",
        }
        assert expected.issubset(schemas)
