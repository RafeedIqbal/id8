"""Tests for the ID8 orchestrator state machine.

Exercises the engine, transition table, retry logic, idempotency, and
project-status synchronisation against a real (transactional) PostgreSQL
session — same pattern used in test_routes.py.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.llm.client import LlmResponse, TokenUsage
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.retry_job import RetryJob
from app.models.user import User
from app.orchestrator.base import NodeHandler, NodeResult, RunContext
from app.orchestrator.engine import run_orchestrator
from app.orchestrator.handlers.registry import HANDLER_REGISTRY
from app.orchestrator.nodes import NODE_TO_PROJECT_STATUS, NodeName
from app.orchestrator.retry import RateLimitError, RetryableError
from app.orchestrator.transitions import TRANSITIONS, resolve_next_node

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8_test",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_VALID_PRD_JSON = json.dumps(
    {
        "executive_summary": "A lightweight todo app.",
        "user_stories": [
            {"persona": "User", "action": "create tasks", "benefit": "track work"},
            {"persona": "User", "action": "tag tasks", "benefit": "organize priorities"},
            {"persona": "Manager", "action": "review tasks", "benefit": "monitor progress"},
        ],
        "scope_boundaries": {
            "in_scope": ["Task CRUD", "Tags"],
            "out_of_scope": ["Realtime sync"],
        },
        "entity_list": [
            {"name": "Task", "description": "A unit of work"},
            {"name": "Tag", "description": "A task label"},
        ],
        "non_goals": ["Native mobile app"],
    }
)

_VALID_DESIGN_JSON = json.dumps(
    {
        "screens": [
            {
                "id": "screen-1",
                "name": "Dashboard",
                "description": "Main dashboard screen",
                "components": [
                    {
                        "id": "comp-1",
                        "name": "TaskList",
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
        "folder_structure": {"backend": {"app": {"main.py": "FastAPI entrypoint"}}},
        "database_schema": {"tasks": {"columns": {"id": "uuid"}}},
        "api_routes": [
            {"method": "GET", "path": "/tasks", "description": "List tasks"},
        ],
        "component_hierarchy": {"App": {"Dashboard": "Main dashboard"}},
        "dependencies": [{"name": "fastapi", "version": "^0.110.0"}],
        "deployment_config": {"backend": {"runtime": "python"}},
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture(autouse=True)
def mock_generate_prd_llm() -> None:
    """Avoid external LLM dependency in orchestrator tests."""
    mock = AsyncMock(
        return_value=LlmResponse(
            content=_VALID_PRD_JSON,
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
            model_id="mock-gemini",
            latency_ms=1.0,
            profile_used=ModelProfile.PRIMARY,
        )
    )
    with patch("app.orchestrator.handlers.generate_prd.generate_with_fallback", mock):
        yield


@pytest.fixture(autouse=True)
def mock_generate_design_llm() -> None:
    """Avoid external LLM dependency for internal design generation."""
    mock = AsyncMock(
        return_value=LlmResponse(
            content=_VALID_DESIGN_JSON,
            token_usage=TokenUsage(prompt_tokens=12, completion_tokens=34),
            model_id="mock-gemini-design",
            latency_ms=1.0,
            profile_used=ModelProfile.CUSTOMTOOLS,
        )
    )
    with patch("app.design.internal_spec._generate_with_fallback", mock):
        yield


@pytest.fixture(autouse=True)
def mock_generate_tech_plan_llm() -> None:
    """Avoid external LLM dependency in tech-plan generation."""
    mock = AsyncMock(
        return_value=LlmResponse(
            content=_VALID_TECH_PLAN_JSON,
            token_usage=TokenUsage(prompt_tokens=20, completion_tokens=40),
            model_id="mock-gemini-tech-plan",
            latency_ms=1.0,
            profile_used=ModelProfile.PRIMARY,
        )
    )
    with patch("app.orchestrator.handlers.generate_tech_plan.generate_with_fallback", mock):
        yield


@pytest_asyncio.fixture
async def seed_user(db: AsyncSession) -> User:
    user = User(id=_SCAFFOLD_USER_ID, email="test-orch@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build me a todo app",
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


async def _seed_internal_design_pending(db: AsyncSession, run: ProjectRun, version: int = 1) -> None:
    db.add(
        ProjectArtifact(
            project_id=run.project_id,
            run_id=run.id,
            artifact_type="design_spec",
            version=version,
            content={
                "status": "pending",
                "provider": "internal_spec",
            },
            model_profile=ModelProfile.CUSTOMTOOLS,
        )
    )
    await db.flush()


# ---------------------------------------------------------------------------
# 1. Transition table coverage
# ---------------------------------------------------------------------------


class TestTransitionTable:
    """Verify every entry in TRANSITIONS resolves correctly."""

    @pytest.mark.parametrize(
        "node,outcome,expected",
        [
            (row_node, outcome, next_node)
            for row_node, outcomes in TRANSITIONS.items()
            for outcome, next_node in outcomes.items()
        ],
    )
    def test_resolve_next_node(self, node: str, outcome: str, expected: str) -> None:
        assert resolve_next_node(node, outcome) == expected

    def test_resolve_next_node_normalizes_outcome_key(self) -> None:
        assert resolve_next_node("WriteCode", " FAILURE ") == "EndFailed"

    def test_resolve_next_node_allows_failed_failure_alias(self) -> None:
        assert resolve_next_node("WriteCode", "failed") == "EndFailed"


# ---------------------------------------------------------------------------
# 2. Happy path — IngestPrompt → WaitPRDApproval (parks)
# ---------------------------------------------------------------------------


class TestHappyPathParksAtWait:
    @pytest.mark.asyncio
    async def test_orchestrator_parks_at_wait_node(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        await run_orchestrator(seed_run.id, db)
        await db.refresh(seed_run)

        # Should advance through IngestPrompt → GeneratePRD → WaitPRDApproval
        assert seed_run.current_node == "WaitPRDApproval"

    @pytest.mark.asyncio
    async def test_project_status_synced(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await run_orchestrator(seed_run.id, db)
        await db.refresh(seed_project)

        # WaitPRDApproval maps to prd_draft
        assert seed_project.status == ProjectStatus.PRD_DRAFT


# ---------------------------------------------------------------------------
# 3. Approval resumes run
# ---------------------------------------------------------------------------


class TestApprovalResumesRun:
    @pytest.mark.asyncio
    async def test_approved_advances_past_wait(
        self, db: AsyncSession, seed_run: ProjectRun, seed_user: User
    ) -> None:
        # Run until it parks at WaitPRDApproval
        await run_orchestrator(seed_run.id, db)
        assert seed_run.current_node == "WaitPRDApproval"

        # Inject approval
        approval = ApprovalEvent(
            project_id=seed_run.project_id,
            run_id=seed_run.id,
            stage=ApprovalStage.PRD,
            decision="approved",
            created_by=seed_user.id,
        )
        db.add(approval)
        await db.flush()
        await _seed_internal_design_pending(db, seed_run)

        # Resume
        await run_orchestrator(seed_run.id, db)
        await db.refresh(seed_run)

        # Should advance through GenerateDesign → WaitDesignApproval
        assert seed_run.current_node == "WaitDesignApproval"


# ---------------------------------------------------------------------------
# 4. Rejection loops back
# ---------------------------------------------------------------------------


class TestRejectionLoopsBack:
    @pytest.mark.asyncio
    async def test_rejected_loops_to_generation_node(
        self, db: AsyncSession, seed_run: ProjectRun, seed_user: User
    ) -> None:
        # Park at WaitPRDApproval
        await run_orchestrator(seed_run.id, db)
        assert seed_run.current_node == "WaitPRDApproval"

        # Inject rejection
        rejection = ApprovalEvent(
            project_id=seed_run.project_id,
            run_id=seed_run.id,
            stage=ApprovalStage.PRD,
            decision="rejected",
            notes="Needs more detail",
            created_by=seed_user.id,
        )
        db.add(rejection)
        await db.flush()

        # Resume
        await run_orchestrator(seed_run.id, db)
        await db.refresh(seed_run)

        # Should loop back through GeneratePRD → WaitPRDApproval again
        assert seed_run.current_node == "WaitPRDApproval"

        artifact_result = await db.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.run_id == seed_run.id,
                ProjectArtifact.artifact_type == "prd",
            )
            .order_by(ProjectArtifact.version.asc())
        )
        artifacts = artifact_result.scalars().all()
        assert len(artifacts) == 2
        assert [a.version for a in artifacts] == [1, 2]


# ---------------------------------------------------------------------------
# 5. Full happy path to EndSuccess
# ---------------------------------------------------------------------------


class TestFullHappyPath:
    @pytest.mark.asyncio
    async def test_full_run_to_end_success(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project, seed_user: User
    ) -> None:
        original_write_code = HANDLER_REGISTRY[NodeName.WRITE_CODE]
        original_security_gate = HANDLER_REGISTRY[NodeName.SECURITY_GATE]
        original_prepare_pr = HANDLER_REGISTRY[NodeName.PREPARE_PR]
        original_deploy = HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION]
        HANDLER_REGISTRY[NodeName.WRITE_CODE] = _WriteCodeSuccessHandler()
        HANDLER_REGISTRY[NodeName.SECURITY_GATE] = _SecurityGatePassHandler()
        HANDLER_REGISTRY[NodeName.PREPARE_PR] = _PreparePrSuccessHandler()
        HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = _DeploySuccessHandler()

        try:
            # Walk through all nodes with approvals
            stages = [
                (ApprovalStage.PRD, "WaitPRDApproval"),
                (ApprovalStage.DESIGN, "WaitDesignApproval"),
                (ApprovalStage.TECH_PLAN, "WaitTechPlanApproval"),
                (ApprovalStage.DEPLOY, "WaitDeployApproval"),
            ]

            # First run parks at WaitPRDApproval
            await run_orchestrator(seed_run.id, db)
            await _seed_internal_design_pending(db, seed_run)

            for stage, expected_wait in stages:
                await db.refresh(seed_run)
                assert seed_run.current_node == expected_wait, (
                    f"Expected {expected_wait}, got {seed_run.current_node}"
                )

                approval = ApprovalEvent(
                    project_id=seed_run.project_id,
                    run_id=seed_run.id,
                    stage=stage,
                    decision="approved",
                    created_by=seed_user.id,
                )
                db.add(approval)
                await db.flush()

                await run_orchestrator(seed_run.id, db)

            await db.refresh(seed_run)
            assert seed_run.current_node == "EndSuccess"
            assert seed_run.status == ProjectStatus.DEPLOYED

            await db.refresh(seed_project)
            assert seed_project.status == ProjectStatus.DEPLOYED
        finally:
            HANDLER_REGISTRY[NodeName.WRITE_CODE] = original_write_code
            HANDLER_REGISTRY[NodeName.SECURITY_GATE] = original_security_gate
            HANDLER_REGISTRY[NodeName.PREPARE_PR] = original_prepare_pr
            HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = original_deploy


# ---------------------------------------------------------------------------
# 6. Idempotency — no duplicate artifacts
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_no_duplicate_artifacts(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        # Run orchestrator twice
        await run_orchestrator(seed_run.id, db)
        await run_orchestrator(seed_run.id, db)

        # Count PRD artifacts for this run — should be exactly 1
        result = await db.execute(
            select(ProjectArtifact).where(
                ProjectArtifact.run_id == seed_run.id,
                ProjectArtifact.artifact_type == "prd",
            )
        )
        artifacts = result.scalars().all()
        assert len(artifacts) == 1

    @pytest.mark.asyncio
    async def test_failed_deploy_checkpoint_does_not_skip_deploy(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        seed_run.current_node = "DeployProduction"
        seed_run.status = ProjectStatus.DEPLOYING
        db.add(
            ProjectArtifact(
                project_id=seed_run.project_id,
                run_id=seed_run.id,
                artifact_type="deploy_report",
                version=1,
                content={
                    "__node_name": "DeployProduction",
                    "live_url": None,
                    "environment": "production",
                    "error": "previous deploy failed",
                },
                model_profile=None,
            )
        )
        await db.flush()

        original_deploy = HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION]
        HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = _DeploySuccessHandler()
        try:
            await run_orchestrator(seed_run.id, db)
            await db.refresh(seed_run)
            assert seed_run.current_node == "EndSuccess"

            artifact_result = await db.execute(
                select(ProjectArtifact)
                .where(
                    ProjectArtifact.run_id == seed_run.id,
                    ProjectArtifact.artifact_type == "deploy_report",
                )
                .order_by(ProjectArtifact.version.asc())
            )
            deploy_artifacts = artifact_result.scalars().all()
            assert len(deploy_artifacts) == 2
            assert deploy_artifacts[-1].content["live_url"] == "https://example.test"
            assert "error" not in deploy_artifacts[-1].content
        finally:
            HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = original_deploy

    @pytest.mark.asyncio
    async def test_successful_deploy_checkpoint_still_skips(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        seed_run.current_node = "DeployProduction"
        seed_run.status = ProjectStatus.DEPLOYING
        db.add(
            ProjectArtifact(
                project_id=seed_run.project_id,
                run_id=seed_run.id,
                artifact_type="deploy_report",
                version=1,
                content={
                    "__node_name": "DeployProduction",
                    "live_url": "https://example.test",
                    "environment": "production",
                },
                model_profile=None,
            )
        )
        await db.flush()

        original_deploy = HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION]
        HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = _ExplodingDeployHandler()
        try:
            await run_orchestrator(seed_run.id, db)
            await db.refresh(seed_run)
            assert seed_run.current_node == "EndSuccess"

            artifact_result = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.run_id == seed_run.id,
                    ProjectArtifact.artifact_type == "deploy_report",
                )
            )
            deploy_artifacts = artifact_result.scalars().all()
            assert len(deploy_artifacts) == 1
        finally:
            HANDLER_REGISTRY[NodeName.DEPLOY_PRODUCTION] = original_deploy


# ---------------------------------------------------------------------------
# 7. Retry logic
# ---------------------------------------------------------------------------


class _FailingHandler(NodeHandler):
    """A handler that always raises a RetryableError."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        raise RetryableError("Simulated transient error")


