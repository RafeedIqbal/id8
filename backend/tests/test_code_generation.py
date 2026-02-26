"""Tests for code generation (Task 08).

Tests the WriteCode handler with mocked LLM calls, including schema
validation, security feedback loops, and basic code validation.
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
from app.models.enums import ArtifactType, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.user import User
from app.orchestrator.base import RunContext
from app.orchestrator.handlers.write_code import WriteCodeHandler
from app.schemas.code_snapshot import CodeFile, CodeSnapshotContent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000088")


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
    user = User(id=_SCAFFOLD_USER_ID, email="test-codegen@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build a task management app with auth",
        status=ProjectStatus.TECH_PLAN_APPROVED,
    )
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def seed_run(db: AsyncSession, seed_project: Project) -> ProjectRun:
    run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.TECH_PLAN_APPROVED,
        current_node="WriteCode",
    )
    db.add(run)
    await db.flush()
    return run


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_PRD = {
    "executive_summary": "A task management application with auth and tagging.",
    "user_stories": [
        {"persona": "User", "action": "create tasks", "benefit": "stay organized"},
    ],
    "scope_boundaries": {"in_scope": ["Task CRUD", "Auth"], "out_of_scope": []},
    "entity_list": [{"name": "Task", "description": "A todo item"}],
    "non_goals": ["Offline support"],
}

_SAMPLE_DESIGN = {
    "screens": [{"name": "Dashboard", "components": ["TaskList", "TaskForm"]}],
    "metadata": {"provider": "internal_spec"},
}

_SAMPLE_TECH_PLAN = {
    "folder_structure": {
        "backend": {"app": {"main.py": "", "routes": {}, "models": {}}},
        "frontend": {"src": {"pages": {}, "components": {}}},
    },
    "database_schema": {
        "users": {"columns": {"id": "uuid PK", "email": "text"}},
        "tasks": {"columns": {"id": "uuid PK", "title": "text", "user_id": "uuid FK"}},
    },
    "api_routes": [
        {"method": "POST", "path": "/auth/login", "description": "Login"},
        {"method": "GET", "path": "/tasks", "description": "List tasks"},
        {"method": "POST", "path": "/tasks", "description": "Create task"},
    ],
    "component_hierarchy": {
        "App": {"Dashboard": {"TaskList": "List", "TaskForm": "Form"}},
    },
    "dependencies": [
        {"name": "fastapi", "version": "^0.110.0"},
        {"name": "next", "version": "^14.0.0"},
    ],
    "deployment_config": {
        "backend": {"platform": "Supabase"},
        "frontend": {"platform": "Vercel"},
    },
}

_VALID_CODE_SNAPSHOT = {
    "files": [
        {
            "path": "backend/app/main.py",
            "content": (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                "@app.get(\"/\")\n"
                "def root():\n"
                "    return {\"status\": \"ok\"}\n"
            ),
            "language": "python",
        },
        {
            "path": "backend/requirements.txt",
            "content": "fastapi>=0.110.0\nuvicorn>=0.27.0\n",
            "language": "text",
        },
        {
            "path": "frontend/package.json",
            "content": '{"name": "task-app", "dependencies": {"next": "^14.0.0"}}\n',
            "language": "json",
        },
        {
            "path": "frontend/src/pages/index.tsx",
            "content": 'export default function Home() {\n  return <div>Task App</div>;\n}\n',
            "language": "typescript",
        },
    ],
    "build_command": "npm run build",
    "test_command": "npm test",
    "entry_point": "backend/app/main.py",
}

_VALID_CODE_SNAPSHOT_JSON = json.dumps(_VALID_CODE_SNAPSHOT)


def _make_ctx(
    db: AsyncSession,
    run: ProjectRun,
    node: str = "WriteCode",
    previous_artifacts: dict | None = None,
    workflow_payload: dict | None = None,
) -> RunContext:
    artifacts = (
        previous_artifacts
        if previous_artifacts is not None
        else {
            "prd": _SAMPLE_PRD,
            "design_spec": _SAMPLE_DESIGN,
            "tech_plan": _SAMPLE_TECH_PLAN,
        }
    )
    payload = workflow_payload if workflow_payload is not None else {}
    return RunContext(
        run_id=run.id,
        project_id=run.project_id,
        current_node=node,
        attempt=0,
        db_session=db,
        previous_artifacts=artifacts,
        workflow_payload=payload,
    )


def _mock_llm_response(content: str = _VALID_CODE_SNAPSHOT_JSON) -> LlmResponse:
    return LlmResponse(
        content=content,
        token_usage=TokenUsage(prompt_tokens=500, completion_tokens=2000),
        model_id="gemini-3.1-pro-preview-customtools",
        latency_ms=3500.0,
        profile_used=ModelProfile.CUSTOMTOOLS,
    )


# ---------------------------------------------------------------------------
# 1. CodeSnapshotContent schema tests
# ---------------------------------------------------------------------------


class TestCodeSnapshotContentSchema:
    def test_valid_snapshot_parses(self) -> None:
        snapshot = CodeSnapshotContent.model_validate(_VALID_CODE_SNAPSHOT)
        assert len(snapshot.files) == 4
        assert snapshot.files[0].path == "backend/app/main.py"
        assert snapshot.files[0].language == "python"
        assert snapshot.build_command == "npm run build"
        assert snapshot.entry_point == "backend/app/main.py"

    def test_missing_files_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CodeSnapshotContent.model_validate({"build_command": "npm run build"})

    def test_empty_files_valid(self) -> None:
        snapshot = CodeSnapshotContent.model_validate({"files": []})
        assert snapshot.files == []

    def test_code_file_requires_all_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CodeFile.model_validate({"path": "test.py"})

    def test_defaults_for_commands(self) -> None:
        snapshot = CodeSnapshotContent.model_validate({"files": []})
        assert snapshot.build_command == "npm run build"
        assert snapshot.test_command == "npm test"
        assert snapshot.entry_point == "backend/app/main.py"


# ---------------------------------------------------------------------------
# 2. WriteCodeHandler tests
# ---------------------------------------------------------------------------


class TestWriteCodeHandler:
    @pytest.mark.asyncio
    async def test_success_produces_valid_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        assert result.artifact_data is not None
        assert result.llm_response is not None

        # Artifact should validate against CodeSnapshotContent (ignoring __ keys).
        clean_data = {k: v for k, v in result.artifact_data.items() if not k.startswith("__")}
        snapshot = CodeSnapshotContent.model_validate(clean_data)
        assert len(snapshot.files) == 4
        assert snapshot.entry_point == "backend/app/main.py"

    @pytest.mark.asyncio
    async def test_llm_called_with_customtools_profile(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        assert mock_gen.await_count == 4  # backend, frontend, config, migrations
        for call in mock_gen.call_args_list:
            call_kwargs = call.kwargs
            assert call_kwargs["profile"] == ModelProfile.CUSTOMTOOLS
            assert call_kwargs["node_name"] == "WriteCode"

    @pytest.mark.asyncio
    async def test_tech_plan_and_design_in_prompt(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        call_kwargs = mock_gen.call_args.kwargs
        prompt = call_kwargs["prompt"]
        # Tech plan content should be in the prompt.
        assert "fastapi" in prompt.lower()
        assert "/tasks" in prompt
        # Design content should be in the prompt.
        assert "dashboard" in prompt.lower()

    @pytest.mark.asyncio
    async def test_token_usage_on_response(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.llm_response.token_usage.prompt_tokens == 500
        assert result.llm_response.token_usage.completion_tokens == 2000
        assert result.llm_response.profile_used == ModelProfile.CUSTOMTOOLS

    @pytest.mark.asyncio
    async def test_json_in_markdown_fences_still_parsed(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)
        fenced_content = f"```json\n{_VALID_CODE_SNAPSHOT_JSON}\n```"

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
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
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response("This is not JSON at all"),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.artifact_data is None
        assert result.error is not None
        assert "backend" in result.error.lower()
        assert "invalid json" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_tech_plan_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(
            db, seed_run, previous_artifacts={"prd": _SAMPLE_PRD, "design_spec": _SAMPLE_DESIGN}
        )
        mock_gen = AsyncMock(return_value=_mock_llm_response())

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "tech plan" in result.error.lower()
        mock_gen.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_design_fails(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(
            db, seed_run, previous_artifacts={"prd": _SAMPLE_PRD, "tech_plan": _SAMPLE_TECH_PLAN}
        )
        mock_gen = AsyncMock(return_value=_mock_llm_response())

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert "design" in result.error.lower()
        mock_gen.assert_not_called()

    @pytest.mark.asyncio
    async def test_metadata_attached_to_artifact(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        meta = result.artifact_data["__code_metadata"]
        assert meta["file_count"] == 4
        assert meta["total_loc"] > 0
        assert meta["security_feedback"] == ""

    @pytest.mark.asyncio
    async def test_artifact_lineage_references(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        # Seed artifacts for lineage tracking.
        prd_art = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.PRD,
            version=1,
            content=_SAMPLE_PRD,
            model_profile=ModelProfile.PRIMARY,
        )
        design_art = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.DESIGN_SPEC,
            version=1,
            content=_SAMPLE_DESIGN,
            model_profile=ModelProfile.CUSTOMTOOLS,
        )
        tech_art = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.TECH_PLAN,
            version=1,
            content=_SAMPLE_TECH_PLAN,
            model_profile=ModelProfile.PRIMARY,
        )
        db.add_all([prd_art, design_art, tech_art])
        await db.flush()

        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        refs = result.artifact_data["__code_metadata"]["source_artifacts"]
        assert refs["prd"]["artifact_id"] == str(prd_art.id)
        assert refs["design_spec"]["artifact_id"] == str(design_art.id)
        assert refs["tech_plan"]["artifact_id"] == str(tech_art.id)


# ---------------------------------------------------------------------------
# 3. Security feedback loop
# ---------------------------------------------------------------------------


class TestSecurityFeedbackLoop:
    @pytest.mark.asyncio
    async def test_security_findings_included_in_prompt(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        # Seed a security report artifact (simulates SecurityGate → WriteCode loop).
        security_report = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.SECURITY_REPORT,
            version=1,
            content={
                "findings": [
                    {
                        "severity": "high",
                        "title": "SQL Injection",
                        "detail": "Unsanitized user input in query builder",
                        "file": "backend/app/routes/tasks.py",
                        "line": 42,
                    },
                    {
                        "severity": "critical",
                        "title": "Hardcoded API Key",
                        "detail": "API key found in source code",
                        "file": "backend/app/config.py",
                        "line": 10,
                    },
                ],
                "critical": 1,
                "high": 1,
            },
            model_profile=ModelProfile.PRIMARY,
        )
        db.add(security_report)
        await db.flush()

        handler = WriteCodeHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={
                "prd": _SAMPLE_PRD,
                "design_spec": _SAMPLE_DESIGN,
                "tech_plan": _SAMPLE_TECH_PLAN,
                "code_snapshot": _VALID_CODE_SNAPSHOT,
            },
        )

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "success"
        call_kwargs = mock_gen.call_args.kwargs
        prompt = call_kwargs["prompt"]
        assert "sql injection" in prompt.lower()
        assert "hardcoded api key" in prompt.lower()
        assert "backend/app/routes/tasks.py" in prompt

    @pytest.mark.asyncio
    async def test_security_findings_normalized_schema_included_in_prompt(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        # Uses the SecurityFinding schema emitted by SecurityGate.
        security_report = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.SECURITY_REPORT,
            version=1,
            content={
                "findings": [
                    {
                        "rule_id": "B608",
                        "severity": "high",
                        "file_path": "backend/app/routes/tasks.py",
                        "line_number": 42,
                        "message": "Possible SQL injection vector",
                        "remediation": "Use parameterized queries",
                        "resolved": False,
                    },
                    {
                        "rule_id": "SECRET_OPENAI_KEY",
                        "severity": "critical",
                        "file_path": "backend/app/config.py",
                        "line_number": 10,
                        "message": "OpenAI API key detected",
                        "remediation": "Load secrets from environment variables",
                        "resolved": True,
                    },
                ],
            },
            model_profile=ModelProfile.PRIMARY,
        )
        db.add(security_report)
        await db.flush()

        handler = WriteCodeHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={
                "prd": _SAMPLE_PRD,
                "design_spec": _SAMPLE_DESIGN,
                "tech_plan": _SAMPLE_TECH_PLAN,
                "code_snapshot": _VALID_CODE_SNAPSHOT,
            },
        )

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        prompt = mock_gen.call_args.kwargs["prompt"]
        assert "possible sql injection vector" in prompt.lower()
        assert "use parameterized queries" in prompt.lower()
        assert "backend/app/routes/tasks.py:42" in prompt
        # Resolved findings should not be sent back for remediation.
        assert "openai api key detected" not in prompt.lower()

    @pytest.mark.asyncio
    async def test_no_security_findings_when_no_report(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        call_kwargs = mock_gen.call_args.kwargs
        prompt = call_kwargs["prompt"]
        # Should not contain security-related sections.
        assert "security findings" not in prompt.lower()

    @pytest.mark.asyncio
    async def test_security_feedback_filters_non_blocking_findings(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        security_report = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.SECURITY_REPORT,
            version=1,
            content={
                "findings": [
                    {
                        "severity": "low",
                        "title": "Verbose logging",
                        "detail": "Informational only",
                        "status": "open",
                    },
                    {
                        "severity": "high",
                        "title": "Patched finding",
                        "detail": "Already fixed",
                        "status": "resolved",
                    },
                    {
                        "severity": "critical",
                        "title": "Hardcoded secret",
                        "detail": "Secret in source",
                        "status": "open",
                    },
                ],
            },
            model_profile=ModelProfile.PRIMARY,
        )
        db.add(security_report)
        await db.flush()

        handler = WriteCodeHandler()
        ctx = _make_ctx(
            db,
            seed_run,
            previous_artifacts={
                "prd": _SAMPLE_PRD,
                "design_spec": _SAMPLE_DESIGN,
                "tech_plan": _SAMPLE_TECH_PLAN,
                "code_snapshot": _VALID_CODE_SNAPSHOT,
            },
        )

        mock_gen = AsyncMock(return_value=_mock_llm_response())
        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            mock_gen,
        ):
            await handler.execute(ctx)

        prompt = mock_gen.call_args.kwargs["prompt"]
        assert "hardcoded secret" in prompt.lower()
        assert "verbose logging" not in prompt.lower()
        assert "patched finding" not in prompt.lower()


# ---------------------------------------------------------------------------
# 4. Code validation tests
# ---------------------------------------------------------------------------


class TestCodeValidation:
    @pytest.mark.asyncio
    async def test_python_syntax_error_fails_validation(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        bad_snapshot = {
            **_VALID_CODE_SNAPSHOT,
            "files": [
                {
                    "path": "backend/app/main.py",
                    "content": "def broken(\n    # missing closing paren",
                    "language": "python",
                },
                {
                    "path": "requirements.txt",
                    "content": "fastapi\n",
                    "language": "text",
                },
            ],
        }

        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(json.dumps(bad_snapshot)),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.error is not None
        assert "syntax error" in result.error.lower()
        assert result.context_updates is not None
        errors = result.context_updates.get("validation_errors", [])
        assert any("syntax error" in err.lower() for err in errors)

    @pytest.mark.asyncio
    async def test_missing_entry_point_fails_validation(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        snapshot = {
            "files": [
                {
                    "path": "backend/app/server.py",
                    "content": "def serve() -> None:\n    pass\n",
                    "language": "python",
                },
                {
                    "path": "backend/requirements.txt",
                    "content": "fastapi\n",
                    "language": "text",
                },
            ],
            "build_command": "python -m compileall backend/app",
            "test_command": "pytest",
            "entry_point": "backend/app/main.py",
        }

        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(json.dumps(snapshot)),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.error is not None
        assert "entry point" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_dependency_manifest_fails_validation(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        snapshot = {
            "files": [
                {
                    "path": "app.py",
                    "content": "print('hello')\n",
                    "language": "python",
                }
            ],
            "build_command": "python app.py",
            "test_command": "pytest",
            "entry_point": "app.py",
        }

        handler = WriteCodeHandler()
        ctx = _make_ctx(db, seed_run)

        with patch(
            "app.orchestrator.handlers.write_code.generate_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_llm_response(json.dumps(snapshot)),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.error is not None
        assert "dependency manifest" in result.error.lower()


# ---------------------------------------------------------------------------
# 5. Prompt template tests
# ---------------------------------------------------------------------------


class TestCodeGenerationPromptTemplates:
    def test_basic_prompt_includes_tech_plan_and_design(self) -> None:
        from app.llm.prompts.code_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={
                "tech_plan": _SAMPLE_TECH_PLAN,
                "design_spec": _SAMPLE_DESIGN,
                "prd": _SAMPLE_PRD,
            },
        )
        assert "JSON" in system
        assert "files" in system
        assert "/tasks" in user
        assert "dashboard" in user.lower()
        assert "task management" in user.lower()

    def test_prompt_with_security_feedback(self) -> None:
        from app.llm.prompts.code_generation import build_prompts

        system, user = build_prompts(
            previous_artifacts={
                "tech_plan": _SAMPLE_TECH_PLAN,
                "design_spec": _SAMPLE_DESIGN,
                "prd": _SAMPLE_PRD,
                "code_snapshot": _VALID_CODE_SNAPSHOT,
            },
            feedback="SQL Injection in tasks endpoint",
        )
        assert "SQL Injection" in user
        assert "security" in user.lower()
        # Previous code should be included.
        assert "backend/app/main.py" in user

    def test_internal_metadata_stripped_from_prompts(self) -> None:
        from app.llm.prompts.code_generation import build_prompts

        tech_plan_with_meta = {**_SAMPLE_TECH_PLAN, "__node_name": "GenerateTechPlan"}
        _, user = build_prompts(
            previous_artifacts={
                "tech_plan": tech_plan_with_meta,
                "design_spec": _SAMPLE_DESIGN,
                "prd": _SAMPLE_PRD,
            },
        )
        assert "__node_name" not in user
