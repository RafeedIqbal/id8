"""Acceptance test suite for Task 14.

Maps directly to the eight scenarios in ``qa/acceptance-test-plan.md``.
External providers are mocked so the suite can run in CI deterministically.
"""
from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.deploy.secret_filter import assert_no_secrets, filter_env_vars
from app.design.base import DesignOutput, Screen, StitchAuthContext, StitchAuthMethod, StitchRuntimeError
from app.design.internal_spec import InternalSpecProvider
from app.design.stitch_mcp import STITCH_TOOLS, StitchMcpProvider
from app.github.auth import GitHubAuth
from app.github.client import CheckRun, GitHubClient, GitHubConflictError, MergeResult, PrInfo
from app.llm.client import LlmResponse, TokenUsage, generate_with_fallback
from app.llm.router import resolve_model, resolve_profile
from app.models.approval_event import ApprovalEvent
from app.models.audit_event import AuditEvent
from app.models.enums import ApprovalStage, ArtifactType, DesignProvider, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.user import User
from app.orchestrator.base import NodeHandler, NodeResult, RunContext
from app.orchestrator.engine import run_orchestrator
from app.orchestrator.handlers.deploy_production import _record_env_injection_audit
from app.orchestrator.handlers.generate_design import GenerateDesignHandler
from app.orchestrator.handlers.prepare_pr import _run_github_flow
from app.orchestrator.handlers.registry import HANDLER_REGISTRY
from app.orchestrator.handlers.security_gate import SecurityGateHandler
from app.orchestrator.nodes import NodeName
from app.orchestrator.retry import RetryableError
from app.orchestrator.transitions import resolve_next_node
from app.routes.design import submit_design_feedback
from app.routes.runs import create_run
from app.schemas.design import DesignFeedbackRequest
from app.schemas.security_report import SecurityFinding

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000199")
_ACCEPTANCE_LIVE_URL = "https://acceptance.id8.example.com"

_VALID_PRD = {
    "executive_summary": "A collaborative todo app for teams.",
    "user_stories": [
        {
            "persona": "Team member",
            "action": "create and update tasks",
            "benefit": "track progress",
        },
    ],
    "scope_boundaries": {
        "in_scope": ["Task CRUD", "Tags", "Comments"],
        "out_of_scope": ["Realtime collaboration"],
    },
    "entity_list": [
        {"name": "Task", "description": "Work item"},
        {"name": "Tag", "description": "Task category"},
    ],
    "non_goals": ["Native desktop app"],
}