class _RateLimitedHandler(NodeHandler):
    """A handler that always raises a rate-limit error with retry-after."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        raise RateLimitError("Rate limited", retry_after_seconds=15.0)


class _LlmTelemetryHandler(NodeHandler):
    """A handler that emits artifact + LLM telemetry."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={"title": "Generated PRD", "source": "llm"},
            llm_response=LlmResponse(
                content="# PRD",
                token_usage=TokenUsage(prompt_tokens=123, completion_tokens=456),
                model_id="gemini-3.1-pro-preview",
                latency_ms=321.0,
                profile_used=ModelProfile.PRIMARY,
            ),
        )


class _PreparePrSuccessHandler(NodeHandler):
    """Deterministic PreparePR replacement for orchestrator unit tests."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(outcome="success")


class _DeploySuccessHandler(NodeHandler):
    """Deterministic DeployProduction replacement for orchestrator unit tests."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="passed",
            artifact_data={"live_url": "https://example.test", "environment": "production"},
        )


class _ExplodingDeployHandler(NodeHandler):
    """Raises immediately if DeployProduction executes unexpectedly."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        raise AssertionError("DeployProduction handler should not run for reusable checkpoints")


class _WriteCodeSuccessHandler(NodeHandler):
    """Deterministic WriteCode replacement to avoid real LLM calls in tests."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        return NodeResult(
            outcome="success",
            artifact_data={
                "files": [
                    {
                        "path": "backend/app/main.py",
                        "content": "from fastapi import FastAPI\n\napp = FastAPI()\n",
                        "language": "python",
                    }
                ]
            },
        )


