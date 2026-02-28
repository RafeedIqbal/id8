from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.orchestrator.base import NodeResult, RunContext
from app.orchestrator.handlers.prepare_pr import PreparePRHandler
from app.orchestrator.handlers.write_code import (
    WriteCodeHandler,
    _infer_entry_point,
    _infer_test_command,
    _is_path_allowed,
    _resolve_npm_package_files,
    _summarize_npm_failure,
    _validate_code_snapshot,
)
from app.schemas.code_snapshot import CodeChunkContent, CodeFile


def test_is_path_allowed():
    assert _is_path_allowed("app/page.tsx") is True
    assert _is_path_allowed("app/layout.tsx") is True
    assert _is_path_allowed("app/globals.css") is True

    assert _is_path_allowed("app/components/button.tsx") is True
    assert _is_path_allowed("components/ui/card.tsx") is True
    assert _is_path_allowed("lib/utils.ts") is True
    assert _is_path_allowed("types/index.d.ts") is True
    assert _is_path_allowed("data/mock.json") is True
    assert _is_path_allowed("public/favicon.ico") is True

    assert _is_path_allowed("src/app/components/button.tsx") is False
    assert _is_path_allowed("src/components/ui/card.tsx") is False
    assert _is_path_allowed("package.json") is False
    assert _is_path_allowed("next.config.ts") is False
    assert _is_path_allowed("postcss.config.mjs") is False
    assert _is_path_allowed("eslint.config.mjs") is False
    assert _is_path_allowed("tsconfig.json") is False
    assert _is_path_allowed(".gitignore") is False
    assert _is_path_allowed("README.md") is False


def test_infer_entry_point():
    assert _infer_entry_point(["components/ui/button.tsx", "app/page.tsx"]) == "app/page.tsx"
    assert _infer_entry_point(["src/app/page.tsx", "app/layout.tsx", "app/page.tsx"]) == "app/page.tsx"
    assert _infer_entry_point(["b.ts", "a.ts"]) == "a.ts"


def test_infer_test_command():
    assert _infer_test_command(["package.json"]) == "npx tsc --noEmit && npm run lint"
    assert _infer_test_command(["requirements.txt", "main.py"]) == "pytest"
    assert _infer_test_command(["some_script.sh"]) == "echo test"


def test_validate_code_snapshot_rejects_dual_app_trees():
    snapshot = {
        "files": [
            {
                "path": "app/page.tsx",
                "content": "export default function Page() { return null; }",
                "language": "typescript",
            },
            {
                "path": "src/app/page.tsx",
                "content": "export default function Page() { return null; }",
                "language": "typescript",
            },
            {"path": "package.json", "content": '{"dependencies":{"next":"16.1.6"}}', "language": "json"},
            {"path": "tsconfig.json", "content": "{}", "language": "json"},
        ],
        "entry_point": "app/page.tsx",
    }

    errors = _validate_code_snapshot(snapshot)
    assert "Merged snapshot cannot contain both root-level 'app/' and 'src/app/' trees" in errors


def test_code_chunk_content_upgrades_legacy_package_changes():
    content = CodeChunkContent.model_validate(
        {
            "files": [],
            "package_changes": {
                "dependencies": {"lucide-react": "^1.0.0"},
                "devDependencies": {"vitest": "^3.0.0"},
            },
        }
    )

    assert [item.model_dump() for item in content.package_requirements] == [
        {"name": "lucide-react", "section": "dependencies", "reason": ""},
        {"name": "vitest", "section": "devDependencies", "reason": ""},
    ]


