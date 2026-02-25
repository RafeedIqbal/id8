"""Tests for tech plan generation (Task 07).

Tests the GenerateTechPlan handler with mocked LLM calls.
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
from app.orchestrator.handlers.generate_tech_plan import GenerateTechPlanHandler
from app.schemas.tech_plan import TechPlanContent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000077")


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
    user = User(id=_SCAFFOLD_USER_ID, email="test-techplan@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build me a todo app with user auth and tagging",
        status=ProjectStatus.DESIGN_APPROVED,
    )
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def seed_run(db: AsyncSession, seed_project: Project) -> ProjectRun:
    run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.DESIGN_APPROVED,
        current_node="GenerateTechPlan",
    )
    db.add(run)
    await db.flush()
    return run


# A valid tech plan JSON that matches TechPlanContent schema.
_VALID_TECH_PLAN = {
    "folder_structure": {
        "src": {
            "app": {"main.py": "FastAPI entrypoint", "models": {}, "routes": {}},
            "tests": {"test_main.py": "Main test file"},
        }
    },
    "database_schema": {
        "users": {
            "columns": {"id": "uuid PK", "email": "text UNIQUE", "created_at": "timestamptz"},
            "indexes": ["idx_users_email"],
        },
        "tasks": {
            "columns": {"id": "uuid PK", "title": "text", "user_id": "uuid FK(users.id)"},
            "indexes": ["idx_tasks_user_id"],
        },
    },
    "api_routes": [
        {"method": "POST", "path": "/auth/login", "description": "Authenticate user"},
        {"method": "GET", "path": "/tasks", "description": "List user tasks"},
        {"method": "POST", "path": "/tasks", "description": "Create a new task"},
        {"method": "PUT", "path": "/tasks/{id}", "description": "Update a task"},
        {"method": "DELETE", "path": "/tasks/{id}", "description": "Delete a task"},
    ],
    "component_hierarchy": {
        "App": {
            "AuthProvider": {"LoginPage": "Login form", "RegisterPage": "Registration form"},
            "Dashboard": {"TaskList": "List of tasks", "TaskForm": "Create/edit task form"},
        }
    },
    "dependencies": [
        {"name": "fastapi", "version": "^0.110.0"},
        {"name": "sqlalchemy", "version": "^2.0.0"},
        {"name": "next", "version": "^14.0.0"},
        {"name": "react", "version": "^18.0.0"},
    ],
    "deployment_config": {
        "backend": {"platform": "Supabase", "runtime": "Python 3.12"},
        "frontend": {"platform": "Vercel", "framework": "Next.js"},
        "ci_cd": {"provider": "GitHub Actions", "branches": ["main"]},
    },
}

_VALID_TECH_PLAN_JSON = json.dumps(_VALID_TECH_PLAN)

_SAMPLE_PRD = {
    "executive_summary": "A todo application with auth and tagging.",
    "user_stories": [
        {"persona": "Busy professional", "action": "create and tag tasks", "benefit": "stay organized"},
    ],
    "scope_boundaries": {"in_scope": ["Task CRUD", "User auth"], "out_of_scope": []},
    "entity_list": [{"name": "Task", "description": "A todo item"}],
    "non_goals": ["Offline support"],
}

_SAMPLE_DESIGN = {
    "screens": [{"name": "Dashboard", "components": ["TaskList", "TaskForm"]}],
    "metadata": {"provider": "internal_spec"},
}


def _make_ctx(
    db: AsyncSession,
    run: ProjectRun,
    node: str = "GenerateTechPlan",
    previous_artifacts: dict | None = None,
    workflow_payload: dict | None = None,
) -> RunContext:
    return RunContext(
        run_id=run.id,
        project_id=run.project_id,
        current_node=node,
        attempt=0,
        db_session=db,
        previous_artifacts=previous_artifacts or {"prd": _SAMPLE_PRD, "design_spec": _SAMPLE_DESIGN},
        workflow_payload=workflow_payload or {},
    )


def _mock_llm_response(content: str = _VALID_TECH_PLAN_JSON) -> LlmResponse:
    return LlmResponse(
        content=content,
        token_usage=TokenUsage(prompt_tokens=300, completion_tokens=800),
        model_id="gemini-3.1-pro-preview",
        latency_ms=1200.0,
        profile_used=ModelProfile.PRIMARY,
    )


# ---------------------------------------------------------------------------
# 1. TechPlanContent schema tests
# ---------------------------------------------------------------------------


class TestTechPlanContentSchema:
    def test_valid_plan_parses(self) -> None:
        plan = TechPlanContent.model_validate(_VALID_TECH_PLAN)
        assert len(plan.api_routes) == 5
        assert plan.api_routes[0].method == "POST"
        assert plan.api_routes[0].path == "/auth/login"
        assert len(plan.dependencies) == 4
        assert plan.dependencies[0].name == "fastapi"
        assert "users" in plan.database_schema
        assert "src" in plan.folder_structure

    def test_missing_field_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TechPlanContent.model_validate({"folder_structure": {}})

    def test_empty_api_routes_valid(self) -> None:
        data = {**_VALID_TECH_PLAN, "api_routes": []}
        plan = TechPlanContent.model_validate(data)
        assert plan.api_routes == []

    def test_api_route_requires_method_path_description(self) -> None:
        from pydantic import ValidationError

        data = {**_VALID_TECH_PLAN, "api_routes": [{"method": "GET"}]}
        with pytest.raises(ValidationError):
            TechPlanContent.model_validate(data)


# ---------------------------------------------------------------------------
# 2. GenerateTechPlan handler tests
# ---------------------------------------------------------------------------


class TestGenerateTechPlanHandler:
    @pytest.mark.asyncio
    async def test_success_produces_valid_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.artifact_data is not None
        assert result.llm_response is not None

        # Artifact data should be valid against TechPlanContent
        plan = TechPlanContent.model_validate(result.artifact_data)
        assert len(plan.api_routes) >= 1
        assert len(plan.dependencies) >= 1
        assert plan.folder_structure

    @pytest.mark.asyncio
    async def test_llm_called_with_correct_profile(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["profile"] == ModelProfile.PRIMARY
        assert call_kwargs["node_name"] == "GenerateTechPlan"

    @pytest.mark.asyncio
    async def test_prd_and_design_included_in_prompt(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        call_kwargs = mock_gen.call_args.kwargs
        # PRD content should be in the prompt
        assert "todo application" in call_kwargs["prompt"].lower()
        # Design content should be in the prompt
        assert "dashboard" in call_kwargs["prompt"].lower()

    @pytest.mark.asyncio
    async def test_token_usage_on_response(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.llm_response.token_usage.prompt_tokens == 300
        assert result.llm_response.token_usage.completion_tokens == 800

    @pytest.mark.asyncio
    async def test_json_in_markdown_fences_still_parsed(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        """LLM sometimes wraps JSON in ```json ... ``` fences."""
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)
        fenced_content = f"```json\n{_VALID_TECH_PLAN_JSON}\n```"

        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(fenced_content),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.artifact_data is not None

    @pytest.mark.asyncio
    async def test_invalid_json_retries_then_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("This is not JSON at all"),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.artifact_data is None
        assert result.error is not None
        assert "schema validation failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_prd_artifact_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run, previous_artifacts={})

        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "prd" in result.error.lower()

    @pytest.mark.asyncio
    async def test_works_without_design_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        """Tech plan should still generate if design_spec is missing."""
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run, previous_artifacts={"prd": _SAMPLE_PRD})

        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"


# ---------------------------------------------------------------------------
# 3. Rejection feedback loop
# ---------------------------------------------------------------------------


class TestRejectionFeedback:
    @pytest.mark.asyncio
    async def test_feedback_included_in_prompt_on_rejection(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project, seed_user: User
    ) -> None:
        rejection = ApprovalEvent(
            project_id=seed_project.id,
            run_id=seed_run.id,
            stage=ApprovalStage.TECH_PLAN,
            decision="rejected",
            notes="Need more detail on database indexes and API pagination",
            created_by=seed_user.id,
        )
        db.add(rejection)
        await db.flush()

        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            mock_gen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"

        call_kwargs = mock_gen.call_args.kwargs
        assert "database indexes" in call_kwargs["prompt"].lower()
        assert "rejected" in call_kwargs["prompt"].lower()

    @pytest.mark.asyncio
    async def test_no_feedback_when_no_rejection(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateTechPlanHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.generate_tech_plan.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        call_kwargs = mock_gen.call_args.kwargs
        assert "rejected" not in call_kwargs["prompt"].lower()
        assert "feedback" not in call_kwargs["prompt"].lower()


# ---------------------------------------------------------------------------
# 4. Prompt template tests
# ---------------------------------------------------------------------------


class TestTechPlanPromptTemplates:
    def test_basic_prompt_includes_prd_and_design(self) -> None:
        from app.llm.prompts.tech_plan_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={"prd": _SAMPLE_PRD, "design_spec": _SAMPLE_DESIGN},
        )
        assert "JSON" in system
        assert "folder_structure" in system
        assert "todo application" in user.lower()
        assert "dashboard" in user.lower()

    def test_prompt_with_feedback(self) -> None:
        from app.llm.prompts.tech_plan_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={"prd": _SAMPLE_PRD, "design_spec": _SAMPLE_DESIGN},
            feedback="Add caching strategy",
        )
        assert "Add caching strategy" in user
        assert "rejected" in user.lower()

    def test_prompt_without_design(self) -> None:
        from app.llm.prompts.tech_plan_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={"prd": _SAMPLE_PRD},
        )
        assert "not available" in user.lower()

    def test_internal_metadata_stripped(self) -> None:
        from app.llm.prompts.tech_plan_generation import build_prompts

        prd_with_meta = {**_SAMPLE_PRD, "__node_name": "GeneratePRD", "__llm_metadata": {}}
        _, user = build_prompts(previous_artifacts={"prd": prd_with_meta})
        assert "__node_name" not in user
        assert "__llm_metadata" not in user