class _SecurityGatePassHandler(NodeHandler):
    """Deterministic SecurityGate replacement to avoid scanner subprocesses in tests."""

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


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retryable_error_creates_retry_job(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        # Replace IngestPrompt handler with one that always fails
        original = HANDLER_REGISTRY[NodeName.INGEST_PROMPT]
        HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = _FailingHandler()

        try:
            await run_orchestrator(seed_run.id, db)
            await db.refresh(seed_run)

            # Run should still be at IngestPrompt (not advanced)
            assert seed_run.current_node == "IngestPrompt"
            assert seed_run.retry_count == 1

            # A RetryJob should have been created
            result = await db.execute(
                select(RetryJob).where(RetryJob.run_id == seed_run.id)
            )
            jobs = result.scalars().all()
            assert len(jobs) == 1
            assert jobs[0].node_name == "IngestPrompt"
            assert jobs[0].retry_attempt == 1
            retry_delay = (jobs[0].scheduled_for - datetime.now(tz=UTC)).total_seconds()
            assert 1.0 <= retry_delay <= 5.0
        finally:
            HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = original


# ---------------------------------------------------------------------------
# 8. Rate-limit retry delay
# ---------------------------------------------------------------------------


class TestRateLimitDelay:
    @pytest.mark.asyncio
    async def test_rate_limit_uses_retry_after_delay(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        original = HANDLER_REGISTRY[NodeName.INGEST_PROMPT]
        HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = _RateLimitedHandler()

        try:
            await run_orchestrator(seed_run.id, db)

            result = await db.execute(
                select(RetryJob).where(RetryJob.run_id == seed_run.id)
            )
            job = result.scalar_one()
            retry_delay = (job.scheduled_for - datetime.now(tz=UTC)).total_seconds()
            assert 13.0 <= retry_delay <= 16.0
            assert job.payload["model_profile"] == "fallback"
            assert job.payload["retry_after_seconds"] == 15.0
        finally:
            HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = original


# ---------------------------------------------------------------------------
# 9. Retry exhaustion
# ---------------------------------------------------------------------------


class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_exhaustion_transitions_to_end_failed(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        original = HANDLER_REGISTRY[NodeName.INGEST_PROMPT]
        HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = _FailingHandler()

        try:
            # Simulate 1 initial attempt + 3 retries
            for _ in range(4):
                await run_orchestrator(seed_run.id, db)

            await db.refresh(seed_run)
            assert seed_run.current_node == "EndFailed"
            assert seed_run.status == ProjectStatus.FAILED
        finally:
            HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = original


# ---------------------------------------------------------------------------
# 10. LLM telemetry persistence
# ---------------------------------------------------------------------------


class TestLlmTelemetryPersistence:
    @pytest.mark.asyncio
    async def test_artifact_persists_llm_metadata(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        original = HANDLER_REGISTRY[NodeName.GENERATE_PRD]
        HANDLER_REGISTRY[NodeName.GENERATE_PRD] = _LlmTelemetryHandler()

        try:
            await run_orchestrator(seed_run.id, db)

            result = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.run_id == seed_run.id,
                    ProjectArtifact.artifact_type == "prd",
                )
            )
            artifact = result.scalar_one()

            assert artifact.model_profile == ModelProfile.PRIMARY
            assert artifact.content["__llm_metadata"]["model_id"] == "gemini-3.1-pro-preview"
            assert artifact.content["__llm_metadata"]["prompt_tokens"] == 123
            assert artifact.content["__llm_metadata"]["completion_tokens"] == 456
            assert artifact.content["__llm_metadata"]["latency_ms"] == 321.0
        finally:
            HANDLER_REGISTRY[NodeName.GENERATE_PRD] = original


# ---------------------------------------------------------------------------
# 11. Resume from failure
# ---------------------------------------------------------------------------


class TestResumeFromFailure:
    @pytest.mark.asyncio
    async def test_resume_from_specific_node(
        self, db: AsyncSession, seed_project: Project, seed_user: User
    ) -> None:
        # Create a run that starts at GenerateDesign (simulating resume)
        run = ProjectRun(
            project_id=seed_project.id,
            status=ProjectStatus.IDEATION,
            current_node="GenerateDesign",
        )
        db.add(run)
        await db.flush()
        db.add(
            ProjectArtifact(
                project_id=seed_project.id,
                run_id=run.id,
                artifact_type="prd",
                version=1,
                content={
                    "__node_name": "GeneratePRD",
                    "executive_summary": "A lightweight todo app.",
                    "user_stories": [
                        {"persona": "User", "action": "create tasks", "benefit": "track work"},
                    ],
                    "entity_list": [{"name": "Task", "description": "A unit of work"}],
                },
                model_profile=ModelProfile.PRIMARY,
            )
        )
        await _seed_internal_design_pending(db, run)

        await run_orchestrator(run.id, db)
        await db.refresh(run)

        # Should advance through GenerateDesign → WaitDesignApproval
        assert run.current_node == "WaitDesignApproval"


# ---------------------------------------------------------------------------
# 12. Project status sync per node
# ---------------------------------------------------------------------------


class TestProjectStatusSync:
    @pytest.mark.asyncio
    async def test_status_matches_node(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await run_orchestrator(seed_run.id, db)
        await db.refresh(seed_project)

        expected = NODE_TO_PROJECT_STATUS[NodeName(seed_run.current_node)]
        assert seed_project.status == expected