def test_resolve_npm_package_files_generates_server_owned_manifest(monkeypatch, tmp_path):
    expected_package_json = (
        '{\n'
        '  "name": "example",\n'
        '  "private": true,\n'
        '  "dependencies": {\n'
        '    "next": "16.1.6",\n'
        '    "react": "19.2.3",\n'
        '    "react-dom": "19.2.3",\n'
        '    "lucide-react": "0.542.0"\n'
        "  },\n"
        '  "devDependencies": {\n'
        '    "vitest": "3.2.4"\n'
        "  }\n"
        "}\n"
    )
    expected_lockfile = '{\n  "name": "example",\n  "lockfileVersion": 3\n}\n'

    class FakeTemporaryDirectory:
        def __enter__(self):
            return str(tmp_path)

        def __exit__(self, exc_type, exc, tb):
            return False

    commands: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout, cwd):
        commands.append(cmd)
        assert capture_output is True
        assert text is True
        assert timeout == 180
        assert cwd == str(tmp_path)
        (tmp_path / "package.json").write_text(expected_package_json, encoding="utf-8")
        (tmp_path / "package-lock.json").write_text(expected_lockfile, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.orchestrator.handlers.write_code.tempfile.TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr("app.orchestrator.handlers.write_code.subprocess.run", fake_run)

    files = [
        CodeFile(
            path="app/page.tsx",
            content="export default function Page() { return null; }\n",
            language="typescript",
        ),
        CodeFile(
            path="package.json",
            content=(
                '{"name":"example","private":true,"dependencies":{"next":"16.1.6","react":"19.2.3",'
                '"react-dom":"19.2.3"}}\n'
            ),
            language="json",
        ),
    ]

    updated_files, errors = _resolve_npm_package_files(
        files,
        [
            {"name": "lucide-react", "section": "dependencies", "reason": "icons"},
            {"name": "vitest", "section": "devDependencies", "reason": "tests"},
        ]
    )

    assert errors == []
    assert commands == [
        [
            "npm",
            "install",
            "--package-lock-only",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--save-exact",
            "lucide-react",
        ],
        [
            "npm",
            "install",
            "--package-lock-only",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--save-dev",
            "--save-exact",
            "vitest",
        ],
    ]
    package_json = next(file for file in updated_files if file.path == "package.json")
    assert package_json.content == expected_package_json
    lockfile = next(file for file in updated_files if file.path == "package-lock.json")
    assert lockfile.content == expected_lockfile
    assert lockfile.language == "json"


def test_resolve_npm_package_files_surfaces_resolution_errors(monkeypatch, tmp_path):
    class FakeTemporaryDirectory:
        def __enter__(self):
            return str(tmp_path)

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_run(cmd, capture_output, text, timeout, cwd):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "npm error code ERESOLVE\n"
                "npm error ERESOLVE unable to resolve dependency tree\n"
                "npm error Found: react@19.2.3\n"
                "npm error Could not resolve dependency:\n"
                'npm error peer react@"^18.0.0" from lucide-react@0.344.0\n'
            ),
        )

    monkeypatch.setattr("app.orchestrator.handlers.write_code.tempfile.TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr("app.orchestrator.handlers.write_code.subprocess.run", fake_run)

    files = [
        CodeFile(
            path="package.json",
            content=(
                '{"name":"example","private":true,"dependencies":{"next":"16.1.6","react":"19.2.3",'
                '"react-dom":"19.2.3","lucide-react":"0.344.0"}}\n'
            ),
            language="json",
        ),
    ]

    updated_files, errors = _resolve_npm_package_files(
        files,
        [{"name": "lucide-react", "section": "dependencies", "reason": "icons"}],
    )

    assert updated_files == files
    assert errors == [
        "npm dependency resolution failed while resolving dependencies (lucide-react): "
        'code ERESOLVE | ERESOLVE unable to resolve dependency tree | Found: react@19.2.3 | '
        'Could not resolve dependency: | peer react@"^18.0.0" from lucide-react@0.344.0'
    ]


def test_summarize_npm_failure_deduplicates_noise():
    summary = _summarize_npm_failure(
        "npm error code ERESOLVE\n"
        "npm error code ERESOLVE\n"
        "npm error Found: react@19.2.3\n"
        "npm error Found: react@19.2.3\n"
    )

    assert summary == "code ERESOLVE | Found: react@19.2.3"


@pytest.mark.asyncio
async def test_write_code_fails_fast_when_template_dir_missing(monkeypatch):
    handler = WriteCodeHandler()
    llm_mock = AsyncMock()
    monkeypatch.setattr("app.orchestrator.handlers.write_code.generate_with_fallback", llm_mock)
    monkeypatch.setattr("app.orchestrator.handlers.write_code._load_security_feedback", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.orchestrator.handlers.write_code._load_source_artifact_references",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr("app.config.settings.codegen_template_dir", "does/not/exist")

    ctx = RunContext(
        run_id=uuid4(),
        project_id=uuid4(),
        current_node="WriteCode",
        attempt=1,
        db_session=AsyncMock(),
        previous_artifacts={"design_spec": {"screens": []}, "prd": {"name": "Test"}},
        workflow_payload={},
    )

    result = await handler.execute(ctx)

    assert result.outcome == "failure"
    assert "Codegen template directory does not exist" in (result.error or "")
    llm_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_code_persists_alias_metadata(monkeypatch, tmp_path):
    handler = WriteCodeHandler()

    template_dir = tmp_path / "example"
    (template_dir / "app").mkdir(parents=True)
    (template_dir / "app" / "page.tsx").write_text(
        "export default function Page() { return null; }\n",
        encoding="utf-8",
    )
    (template_dir / "app" / "layout.tsx").write_text(
        (
            "export default function Layout({ children }: { children: React.ReactNode }) "
            "{ return <html><body>{children}</body></html>; }\n"
        ),
        encoding="utf-8",
    )
    (template_dir / "app" / "globals.css").write_text("@import \"tailwindcss\";\n", encoding="utf-8")
    (template_dir / "package.json").write_text(
        '{"dependencies":{"next":"16.1.6","react":"19.2.3","react-dom":"19.2.3"}}\n',
        encoding="utf-8",
    )
    (template_dir / "tsconfig.json").write_text("{}\n", encoding="utf-8")

    responses = iter(
        [
            SimpleNamespace(
                content='{"files":[],"package_requirements":[]}',
                token_usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                profile_used="primary",
                model_id="model-a",
            ),
            SimpleNamespace(
                content=(
                    '{"files":[{"path":"app/page.tsx","content":"export default function Page() { return '
                    '<main>Hello</main>; }","language":"typescript"}],"package_requirements":[]}'
                ),
                token_usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                profile_used="primary",
                model_id="model-b",
            ),
        ]
    )

    async def fake_generate(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("app.orchestrator.handlers.write_code.generate_with_fallback", fake_generate)
    monkeypatch.setattr("app.orchestrator.handlers.write_code._load_security_feedback", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.orchestrator.handlers.write_code._load_source_artifact_references",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr("app.orchestrator.handlers.write_code.emit_llm_usage_event", AsyncMock(return_value=0.0))
    monkeypatch.setattr(
        "app.orchestrator.handlers.write_code._resolve_npm_package_files",
        lambda files, package_requirements: (files, []),
    )
    monkeypatch.setattr("app.config.settings.codegen_template_dir", str(template_dir))

    ctx = RunContext(
        run_id=uuid4(),
        project_id=uuid4(),
        current_node="WriteCode",
        attempt=1,
        db_session=AsyncMock(),
        previous_artifacts={"design_spec": {"screens": []}, "prd": {"name": "Test"}},
        workflow_payload={},
    )

    result = await handler.execute(ctx)

    assert result.outcome == "success"
    assert result.artifact_data is not None
    assert "__code_metadata" in result.artifact_data
    assert "code_metadata_" not in result.artifact_data
    assert result.artifact_data["__code_metadata"]["is_authoritative_merged_tree"] is True


@pytest.mark.asyncio
async def test_prepare_pr_reads_authoritative_flag_from_alias(monkeypatch):
    handler = PreparePRHandler()
    captured: dict[str, object] = {}

    async def fake_run_github_flow(ctx, client, files, *, skip_check_runs=False, authoritative=False):
        captured["authoritative"] = authoritative
        return NodeResult(outcome="success")

    monkeypatch.setattr(
        "app.orchestrator.handlers.prepare_pr._load_code_snapshot",
        AsyncMock(
            return_value={
                "files": [{"path": "app/page.tsx", "content": "export default function Page() { return null; }"}],
                "__code_metadata": {"is_authoritative_merged_tree": True},
            }
        ),
    )
    monkeypatch.setattr(
        "app.orchestrator.handlers.prepare_pr.resolve_github_auth",
        lambda: SimpleNamespace(mode="token"),
    )
    monkeypatch.setattr("app.orchestrator.handlers.prepare_pr.GitHubClient", lambda auth: object())
    monkeypatch.setattr("app.orchestrator.handlers.prepare_pr._run_github_flow", fake_run_github_flow)

    ctx = RunContext(
        run_id=uuid4(),
        project_id=uuid4(),
        current_node="PreparePR",
        attempt=1,
        db_session=AsyncMock(),
        previous_artifacts={},
        workflow_payload={},
    )

    result = await handler.execute(ctx)

    assert result.outcome == "success"
    assert captured["authoritative"] is True
