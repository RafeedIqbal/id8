"""Tests for PRD generation (Task 05).

Tests the IngestPrompt and GeneratePRD handlers with mocked LLM calls.
"""
from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.llm.client import LlmResponse, TokenUsage
from app.models.approval_event import ApprovalEvent
from app.models.enums import ApprovalStage, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.user import User
from app.orchestrator.base import RunContext
from app.orchestrator.handlers.generate_prd import GeneratePRDHandler
from app.orchestrator.handlers.ingest_prompt import IngestPromptHandler
from app.schemas.prd import PrdContent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    conn = await _engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    yield session
    await session.close()
    await txn.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def seed_user(db: AsyncSession) -> User:
    user = User(id=_SCAFFOLD_USER_ID, email="test-prd@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build me a todo app with user auth and tagging",
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


def _make_ctx(
    db: AsyncSession,
    run: ProjectRun,
    node: str = "IngestPrompt",
    previous_artifacts: dict | None = None,
) -> RunContext:
    return RunContext(
        run_id=run.id,
        project_id=run.project_id,
        current_node=node,
        attempt=0,
        db_session=db,
        previous_artifacts=previous_artifacts or {},
    )


# A valid PRD JSON string that matches PrdContent schema.
_VALID_PRD_JSON = json.dumps(
    {
        "executive_summary": "A todo application with auth and tagging.",
        "user_stories": [
            {
                "persona": "Busy professional",
                "action": "create and tag tasks",
                "benefit": "stay organized",
            },
            {
                "persona": "Team lead",
                "action": "view team tasks by tag",
                "benefit": "track progress",
            },
            {
                "persona": "Mobile user",
                "action": "manage tasks on the go",
                "benefit": "stay productive anywhere",
            },
        ],
        "scope_boundaries": {
            "in_scope": ["Task CRUD", "User authentication", "Tag management"],
            "out_of_scope": ["Calendar integration", "Email notifications"],
        },
        "entity_list": [
            {"name": "Task", "description": "A todo item with title, status, and tags"},
            {"name": "User", "description": "An authenticated user who owns tasks"},
            {"name": "Tag", "description": "A label that can be attached to tasks"},
        ],
        "non_goals": ["Real-time collaboration", "Offline support"],
    }
)


def _mock_llm_response(content: str = _VALID_PRD_JSON) -> LlmResponse:
    return LlmResponse(
        content=content,
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=200),
        model_id="gemini-3.1-pro-preview",
        latency_ms=500.0,
        profile_used=ModelProfile.PRIMARY,
    )


# ---------------------------------------------------------------------------
# 1. PrdContent schema tests
# ---------------------------------------------------------------------------


class TestPrdContentSchema:
    def test_valid_prd_parses(self) -> None:
        data = json.loads(_VALID_PRD_JSON)
        prd = PrdContent.model_validate(data)
        assert prd.executive_summary == "A todo application with auth and tagging."
        assert len(prd.user_stories) == 3
        assert len(prd.entity_list) == 3
        assert len(prd.non_goals) == 2
        assert prd.scope_boundaries.in_scope[0] == "Task CRUD"

    def test_missing_field_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PrdContent.model_validate({"executive_summary": "test"})


# ---------------------------------------------------------------------------
# 2. IngestPrompt handler tests
# ---------------------------------------------------------------------------


