"""Tests for the ID8 orchestrator state machine.

Exercises the engine, transition table, retry logic, idempotency, and
project-status synchronisation against a real (transactional) PostgreSQL
session — same pattern used in test_routes.py.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.retry_job import RetryJob
from app.models.user import User
from app.orchestrator.base import NodeHandler, NodeResult, RunContext
from app.orchestrator.engine import run_orchestrator
from app.orchestrator.handlers.registry import HANDLER_REGISTRY
from app.orchestrator.nodes import NODE_TO_PROJECT_STATUS, NodeName
from app.orchestrator.retry import RetryableError
from app.orchestrator.transitions import TRANSITIONS, resolve_next_node

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


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


# ---------------------------------------------------------------------------
# 5. Full happy path to EndSuccess
# ---------------------------------------------------------------------------


class TestFullHappyPath:
    @pytest.mark.asyncio
    async def test_full_run_to_end_success(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project, seed_user: User
    ) -> None:
        # Walk through all nodes with approvals
        stages = [
            (ApprovalStage.PRD, "WaitPRDApproval"),
            (ApprovalStage.DESIGN, "WaitDesignApproval"),
            (ApprovalStage.TECH_PLAN, "WaitTechPlanApproval"),
            (ApprovalStage.DEPLOY, "WaitDeployApproval"),
        ]

        # First run parks at WaitPRDApproval
        await run_orchestrator(seed_run.id, db)

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


# ---------------------------------------------------------------------------
# 7. Retry logic
# ---------------------------------------------------------------------------


class _FailingHandler(NodeHandler):
    """A handler that always raises a RetryableError."""
    async def execute(self, ctx: RunContext) -> NodeResult:
        raise RetryableError("Simulated transient error")


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
        finally:
            HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = original


# ---------------------------------------------------------------------------
# 8. Retry exhaustion
# ---------------------------------------------------------------------------


class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_exhaustion_transitions_to_end_failed(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        original = HANDLER_REGISTRY[NodeName.INGEST_PROMPT]
        HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = _FailingHandler()

        try:
            # Simulate 3 attempts
            for _ in range(3):
                await run_orchestrator(seed_run.id, db)

            await db.refresh(seed_run)
            assert seed_run.current_node == "EndFailed"
            assert seed_run.status == ProjectStatus.FAILED
        finally:
            HANDLER_REGISTRY[NodeName.INGEST_PROMPT] = original


# ---------------------------------------------------------------------------
# 9. Resume from failure
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

        await run_orchestrator(run.id, db)
        await db.refresh(run)

        # Should advance through GenerateDesign → WaitDesignApproval
        assert run.current_node == "WaitDesignApproval"


# ---------------------------------------------------------------------------
# 10. Project status sync per node
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
