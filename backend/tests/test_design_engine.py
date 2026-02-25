"""Tests for Design Engine (Task 06).

Tests design providers, provider factory fallback, and the GenerateDesign handler.
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

from app.design.base import (
    DesignFeedback,
    DesignOutput,
    Screen,
    ScreenComponent,
    StitchAuthContext,
    StitchAuthError,
    StitchAuthMethod,
    StitchRuntimeError,
)
from app.design.internal_spec import InternalSpecProvider, _parse_llm_response
from app.design.provider_factory import (
    generate_with_fallback,
    get_provider,
    regenerate_with_fallback,
)
from app.design.stitch_mcp import STITCH_TOOLS, StitchMcpProvider
from app.llm.client import LlmResponse, TokenUsage
from app.models.approval_event import ApprovalEvent
from app.models.enums import (
    ApprovalStage,
    DesignProvider,
    ModelProfile,
    ProjectStatus,
)
from app.models.project import Project
from app.models.project_run import ProjectRun
from app.models.user import User
from app.orchestrator.base import RunContext
from app.orchestrator.handlers.generate_design import GenerateDesignHandler

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000098")


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
    user = User(id=_SCAFFOLD_USER_ID, email="test-design@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build me a todo app with user auth and tagging",
        status=ProjectStatus.PRD_APPROVED,
    )
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def seed_run(db: AsyncSession, seed_project: Project) -> ProjectRun:
    run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.PRD_APPROVED,
        current_node="GenerateDesign",
    )
    db.add(run)
    await db.flush()
    return run


def _make_ctx(
    db: AsyncSession,
    run: ProjectRun,
    node: str = "GenerateDesign",
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


# Sample data
_VALID_PRD = {
    "executive_summary": "A todo application with auth and tagging.",
    "user_stories": [
        {"persona": "Busy professional", "action": "create and tag tasks", "benefit": "stay organized"},
        {"persona": "Team lead", "action": "view team tasks", "benefit": "track progress"},
        {"persona": "Mobile user", "action": "manage tasks on the go", "benefit": "productivity"},
    ],
    "scope_boundaries": {
        "in_scope": ["Task CRUD", "User auth", "Tagging"],
        "out_of_scope": ["Calendar integration"],
    },
    "entity_list": [
        {"name": "Task", "description": "A todo item"},
        {"name": "User", "description": "An authenticated user"},
        {"name": "Tag", "description": "A label for tasks"},
    ],
    "non_goals": ["Offline support"],
}

_VALID_DESIGN_JSON = json.dumps({
    "screens": [
        {
            "id": "screen-1",
            "name": "Dashboard",
            "description": "Main dashboard showing tasks",
            "components": [
                {"id": "comp-1", "name": "TaskList", "type": "table", "properties": {}},
                {"id": "comp-2", "name": "AddButton", "type": "button", "properties": {"label": "Add Task"}},
            ],
            "assets": [],
        },
        {
            "id": "screen-2",
            "name": "Login",
            "description": "User login page",
            "components": [
                {"id": "comp-3", "name": "LoginForm", "type": "form", "properties": {}},
            ],
            "assets": [],
        },
    ]
})

_STITCH_RESPONSE = {
    "screens": [
        {
            "id": "stitch-screen-1",
            "name": "Home",
            "description": "Generated by Stitch",
            "components": [
                {"id": "sc-1", "name": "Header", "type": "header", "properties": {}},
            ],
            "assets": ["https://stitch.example.com/asset1.png"],
        }
    ]
}


def _mock_llm_response(content: str = _VALID_DESIGN_JSON) -> LlmResponse:
    return LlmResponse(
        content=content,
        token_usage=TokenUsage(prompt_tokens=150, completion_tokens=300),
        model_id="gemini-3.1-pro-preview-customtools",
        latency_ms=800.0,
        profile_used=ModelProfile.CUSTOMTOOLS,
    )


def _sample_auth() -> StitchAuthContext:
    return StitchAuthContext(
        auth_method=StitchAuthMethod.API_KEY,
        api_key="test-api-key-123",
    )


def _sample_design_output() -> DesignOutput:
    return DesignOutput(
        screens=[
            Screen(
                id="screen-1",
                name="Dashboard",
                description="Main view",
                components=[
                    ScreenComponent(id="comp-1", name="TaskList", type="table"),
                ],
            )
        ]
    )


# ---------------------------------------------------------------------------
# 1. Base types tests
# ---------------------------------------------------------------------------


class TestStitchAuthContext:
    def test_api_key_headers(self) -> None:
        auth = StitchAuthContext(auth_method=StitchAuthMethod.API_KEY, api_key="my-key")
        headers = auth.build_headers()
        assert headers == {"X-Goog-Api-Key": "my-key"}

    def test_oauth_headers(self) -> None:
        auth = StitchAuthContext(
            auth_method=StitchAuthMethod.OAUTH,
            oauth_token="bearer-tok",
            goog_user_project="proj-123",
        )
        headers = auth.build_headers()
        assert headers["Authorization"] == "Bearer bearer-tok"
        assert headers["X-Goog-User-Project"] == "proj-123"

    def test_redacted_summary_no_secrets(self) -> None:
        auth = StitchAuthContext(auth_method=StitchAuthMethod.API_KEY, api_key="secret-123")
        summary = auth.redacted_summary()
        assert summary == {"auth_method": "api_key"}
        assert "secret" not in str(summary)

    def test_from_mapping(self) -> None:
        auth = StitchAuthContext.from_mapping(
            {"auth_method": "api_key", "api_key": "abc123"}
        )
        assert auth is not None
        assert auth.auth_method == StitchAuthMethod.API_KEY
        assert auth.api_key == "abc123"


class TestDesignOutput:
    def test_to_dict(self) -> None:
        output = _sample_design_output()
        d = output.to_dict()
        assert len(d["screens"]) == 1
        assert d["screens"][0]["name"] == "Dashboard"
        assert d["screens"][0]["components"][0]["type"] == "table"


class TestStitchAuthError:
    def test_default_payload(self) -> None:
        err = StitchAuthError("Missing credentials")
        assert err.action_payload["error_type"] == "stitch_auth_required"
        assert len(err.action_payload["instructions"]) == 4

    def test_custom_payload(self) -> None:
        err = StitchAuthError("Custom", action_payload={"custom": True})
        assert err.action_payload == {"custom": True}


# ---------------------------------------------------------------------------
# 2. Internal spec provider tests
# ---------------------------------------------------------------------------


class TestInternalSpecLlmParsing:
    def test_valid_json_parses(self) -> None:
        output, error = _parse_llm_response(_VALID_DESIGN_JSON)
        assert output is not None
        assert error is None
        assert len(output.screens) == 2
        assert output.screens[0].name == "Dashboard"
        assert len(output.screens[0].components) == 2

    def test_markdown_fenced_json_parses(self) -> None:
        fenced = f"```json\n{_VALID_DESIGN_JSON}\n```"
        output, error = _parse_llm_response(fenced)
        assert output is not None
        assert error is None

    def test_invalid_json_returns_error(self) -> None:
        output, error = _parse_llm_response("Not JSON at all")
        assert output is None
        assert "Invalid JSON" in error

    def test_non_object_returns_error(self) -> None:
        output, error = _parse_llm_response("[1, 2, 3]")
        assert output is None
        assert "not a JSON object" in error

    def test_missing_screens_returns_empty(self) -> None:
        output, error = _parse_llm_response('{"other": "data"}')
        assert output is not None
        assert len(output.screens) == 0


class TestInternalSpecProvider:
    @pytest.mark.asyncio
    async def test_generate_success(self) -> None:
        provider = InternalSpecProvider()

        with patch(
            "app.design.internal_spec._generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            output = await provider.generate(
                prd_content=_VALID_PRD,
                constraints={"style": "modern"},
            )

        assert len(output.screens) == 2
        assert output.metadata["provider"] == "internal_spec"
        assert output.metadata["model_id"] == "gemini-3.1-pro-preview-customtools"

    @pytest.mark.asyncio
    async def test_generate_retries_on_bad_json(self) -> None:
        provider = InternalSpecProvider()

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response("not json")
            return _mock_llm_response()

        with patch(
            "app.design.internal_spec._generate_with_fallback",
            new_callable=AsyncMock,
            side_effect=side_effect,
        ):
            output = await provider.generate(prd_content=_VALID_PRD, constraints={})

        assert call_count == 2
        assert len(output.screens) == 2

    @pytest.mark.asyncio
    async def test_regenerate_includes_feedback(self) -> None:
        provider = InternalSpecProvider()
        previous = _sample_design_output()
        feedback = DesignFeedback(feedback_text="Make buttons bigger", target_screen_id="screen-1")

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch("app.design.internal_spec._generate_with_fallback", mock_gen):
            output = await provider.regenerate(previous=previous, feedback=feedback)

        assert output.metadata["feedback_text"] == "Make buttons bigger"


# ---------------------------------------------------------------------------
# 3. Stitch MCP provider tests
# ---------------------------------------------------------------------------


class TestStitchMcpProvider:
    def test_validate_auth_missing(self) -> None:
        provider = StitchMcpProvider()
        with pytest.raises(StitchAuthError):
            provider._validate_auth(None)

    def test_validate_auth_empty(self) -> None:
        provider = StitchMcpProvider()
        auth = StitchAuthContext(auth_method=StitchAuthMethod.API_KEY, api_key="")
        with pytest.raises(StitchAuthError):
            provider._validate_auth(auth)

    def test_validate_auth_valid(self) -> None:
        provider = StitchMcpProvider()
        # Should not raise
        provider._validate_auth(_sample_auth())

    def test_validate_auth_oauth_requires_user_project(self) -> None:
        provider = StitchMcpProvider()
        auth = StitchAuthContext(
            auth_method=StitchAuthMethod.OAUTH,
            oauth_token="oauth-token",
            goog_user_project="",
        )
        with pytest.raises(StitchAuthError):
            provider._validate_auth(auth)

    @pytest.mark.asyncio
    async def test_generate_calls_stitch(self) -> None:
        provider = StitchMcpProvider()
        auth = _sample_auth()

        with patch.object(
            provider,
            "_call_stitch",
            new_callable=AsyncMock,
            return_value=_STITCH_RESPONSE,
        ) as mock_call:
            output = await provider.generate(
                prd_content=_VALID_PRD,
                constraints={},
                auth=auth,
            )

        mock_call.assert_called_once()
        assert output.metadata["provider"] == "stitch_mcp"
        assert len(output.screens) == 1
        assert output.screens[0].name == "Home"

    @pytest.mark.asyncio
    async def test_regenerate_passes_feedback(self) -> None:
        provider = StitchMcpProvider()
        auth = _sample_auth()
        previous = _sample_design_output()
        feedback = DesignFeedback(
            feedback_text="Adjust header",
            target_screen_id="screen-1",
            target_component_id="comp-1",
        )

        with patch.object(
            provider,
            "_call_stitch",
            new_callable=AsyncMock,
            return_value=_STITCH_RESPONSE,
        ) as mock_call:
            output = await provider.regenerate(previous=previous, feedback=feedback, auth=auth)

        call_kwargs = mock_call.call_args.kwargs
        assert "screen_id" in call_kwargs["params"]
        assert "component_id" in call_kwargs["params"]
        assert output.metadata["feedback_text"] == "Adjust header"


class TestStitchToolInventory:
    def test_tool_list_has_expected_tools(self) -> None:
        tool_names = {t["name"] for t in STITCH_TOOLS}
        assert "create_project" in tool_names
        assert "generate_screen_from_text" in tool_names
        assert "list_screens" in tool_names
        assert len(STITCH_TOOLS) == 6


# ---------------------------------------------------------------------------
# 4. Provider factory tests
# ---------------------------------------------------------------------------


class TestProviderFactory:
    def test_get_provider_stitch(self) -> None:
        p = get_provider(DesignProvider.STITCH_MCP)
        assert isinstance(p, StitchMcpProvider)

    def test_get_provider_internal(self) -> None:
        p = get_provider(DesignProvider.INTERNAL_SPEC)
        assert isinstance(p, InternalSpecProvider)

    def test_get_provider_unknown(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            get_provider("nonexistent")

    @pytest.mark.asyncio
    async def test_fallback_on_stitch_runtime_error(self) -> None:
        """Stitch outage should automatically fall back to internal_spec."""
        stitch_mock = AsyncMock(side_effect=StitchRuntimeError("Service unavailable"))
        internal_output = _sample_design_output()
        internal_output.metadata["provider"] = "internal_spec"
        internal_mock = AsyncMock(return_value=internal_output)

        with (
            patch.object(StitchMcpProvider, "generate", stitch_mock),
            patch.object(InternalSpecProvider, "generate", internal_mock),
        ):
            output, provider_used = await generate_with_fallback(
                prd_content=_VALID_PRD,
                constraints={},
            )

        assert provider_used == DesignProvider.INTERNAL_SPEC
        stitch_mock.assert_called_once()
        internal_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_auth_error_not_swallowed(self) -> None:
        """StitchAuthError should propagate immediately, not fall back."""
        stitch_mock = AsyncMock(side_effect=StitchAuthError("Missing creds"))

        with patch.object(StitchMcpProvider, "generate", stitch_mock):
            with pytest.raises(StitchAuthError, match="Missing creds"):
                await generate_with_fallback(
                    prd_content=_VALID_PRD,
                    constraints={},
                )

    @pytest.mark.asyncio
    async def test_regenerate_fallback(self) -> None:
        stitch_mock = AsyncMock(side_effect=StitchRuntimeError("Timeout"))
        internal_output = _sample_design_output()
        internal_mock = AsyncMock(return_value=internal_output)

        previous = _sample_design_output()
        feedback = DesignFeedback(feedback_text="Fix layout")

        with (
            patch.object(StitchMcpProvider, "regenerate", stitch_mock),
            patch.object(InternalSpecProvider, "regenerate", internal_mock),
        ):
            output, provider_used = await regenerate_with_fallback(
                previous=previous,
                feedback=feedback,
            )

        assert provider_used == DesignProvider.INTERNAL_SPEC

    @pytest.mark.asyncio
    async def test_preferred_internal_skips_stitch(self) -> None:
        internal_output = _sample_design_output()
        internal_output.metadata["provider"] = "internal_spec"
        internal_mock = AsyncMock(return_value=internal_output)

        with patch.object(InternalSpecProvider, "generate", internal_mock):
            output, provider_used = await generate_with_fallback(
                prd_content=_VALID_PRD,
                constraints={},
                preferred_provider=DesignProvider.INTERNAL_SPEC,
            )

        assert provider_used == DesignProvider.INTERNAL_SPEC
        internal_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 5. GenerateDesign handler tests
# ---------------------------------------------------------------------------


class TestGenerateDesignHandler:
    @pytest.mark.asyncio
    async def test_success_with_internal_spec(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateDesignHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={"prd": _VALID_PRD},
            workflow_payload={"design_provider": DesignProvider.INTERNAL_SPEC},
        )

        with patch(
            "app.design.internal_spec._generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.artifact_data is not None
        assert len(result.artifact_data["screens"]) == 2
        assert result.artifact_data["__design_metadata"]["provider_used"] == DesignProvider.INTERNAL_SPEC

    @pytest.mark.asyncio
    async def test_missing_prd_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateDesignHandler()
        ctx = _make_ctx(db, seed_run, previous_artifacts={})

        result = await handler.execute(ctx)
        assert result.outcome == "failure"
        assert "PRD" in result.error

    @pytest.mark.asyncio
    async def test_missing_project_fails(
        self, db: AsyncSession, seed_run: ProjectRun
    ) -> None:
        handler = GenerateDesignHandler()
        ctx = RunContext(
            run_id=seed_run.id,
            project_id=uuid.uuid4(),
            current_node="GenerateDesign",
            attempt=0,
            db_session=db,
            previous_artifacts={"prd": _VALID_PRD},
        )
        result = await handler.execute(ctx)
        assert result.outcome == "failure"
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_stitch_auth_error_returns_actionable_payload(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateDesignHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={"prd": _VALID_PRD},
            workflow_payload={"design_provider": DesignProvider.STITCH_MCP},
        )

        with patch(
            "app.design.provider_factory.generate_with_fallback",
            new_callable=AsyncMock,
            side_effect=StitchAuthError("Missing credentials"),
        ) as mock_gen:
            # Patch at the module level where the handler imports from
            with patch(
                "app.orchestrator.handlers.generate_design.generate_with_fallback",
                mock_gen,
            ):
                result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.artifact_data is not None
        assert result.artifact_data["error_type"] == "stitch_auth_required"

    @pytest.mark.asyncio
    async def test_rejection_feedback_triggers_regeneration(
        self,
        db: AsyncSession,
        seed_run: ProjectRun,
        seed_project: Project,
        seed_user: User,
    ) -> None:
        # Inject a rejection event
        rejection = ApprovalEvent(
            project_id=seed_project.id,
            run_id=seed_run.id,
            stage=ApprovalStage.DESIGN,
            decision="rejected",
            notes="Navigation needs more contrast",
            created_by=seed_user.id,
        )
        db.add(rejection)
        await db.flush()

        prev_design = _sample_design_output().to_dict()
        handler = GenerateDesignHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={
                "prd": _VALID_PRD,
                "design_spec": prev_design,
            },
            workflow_payload={"design_provider": DesignProvider.INTERNAL_SPEC},
        )

        mock_regen = AsyncMock(
            return_value=(_sample_design_output(), DesignProvider.INTERNAL_SPEC)
        )
        with patch(
            "app.orchestrator.handlers.generate_design.regenerate_with_fallback",
            mock_regen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        mock_regen.assert_called_once()
        call_kwargs = mock_regen.call_args.kwargs
        assert call_kwargs["feedback"].feedback_text == "Navigation needs more contrast"

    @pytest.mark.asyncio
    async def test_design_metadata_in_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = GenerateDesignHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={"prd": _VALID_PRD},
            workflow_payload={"design_provider": DesignProvider.INTERNAL_SPEC},
        )

        with patch(
            "app.design.internal_spec._generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        meta = result.artifact_data["__design_metadata"]
        assert "provider_used" in meta
        assert "generation_time_ms" in meta

    @pytest.mark.asyncio
    async def test_reads_config_from_pending_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        """Handler should read provider config from a pending design_spec artifact."""
        handler = GenerateDesignHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={
                "prd": _VALID_PRD,
                "design_spec": {
                    "status": "pending",
                    "provider": "internal_spec",
                    "design_constraints": {"theme": "dark"},
                },
            },
        )

        mock_gen = AsyncMock(
            return_value=(_sample_design_output(), DesignProvider.INTERNAL_SPEC)
        )
        with patch(
            "app.orchestrator.handlers.generate_design.generate_with_fallback",
            mock_gen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["preferred_provider"] == "internal_spec"
        assert call_kwargs["constraints"] == {"theme": "dark"}


# ---------------------------------------------------------------------------
# 6. Design prompt template tests
# ---------------------------------------------------------------------------


class TestDesignPromptTemplates:
    def test_basic_prompt(self) -> None:
        from app.llm.prompts.design_generation import build_prompts

        system, user = build_prompts(prd_content=_VALID_PRD)
        assert "JSON" in system
        assert "screens" in system
        assert "todo" in user.lower()
        assert "Task CRUD" in user

    def test_prompt_with_feedback(self) -> None:
        from app.llm.prompts.design_generation import build_prompts

        system, user = build_prompts(
            prd_content=_VALID_PRD,
            feedback="Make the header bigger",
            target_screen_id="screen-1",
            previous_design={"screens": [{"name": "Dashboard"}]},
        )
        assert "Make the header bigger" in user
        assert "Target Screen: screen-1" in user
        assert "Dashboard" in user

    def test_prompt_with_constraints(self) -> None:
        from app.llm.prompts.design_generation import build_prompts

        system, user = build_prompts(
            prd_content=_VALID_PRD,
            constraints={"color_scheme": "blue"},
        )
        assert "color_scheme" in user


# ---------------------------------------------------------------------------
# 7. Schema validation tests
# ---------------------------------------------------------------------------


class TestDesignSchemas:
    def test_design_output_schema_validates(self) -> None:
        from app.schemas.design import DesignOutputSchema

        data = json.loads(_VALID_DESIGN_JSON)
        schema = DesignOutputSchema.model_validate(data)
        assert len(schema.screens) == 2
        assert schema.screens[0].name == "Dashboard"

    def test_design_generate_request_defaults(self) -> None:
        from app.schemas.design import DesignGenerateRequest

        req = DesignGenerateRequest()
        assert req.provider == DesignProvider.STITCH_MCP
        assert req.model_profile == ModelProfile.CUSTOMTOOLS