_VALID_PRD_JSON = json.dumps(_VALID_PRD)
_VALID_DESIGN_JSON = json.dumps(
    {
        "screens": [
            {
                "id": "screen-1",
                "name": "Dashboard",
                "description": "Primary task view",
                "components": [
                    {
                        "id": "comp-1",
                        "name": "TaskTable",
                        "type": "table",
                        "properties": {},
                    }
                ],
                "assets": [],
            }
        ]
    }
)
_VALID_TECH_PLAN_JSON = json.dumps(
    {
        "folder_structure": {"backend": {"app": {"main.py": "FastAPI app"}}},
        "database_schema": {"tasks": {"columns": {"id": "uuid"}}},
        "api_routes": [{"method": "GET", "path": "/tasks", "description": "List tasks"}],
        "component_hierarchy": {"App": {"Dashboard": "Main screen"}},
        "dependencies": [{"name": "fastapi", "version": "^0.110.0"}],
        "deployment_config": {"backend": {"runtime": "python3.12"}},
    }
)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Transactional session rolled back after every test."""
    conn = await _engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    yield session
    await session.close()
    await txn.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def seed_user(db: AsyncSession) -> User:
    user = User(id=_SCAFFOLD_USER_ID, email="test-acceptance@id8.local", role="admin")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build a todo app",
        status=ProjectStatus.IDEATION,
    )
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def seed_run(db: AsyncSession, seed_project: Project) -> ProjectRun:
    run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.IDEATION,
        current_node="IngestPrompt",
    )
    db.add(run)
    await db.flush()
    return run


def _make_llm_response(content: str, profile: ModelProfile, model_id: str) -> LlmResponse:
    return LlmResponse(
        content=content,
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=200),
        model_id=model_id,
        latency_ms=25.0,
        profile_used=profile,
    )


def _make_ctx(
    db: AsyncSession,
    run: ProjectRun,
    *,
    node: str,
    previous_artifacts: dict | None = None,
    workflow_payload: dict | None = None,
) -> RunContext:
    return RunContext(
        run_id=run.id,
        project_id=run.project_id,
        current_node=node,
        attempt=0,
        db_session=db,
        previous_artifacts=previous_artifacts or {},
        workflow_payload=workflow_payload or {},
    )


async def _seed_internal_design_pending(db: AsyncSession, run: ProjectRun, version: int = 1) -> None:
    db.add(
        ProjectArtifact(
            project_id=run.project_id,
            run_id=run.id,
            artifact_type=ArtifactType.DESIGN_SPEC,
            version=version,
            content={"status": "pending", "provider": "internal_spec"},
            model_profile=ModelProfile.CUSTOMTOOLS,
        )
    )
    await db.flush()


def _mock_generative_api_response(text: str = "{}") -> MagicMock:
    usage = MagicMock()
    usage.prompt_token_count = 5
    usage.candidates_token_count = 7
    usage.input_token_count = 5
    usage.output_token_count = 7
    response = MagicMock()
    response.text = text
    response.usage_metadata = usage
    return response


class _WriteCodeSuccessHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={
                "files": [
                    {
                        "path": "backend/app/main.py",
                        "content": "from fastapi import FastAPI\n\napp = FastAPI()\n",
                        "language": "python",
                    },
                    {
                        "path": "backend/requirements.txt",
                        "content": "fastapi==0.110.0\n",
                        "language": "text",
                    },
                ]
            },
        )


class _SecurityGatePassHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="passed",
            artifact_data={
                "findings": [],
                "summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0},
                "scan_tools": ["stub"],
                "passed": True,
            },
        )


class _PreparePrSuccessHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            context_updates={
                "pr_url": "https://github.com/acme/id8/pull/1",
                "pr_number": 1,
                "branch_name": f"id8/run-{ctx.run_id}",
            },
        )


class _DeploySuccessHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        result = await ctx.db.execute(select(Project).where(Project.id == ctx.project_id))
        project = result.scalar_one()
        project.live_deployment_url = _ACCEPTANCE_LIVE_URL

        return NodeResult(
            outcome="passed",
            artifact_data={
                "live_url": _ACCEPTANCE_LIVE_URL,
                "environment": "production",
                "vercel": {"state": "READY"},
                "supabase": {},
            },
            context_updates={"live_url": _ACCEPTANCE_LIVE_URL},
        )


class _ExplodingDeployHandler(NodeHandler):
    async def execute(self, ctx: RunContext) -> NodeResult:
        raise AssertionError("DeployProduction handler should not run when checkpoint exists")


@pytest.mark.asyncio
async def test_scenario_1_happy_path(
    db: AsyncSession,
    seed_user: User,
    seed_project: Project,
    seed_run: ProjectRun,
) -> None:
    """Scenario 1: Happy path reaches deployed with all required artifacts."""
    originals = {
        NodeName.WRITE_CODE: HANDLER_REGISTRY[NodeName.WRITE_CODE],
        NodeName.SECURITY_GATE: HANDLER_REGISTRY[NodeName.SECURITY_GATE],
        NodeName.PREPARE_PR: HANDLER_REGISTRY[NodeName.PREPARE_PR],
        NodeName.DEPLOY_PRODUCTION: HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION],
    }
    HANDLER_REGISTRY[NodeName.WRITE_CODE] = _WriteCodeSuccessHandler()
    HANDLER_REGISTRY[NodeName.SECURITY_GATE] = _SecurityGatePassHandler()
    HANDLER_REGISTRY[NodeName.PREPARE_PR] = _PreparePrSuccessHandler()
    HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = _DeploySuccessHandler()

    try:
        with (
            patch(
                "app.orchestrator.handlers.generate_prd.generate_with_fallback",
                new=AsyncMock(
                    return_value=_make_llm_response(
                        _VALID_PRD_JSON,
                        ModelProfile.PRIMARY,
                        "gemini-3.1-pro-preview",
                    )
                ),
            ),
            patch(
                "app.design.internal_spec._generate_with_fallback",
                new=AsyncMock(
                    return_value=_make_llm_response(
                        _VALID_DESIGN_JSON,
                        ModelProfile.CUSTOMTOOLS,
                        "gemini-3.1-pro-preview-customtools",
                    )
                ),
            ),
            patch(
                "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
                new=AsyncMock(
                    return_value=_make_llm_response(
                        _VALID_TECH_PLAN_JSON,
                        ModelProfile.PRIMARY,
                        "gemini-3.1-pro-preview",
                    )
                ),
            ),
        ):
            # Start run and park at first wait node.
            await run_orchestrator(seed_run.id, db)
            await _seed_internal_design_pending(db, seed_run)

            stages = [
                (ApprovalStage.PRD, "WaitPRDApproval"),
                (ApprovalStage.DESIGN, "WaitDesignApproval"),
                (ApprovalStage.TECH_PLAN, "WaitTechPlanApproval"),
                (ApprovalStage.DEPLOY, "WaitDeployApproval"),
            ]
            for stage, expected_node in stages:
                await db.refresh(seed_run)
                assert seed_run.current_node == expected_node

                db.add(
                    ApprovalEvent(
                        project_id=seed_run.project_id,
                        run_id=seed_run.id,
                        stage=stage,
                        decision="approved",
                        created_by=seed_user.id,
                    )
                )
                await db.flush()
                await run_orchestrator(seed_run.id, db)

        await db.refresh(seed_run)
        await db.refresh(seed_project)
        assert seed_run.status == ProjectStatus.DEPLOYED
        assert seed_run.current_node == "EndSuccess"
        assert seed_project.live_deployment_url == _ACCEPTANCE_LIVE_URL

        result = await db.execute(
            select(ProjectArtifact)
            .where(ProjectArtifact.run_id == seed_run.id)
            .order_by(ProjectArtifact.created_at.asc())
        )
        artifacts = result.scalars().all()
        by_type: dict[str, list[ProjectArtifact]] = {}
        for artifact in artifacts:
            by_type.setdefault(str(artifact.artifact_type), []).append(artifact)

        required = {
            "prd",
            "design_spec",
            "tech_plan",
            "code_snapshot",
            "security_report",
            "deploy_report",
        }
        assert required.issubset(by_type.keys())
        deploy_report = max(by_type["deploy_report"], key=lambda item: item.version)
        assert deploy_report.content["live_url"] == _ACCEPTANCE_LIVE_URL
    finally:
        for node, handler in originals.items():
            HANDLER_REGISTRY[node] = handler


@pytest.mark.asyncio
async def test_scenario_2_stitch_iteration_loop(
    db: AsyncSession,
    seed_project: Project,
    seed_run: ProjectRun,
) -> None:
    """Scenario 2: auth prompt + versioned design iteration with feedback metadata."""
    # Missing Stitch credentials should return an actionable setup payload.
    handler = GenerateDesignHandler()
    auth_ctx = _make_ctx(
        db,
        seed_run,
        node="GenerateDesign",
        previous_artifacts={
            "prd": _VALID_PRD,
            "design_spec": {"status": "pending", "provider": "stitch_mcp"},
        },
    )
    auth_result = await handler.execute(auth_ctx)
    assert auth_result.outcome == "failure"
    assert auth_result.artifact_data is not None
    assert auth_result.artifact_data["error_type"] == "stitch_auth_required"
    assert any("Create API Key" in step for step in auth_result.artifact_data["instructions"])

    # Simulate existing stitch-generated design, then apply feedback.
    seed_project.status = ProjectStatus.DESIGN_DRAFT
    seed_run.current_node = "WaitDesignApproval"
    db.add(
        ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.DESIGN_SPEC,
            version=1,
            model_profile=ModelProfile.CUSTOMTOOLS,
            content={
                "screens": [
                    {"id": "screen-1", "name": "Dashboard", "components": [], "assets": []}
                ],
                "__design_metadata": {
                    "provider_used": "stitch_mcp",
                    "usable_tools": STITCH_TOOLS,
                },
            },
        )
    )
    await db.flush()

    regenerated = DesignOutput(
        screens=[Screen(id="screen-1", name="Dashboard v2", components=[], assets=[])],
        metadata={"provider": "stitch_mcp", "usable_tools": STITCH_TOOLS},
    )
    with patch(
        "app.routes.design.regenerate_with_fallback",
        new=AsyncMock(return_value=(regenerated, DesignProvider.STITCH_MCP)),
    ):
        response = await submit_design_feedback(
            body=DesignFeedbackRequest(feedback_text="Increase hierarchy contrast on dashboard"),
            project_id=seed_project.id,
            idempotency_key=None,
            db=db,
        )

    artifact = response["artifact"]
    assert artifact.version == 2
    assert artifact.content["__design_metadata"]["feedback_text"] == "Increase hierarchy contrast on dashboard"
    assert artifact.content["__design_metadata"]["usable_tools"] == STITCH_TOOLS

    versions_result = await db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.project_id == seed_project.id,
            ProjectArtifact.artifact_type == ArtifactType.DESIGN_SPEC,
        )
        .order_by(ProjectArtifact.version.asc())
    )
    versions = [item.version for item in versions_result.scalars().all()]
    assert versions == [1, 2]


@pytest.mark.asyncio
async def test_scenario_3_stitch_outage_fallback(
    db: AsyncSession,
    seed_project: Project,
    seed_run: ProjectRun,
) -> None:
    """Scenario 3: Stitch runtime outage falls back to internal_spec and logs audit event."""
    handler = GenerateDesignHandler()
    ctx = _make_ctx(
        db,
        seed_run,
        node="GenerateDesign",
        previous_artifacts={
            "prd": _VALID_PRD,
            "design_spec": {"status": "pending", "provider": "stitch_mcp"},
        },
    )

    internal_output = DesignOutput(
        screens=[Screen(id="screen-fallback", name="Fallback Screen", components=[], assets=[])],
        metadata={"provider": "internal_spec"},
    )
    with (
        patch.object(
            StitchMcpProvider,
            "generate",
            new=AsyncMock(side_effect=StitchRuntimeError("simulated outage")),
        ),
        patch.object(InternalSpecProvider, "generate", new=AsyncMock(return_value=internal_output)),
    ):
        result = await handler.execute(ctx)

    assert result.outcome == "success"
    assert result.artifact_data is not None
    assert str(result.artifact_data["__design_metadata"]["provider_used"]) == "internal_spec"

    await db.flush()
    event_result = await db.execute(
        select(AuditEvent).where(
            AuditEvent.project_id == seed_project.id,
            AuditEvent.event_type == "design.provider_fallback",
        )
    )
    event = event_result.scalar_one_or_none()
    assert event is not None
    assert event.event_payload["run_id"] == str(seed_run.id)
    assert str(event.event_payload["from_provider"]) == "stitch_mcp"
    assert str(event.event_payload["to_provider"]) == "internal_spec"


@pytest.mark.asyncio
async def test_scenario_4_model_routing() -> None:
    """Scenario 4: profile routing and fallback model only on retry conditions."""
    assert resolve_model(resolve_profile("GeneratePRD")) == "gemini-3.1-pro-preview"
    assert resolve_model(resolve_profile("WriteCode")) == "gemini-3.1-pro-preview-customtools"

    retry_models: list[str] = []

    async def retry_then_success(**kwargs):  # type: ignore[no-untyped-def]
        retry_models.append(str(kwargs["model"]))
        if len(retry_models) < 3:
            raise RetryableError("transient")
        return _mock_generative_api_response("{}")

    retry_client = MagicMock()
    retry_client.aio.models.generate_content = AsyncMock(side_effect=retry_then_success)
    with patch("app.llm.client._get_client", return_value=retry_client):
        retry_result = await generate_with_fallback(
            profile=ModelProfile.PRIMARY,
            node_name="GeneratePRD",
            prompt="Generate a PRD",
        )

    assert retry_models[0:2] == [
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview",
    ]
    assert retry_models[2] == "gemini-2.5-pro"
    assert retry_result.profile_used == ModelProfile.FALLBACK

    primary_models: list[str] = []

    async def success_first_try(**kwargs):  # type: ignore[no-untyped-def]
        primary_models.append(str(kwargs["model"]))
        return _mock_generative_api_response("{}")

    primary_client = MagicMock()
    primary_client.aio.models.generate_content = AsyncMock(side_effect=success_first_try)
    with patch("app.llm.client._get_client", return_value=primary_client):
        primary_result = await generate_with_fallback(
            profile=ModelProfile.PRIMARY,
            node_name="GeneratePRD",
            prompt="Generate another PRD",
        )

    assert primary_models == ["gemini-3.1-pro-preview"]
    assert primary_result.profile_used == ModelProfile.PRIMARY


@pytest.mark.asyncio
async def test_scenario_5_security_block(
    db: AsyncSession,
    seed_project: Project,
    seed_run: ProjectRun,
) -> None:
    """Scenario 5: high/critical findings block deploy and loop back to WriteCode."""
    db.add(
        ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.CODE_SNAPSHOT,
            version=1,
            model_profile=ModelProfile.CUSTOMTOOLS,
            content={
                "files": [
                    {
                        "path": "backend/app/main.py",
                        "content": "import pickle\n",
                        "language": "python",
                    },
                    {
                        "path": "backend/requirements.txt",
                        "content": "fastapi==0.110.0\n",
                        "language": "text",
                    },
                ]
            },
        )
    )
    await db.flush()

    high_finding = SecurityFinding(
        rule_id="B301",
        severity="high",
        file_path="backend/app/main.py",
        line_number=1,
        message="Use of pickle",
        remediation="Use a safe serializer",
    )
    critical_finding = SecurityFinding(
        rule_id="SECRET_KEY",
        severity="critical",
        file_path="backend/.env",
        line_number=1,
        message="Hardcoded secret",
        remediation="Load from environment",
    )

    handler = SecurityGateHandler()
    ctx = _make_ctx(db, seed_run, node="SecurityGate")
    with (
        patch("app.security.sast.run_sast", new=AsyncMock(return_value=[high_finding])),
        patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
        patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[critical_finding])),
    ):
        result = await handler.execute(ctx)

    assert result.outcome == "failed"
    assert result.artifact_data is not None
    assert result.artifact_data["summary"]["high"] == 1
    assert result.artifact_data["summary"]["critical"] == 1
    assert resolve_next_node("SecurityGate", "failed") == "WriteCode"
    assert resolve_next_node("SecurityGate", "failed") not in {"PreparePR", "DeployProduction"}


@pytest.mark.asyncio
async def test_scenario_6_git_policy_enforcement(
    db: AsyncSession,
    seed_project: Project,
    seed_run: ProjectRun,
) -> None:
    """Scenario 6: direct push rejected; branch + PR + checks + merge path succeeds."""
    git_client = GitHubClient(GitHubAuth(mode="token", token="ghp_test"))
    with pytest.raises(GitHubConflictError, match="Direct pushes to protected branch"):
        await git_client.push_files(
            "acme",
            "repo",
            "main",
            [{"path": "README.md", "content": "# hi"}],
        )

    seed_project.github_repo_url = "https://github.com/acme/id8-acceptance"
    await db.flush()

    ctx = _make_ctx(
        db,
        seed_run,
        node="PreparePR",
        workflow_payload={"initial_prompt": "Acceptance PR flow"},
    )
    mock_client = MagicMock()
    mock_client.push_files = AsyncMock(return_value="commit-sha")
    mock_client.poll_checks = AsyncMock(
        return_value=[
            CheckRun(
                id=1,
                name="ci/test",
                status="completed",
                conclusion="success",
                html_url="https://github.com/acme/id8/actions/runs/1",
            )
        ]
    )
    mock_client.merge_pull_request = AsyncMock(
        return_value=MergeResult(sha="merge-sha", merged=True, message="merged")
    )

    pr_info = PrInfo(
        number=7,
        html_url="https://github.com/acme/id8-acceptance/pull/7",
        state="open",
        head_sha="head-sha",
        title="feat(id8): Acceptance PR flow",
    )
    with (
        patch("app.orchestrator.handlers.prepare_pr._ensure_branch", new=AsyncMock(return_value="main")),
        patch("app.orchestrator.handlers.prepare_pr._find_closed_pull_request", new=AsyncMock(return_value=None)),
        patch("app.orchestrator.handlers.prepare_pr._ensure_pull_request", new=AsyncMock(return_value=pr_info)),
        patch("app.orchestrator.handlers.prepare_pr._persist_prepare_pr_metadata", new=AsyncMock()),
    ):
        result = await _run_github_flow(
            ctx,
            mock_client,
            files=[{"path": "backend/app/main.py", "content": "print('ok')"}],
        )

    assert result.outcome == "success"
    assert result.context_updates is not None
    assert result.context_updates["pr_url"] == pr_info.html_url
    assert mock_client.push_files.await_count == 1
    assert mock_client.merge_pull_request.await_count == 1


@pytest.mark.asyncio
async def test_scenario_7_resume_reliability(
    db: AsyncSession,
    seed_project: Project,
    seed_run: ProjectRun,
) -> None:
    """Scenario 7: resume does not duplicate PR/deploy and continues from checkpoint."""
    # Resume by idempotency key should return the same run.
    first = await create_run(
        background_tasks=BackgroundTasks(),
        project_id=seed_project.id,
        body=None,
        idempotency_key="acceptance-resume-key",
        db=db,
    )
    second = await create_run(
        background_tasks=BackgroundTasks(),
        project_id=seed_project.id,
        body=None,
        idempotency_key="acceptance-resume-key",
        db=db,
    )
    assert first.id == second.id

    # Simulate restart at PreparePR when PR already merged: must not push/merge again.
    seed_project.github_repo_url = "https://github.com/acme/id8-acceptance"
    await db.flush()
    ctx = _make_ctx(db, first, node="PreparePR")

    mock_client = MagicMock()
    mock_client.push_files = AsyncMock()
    mock_client.merge_pull_request = AsyncMock()
    merged_pr = PrInfo(
        number=9,
        html_url="https://github.com/acme/id8-acceptance/pull/9",
        state="closed",
        head_sha="head",
        title="merged",
        merged=True,
        merge_commit_sha="merge-sha",
    )
    with (
        patch("app.orchestrator.handlers.prepare_pr._ensure_branch", new=AsyncMock(return_value="main")),
        patch("app.orchestrator.handlers.prepare_pr._find_closed_pull_request", new=AsyncMock(return_value=merged_pr)),
        patch("app.orchestrator.handlers.prepare_pr._persist_prepare_pr_metadata", new=AsyncMock()),
    ):
        result = await _run_github_flow(
            ctx,
            mock_client,
            files=[{"path": "backend/app/main.py", "content": "print('ok')"}],
        )

    assert result.outcome == "success"
    mock_client.push_files.assert_not_awaited()
    mock_client.merge_pull_request.assert_not_awaited()

    # Existing DeployProduction artifact should make deploy idempotent (no duplicate deploy).
    deploy_run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.DEPLOYING,
        current_node="DeployProduction",
    )
    db.add(deploy_run)
    await db.flush()
    db.add(
        ProjectArtifact(
            project_id=seed_project.id,
            run_id=deploy_run.id,
            artifact_type=ArtifactType.DEPLOY_REPORT,
            version=1,
            content={
                "__node_name": "DeployProduction",
                "live_url": _ACCEPTANCE_LIVE_URL,
                "environment": "production",
            },
            model_profile=None,
        )
    )
    await db.flush()

    original_deploy = HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION]
    HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = _ExplodingDeployHandler()
    try:
        await run_orchestrator(deploy_run.id, db)
    finally:
        HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = original_deploy

    await db.refresh(deploy_run)
    assert deploy_run.current_node == "EndSuccess"

    deploy_artifacts_result = await db.execute(
        select(ProjectArtifact).where(
            ProjectArtifact.run_id == deploy_run.id,
            ProjectArtifact.artifact_type == ArtifactType.DEPLOY_REPORT,
        )
    )
    deploy_artifacts = deploy_artifacts_result.scalars().all()
    assert len(deploy_artifacts) == 1


@pytest.mark.asyncio
async def test_scenario_8_secret_safety(
    db: AsyncSession,
    seed_run: ProjectRun,
) -> None:
    """Scenario 8: only publishable keys flow to frontend/runtime and audit payloads."""
    env_vars = {
        "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": "anon-key",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        "INTERNAL_API_TOKEN": "internal-token",
    }
    filtered = filter_env_vars(env_vars)
    assert set(filtered.keys()) == {
        "NEXT_PUBLIC_SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    }
    assert_no_secrets(filtered)
    with pytest.raises(ValueError):
        assert_no_secrets(env_vars)

    auth = StitchAuthContext(
        auth_method=StitchAuthMethod.API_KEY,
        api_key="super-secret-api-key",
    )
    redacted = auth.redacted_summary()
    assert redacted == {"auth_method": "api_key"}
    assert "super-secret-api-key" not in json.dumps(redacted)

    ctx = _make_ctx(db, seed_run, node="DeployProduction")
    await _record_env_injection_audit(ctx, filtered.keys())
    await db.flush()

    event_result = await db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.project_id == seed_run.project_id,
            AuditEvent.event_type == "deploy.env_vars_injected",
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    event = event_result.scalar_one()
    assert set(event.event_payload["keys"]) == set(filtered.keys())
    assert "service-role-secret" not in json.dumps(event.event_payload)
    assert "internal-token" not in json.dumps(event.event_payload)