class TestIngestPromptHandler:
    @pytest.mark.asyncio
    async def test_success(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = IngestPromptHandler()
        ctx = _make_ctx(db, seed_run)
        result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_empty_prompt_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        seed_project.initial_prompt = ""
        await db.flush()

        handler = IngestPromptHandler()
        ctx = _make_ctx(db, seed_run)
        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_whitespace_only_prompt_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        seed_project.initial_prompt = "   \n\t  "
        await db.flush()

        handler = IngestPromptHandler()
        ctx = _make_ctx(db, seed_run)
        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_oversized_prompt_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        seed_project.initial_prompt = "x" * 50_000
        await db.flush()

        handler = IngestPromptHandler()
        ctx = _make_ctx(db, seed_run)
        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "maximum length" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_project_fails(self, db: AsyncSession, seed_run: ProjectRun) -> None:
        handler = IngestPromptHandler()
        ctx = RunContext(
            run_id=seed_run.id,
            project_id=uuid.uuid4(),  # non-existent
            current_node="IngestPrompt",
            attempt=0,
            db_session=db,
        )
        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# 3. GeneratePRD handler tests
# ---------------------------------------------------------------------------


class TestGeneratePRDHandler:
    @pytest.mark.asyncio
    async def test_success_produces_valid_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")

        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.artifact_data is not None
        assert result.llm_response is not None

        # Artifact data should be valid against PrdContent
        prd = PrdContent.model_validate(result.artifact_data)
        assert len(prd.user_stories) >= 3
        assert prd.executive_summary

    @pytest.mark.asyncio
    async def test_llm_called_with_correct_profile(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["profile"] == ModelProfile.PRIMARY
        assert call_kwargs["node_name"] == "GeneratePRD"
        assert "todo app" in call_kwargs["prompt"].lower()

    @pytest.mark.asyncio
    async def test_token_usage_on_response(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")

        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.llm_response.token_usage.prompt_tokens == 100
        assert result.llm_response.token_usage.completion_tokens == 200

    @pytest.mark.asyncio
    async def test_json_in_markdown_fences_still_parsed(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        """LLM sometimes wraps JSON in ```json ... ``` fences."""
        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")
        fenced_content = f"```json\n{_VALID_PRD_JSON}\n```"

        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(fenced_content),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.artifact_data is not None
        assert "__parse_error" not in result.artifact_data

    @pytest.mark.asyncio
    async def test_invalid_json_retries_then_returns_raw(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")

        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("This is not JSON at all"),
        ):
            result = await handler.execute(ctx)

        # Still returns success so the engine can persist and continue
        assert result.outcome == "success"
        assert result.artifact_data is not None
        assert "__parse_error" in result.artifact_data
        assert "raw_content" in result.artifact_data


# ---------------------------------------------------------------------------
# 4. Rejection feedback loop
# ---------------------------------------------------------------------------


class TestRejectionFeedback:
    @pytest.mark.asyncio
    async def test_feedback_included_in_prompt_on_v2(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project, seed_user: User
    ) -> None:
        # Inject a rejection event
        rejection = ApprovalEvent(
            project_id=seed_project.id,
            run_id=seed_run.id,
            stage=ApprovalStage.PRD,
            decision="rejected",
            notes="Needs more user stories and clearer scope",
            created_by=seed_user.id,
        )
        db.add(rejection)
        await db.flush()

        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            mock_gen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"

        # The user prompt should contain the rejection feedback
        call_kwargs = mock_gen.call_args.kwargs
        assert "Needs more user stories" in call_kwargs["prompt"]
        assert "rejected" in call_kwargs["prompt"].lower()

    @pytest.mark.asyncio
    async def test_previous_prd_included_in_feedback_prompt(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project, seed_user: User
    ) -> None:
        rejection = ApprovalEvent(
            project_id=seed_project.id,
            run_id=seed_run.id,
            stage=ApprovalStage.PRD,
            decision="rejected",
            notes="Add mobile personas",
            created_by=seed_user.id,
        )
        db.add(rejection)
        await db.flush()

        previous_prd = {
            "executive_summary": "Previous version",
            "user_stories": [],
            "__node_name": "GeneratePRD",
        }
        handler = GeneratePRDHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            node="GeneratePRD",
            previous_artifacts={"prd": previous_prd},
        )

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        call_kwargs = mock_gen.call_args.kwargs
        # Should include previous PRD content (without internal metadata)
        assert "Previous version" in call_kwargs["prompt"]
        # Internal metadata should be stripped
        assert "__node_name" not in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_no_feedback_when_no_rejection(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GeneratePRDHandler()
        ctx = _make_ctx(db, seed_run, node="GeneratePRD")

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_prd.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        call_kwargs = mock_gen.call_args.kwargs
        # Should use the simple prompt template (no feedback)
        assert "rejected" not in call_kwargs["prompt"].lower()
        assert "todo app" in call_kwargs["prompt"].lower()


# ---------------------------------------------------------------------------
# 5. Prompt template tests (updated)
# ---------------------------------------------------------------------------


class TestPrdPromptTemplates:
    def test_basic_prompt(self) -> None:
        from app.llm.prompts.prd_generation import build_prompts

        system, user = build_prompts(initial_prompt="Build a CRM")
        assert "JSON" in system
        assert "executive_summary" in system
        assert "CRM" in user

    def test_prompt_with_feedback_and_previous(self) -> None:
        from app.llm.prompts.prd_generation import build_prompts

        system, user = build_prompts(
            initial_prompt="Build a CRM",
            feedback="Needs more detail",
            previous_artifacts={"prd": {"executive_summary": "Old PRD", "__node_name": "x"}},
        )
        assert "Needs more detail" in user
        assert "Old PRD" in user
        # Internal keys stripped
        assert "__node_name" not in user
