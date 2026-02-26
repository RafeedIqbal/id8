"""Tests for the SecurityGate node (Task 09).

Covers:
1. SecurityReportContent / SecurityFinding schema validation
2. SAST scanner (bandit) — parsing, tool-not-installed graceful degradation
3. Dependency audit (pip-audit / npm audit) — parsing, degradation
4. Secret scanner — pattern detection, placeholder suppression, skip-list
5. SecurityGateHandler — pass/fail logic, artifact shape, context_updates
6. Pass-through of clean code with no findings
"""
from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.enums import ArtifactType, ModelProfile, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.models.user import User
from app.orchestrator.base import RunContext
from app.orchestrator.handlers.security_gate import SecurityGateHandler, _build_summary
from app.schemas.security_report import SecurityFinding, SecurityReportContent, SecuritySummary
from app.security.dependency_audit import (
    _parse_npm_audit_output,
    _parse_pip_audit_output,
)
from app.security.sast import _parse_bandit_output
from app.security.secret_scan import _scan_file, run_secret_scan

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8_test",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")


# ---------------------------------------------------------------------------
# Database fixtures
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
    user = User(id=_SCAFFOLD_USER_ID, email="test-security@id8.local", role="operator")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def seed_project(db: AsyncSession, seed_user: User) -> Project:
    project = Project(
        owner_user_id=seed_user.id,
        initial_prompt="Build a task management app",
        status=ProjectStatus.CODEGEN,
    )
    db.add(project)
    await db.flush()
    return project


@pytest_asyncio.fixture
async def seed_run(db: AsyncSession, seed_project: Project) -> ProjectRun:
    run = ProjectRun(
        project_id=seed_project.id,
        status=ProjectStatus.SECURITY_GATE,
        current_node="SecurityGate",
    )
    db.add(run)
    await db.flush()
    return run


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_CLEAN_FILES = [
    {
        "path": "backend/app/main.py",
        "content": (
            "from fastapi import FastAPI\n\n"
            "app = FastAPI()\n\n"
            "@app.get('/')\n"
            "def root():\n"
            "    return {'status': 'ok'}\n"
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
        "content": json.dumps({"name": "app", "dependencies": {"next": "^14.0.0"}}),
        "language": "json",
    },
]

_CLEAN_CODE_SNAPSHOT = {
    "files": _CLEAN_FILES,
    "build_command": "npm run build",
    "test_command": "npm test",
    "entry_point": "backend/app/main.py",
}


def _make_ctx(
    db: AsyncSession,
    run: ProjectRun,
    previous_artifacts: dict | None = None,
) -> RunContext:
    return RunContext(
        run_id=run.id,
        project_id=run.project_id,
        current_node="SecurityGate",
        attempt=0,
        db_session=db,
        previous_artifacts=previous_artifacts or {},
        workflow_payload={},
    )


async def _seed_code_snapshot(
    db: AsyncSession,
    project: Project,
    run: ProjectRun,
    snapshot: dict | None = None,
) -> ProjectArtifact:
    artifact = ProjectArtifact(
        project_id=project.id,
        run_id=run.id,
        artifact_type=ArtifactType.CODE_SNAPSHOT,
        version=1,
        content=snapshot or _CLEAN_CODE_SNAPSHOT,
        model_profile=ModelProfile.CUSTOMTOOLS,
    )
    db.add(artifact)
    await db.flush()
    return artifact


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------


class TestSecuritySchemas:
    def test_security_finding_defaults(self) -> None:
        f = SecurityFinding(
            rule_id="B101",
            severity="high",
            file_path="app.py",
            line_number=5,
            message="assert used",
            remediation="Remove assert",
        )
        assert f.resolved is False
        assert f.severity == "high"

    def test_security_finding_resolved_flag(self) -> None:
        f = SecurityFinding(
            rule_id="B101",
            severity="high",
            file_path="app.py",
            line_number=5,
            message="assert used",
            remediation="Remove assert",
            resolved=True,
        )
        assert f.resolved is True

    def test_security_summary_defaults(self) -> None:
        s = SecuritySummary()
        assert s.critical == 0
        assert s.high == 0
        assert s.medium == 0
        assert s.low == 0
        assert s.total == 0

    def test_security_report_content_passed_field(self) -> None:
        report = SecurityReportContent(
            findings=[],
            summary=SecuritySummary(),
            scan_tools=["bandit"],
            passed=True,
        )
        assert report.passed is True
        assert report.scan_tools == ["bandit"]

    def test_security_report_roundtrip(self) -> None:
        finding = SecurityFinding(
            rule_id="B301",
            severity="critical",
            file_path="backend/config.py",
            line_number=12,
            message="Hardcoded secret",
            remediation="Use env var",
        )
        report = SecurityReportContent(
            findings=[finding],
            summary=SecuritySummary(critical=1, total=1),
            scan_tools=["secret-scan"],
            passed=False,
        )
        dumped = report.model_dump()
        restored = SecurityReportContent.model_validate(dumped)
        assert restored.passed is False
        assert restored.findings[0].rule_id == "B301"
        assert restored.summary.critical == 1

    def test_build_summary_counts_correctly(self) -> None:
        findings = [
            SecurityFinding(
                rule_id="A",
                severity="critical",
                file_path="f",
                line_number=1,
                message="m",
                remediation="r",
            ),
            SecurityFinding(
                rule_id="B",
                severity="critical",
                file_path="f",
                line_number=2,
                message="m",
                remediation="r",
            ),
            SecurityFinding(
                rule_id="C",
                severity="high",
                file_path="f",
                line_number=3,
                message="m",
                remediation="r",
            ),
            SecurityFinding(
                rule_id="D",
                severity="medium",
                file_path="f",
                line_number=4,
                message="m",
                remediation="r",
            ),
            SecurityFinding(
                rule_id="E",
                severity="low",
                file_path="f",
                line_number=5,
                message="m",
                remediation="r",
            ),
        ]
        summary = _build_summary(findings)
        assert summary.critical == 2
        assert summary.high == 1
        assert summary.medium == 1
        assert summary.low == 1
        assert summary.total == 5


# ---------------------------------------------------------------------------
# 2. SAST scanner tests
# ---------------------------------------------------------------------------


class TestSASTScanner:
    def test_parse_bandit_output_high_severity(self) -> None:
        bandit_json = json.dumps(
            {
                "results": [
                    {
                        "test_id": "B301",
                        "issue_severity": "HIGH",
                        "filename": "/tmp/scan/backend/app/utils.py",
                        "line_number": 42,
                        "issue_text": "Use of pickle",
                        "more_info": "https://bandit.readthedocs.io/en/latest/blacklists/blacklist_calls.html#b301-pickle",
                    }
                ],
                "errors": [],
            }
        )
        findings = _parse_bandit_output(bandit_json, "/tmp/scan")
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert findings[0].rule_id == "B301"
        assert findings[0].file_path == "backend/app/utils.py"
        assert findings[0].line_number == 42
        assert "pickle" in findings[0].message.lower()

    def test_parse_bandit_output_strips_tmpdir_prefix(self) -> None:
        bandit_json = json.dumps(
            {
                "results": [
                    {
                        "test_id": "B105",
                        "issue_severity": "MEDIUM",
                        "filename": "/var/tmp/abc123/src/auth.py",
                        "line_number": 7,
                        "issue_text": "Hardcoded password",
                        "more_info": "https://bandit.io/B105",
                    }
                ]
            }
        )
        findings = _parse_bandit_output(bandit_json, "/var/tmp/abc123")
        assert findings[0].file_path == "src/auth.py"

    def test_parse_bandit_output_empty_results(self) -> None:
        bandit_json = json.dumps({"results": [], "errors": []})
        findings = _parse_bandit_output(bandit_json, "/tmp/scan")
        assert findings == []

    def test_parse_bandit_output_invalid_json(self) -> None:
        findings = _parse_bandit_output("not json at all", "/tmp/scan")
        assert findings == []

    def test_parse_bandit_output_empty_string(self) -> None:
        findings = _parse_bandit_output("", "/tmp/scan")
        assert findings == []

    def test_parse_bandit_output_severity_mapping(self) -> None:
        for bandit_level, expected in [("HIGH", "high"), ("MEDIUM", "medium"), ("LOW", "low")]:
            bandit_json = json.dumps(
                {
                    "results": [
                        {
                            "test_id": "B999",
                            "issue_severity": bandit_level,
                            "filename": "/tmp/x/f.py",
                            "line_number": 1,
                            "issue_text": "test",
                            "more_info": "",
                        }
                    ]
                }
            )
            findings = _parse_bandit_output(bandit_json, "/tmp/x")
            assert findings[0].severity == expected

    @pytest.mark.asyncio
    async def test_run_sast_no_python_files_returns_empty(self) -> None:
        from app.security.sast import run_sast

        files = [
            {"path": "frontend/index.tsx", "content": "export default () => null;", "language": "typescript"},
        ]
        result = await run_sast(files)
        assert result == []

    @pytest.mark.asyncio
    async def test_run_sast_bandit_not_installed_degrades_gracefully(self) -> None:
        from app.security.sast import run_sast

        files = [{"path": "app.py", "content": "print('hello')\n", "language": "python"}]

        with patch("subprocess.run", side_effect=FileNotFoundError("bandit not found")):
            result = await run_sast(files)

        assert result == []

    @pytest.mark.asyncio
    async def test_run_sast_timeout_degrades_gracefully(self) -> None:
        import subprocess

        from app.security.sast import run_sast

        files = [{"path": "app.py", "content": "x = 1\n", "language": "python"}]

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bandit", 60)):
            result = await run_sast(files)

        assert result == []

    @pytest.mark.asyncio
    async def test_run_sast_parses_subprocess_output(self) -> None:
        from app.security.sast import run_sast

        files = [{"path": "backend/app.py", "content": "import pickle\n", "language": "python"}]

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {
                "results": [
                    {
                        "test_id": "B301",
                        "issue_severity": "HIGH",
                        "filename": "/tmp/TMPDIR/backend/app.py",
                        "line_number": 1,
                        "issue_text": "Use of pickle",
                        "more_info": "https://bandit.io/B301",
                    }
                ]
            }
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = await run_sast(files)

        mock_run.assert_called_once()
        assert len(result) == 1
        assert result[0].severity == "high"
        assert result[0].rule_id == "B301"

    @pytest.mark.asyncio
    async def test_run_sast_ignores_unsafe_paths(self) -> None:
        from app.security.sast import run_sast

        files = [
            {
                "path": "../../outside.py",
                "content": "print('unsafe')\n",
                "language": "python",
            }
        ]

        with patch("subprocess.run") as mock_run:
            result = await run_sast(files)

        assert result == []
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Dependency audit tests
# ---------------------------------------------------------------------------


class TestDependencyAudit:
    def test_parse_pip_audit_output_with_vuln(self) -> None:
        pip_audit_json = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "requests",
                        "version": "2.20.0",
                        "vulns": [
                            {
                                "id": "PYSEC-2023-001",
                                "fix_versions": ["2.28.0"],
                                "description": "SSRF vulnerability",
                            }
                        ],
                    }
                ]
            }
        )
        findings = _parse_pip_audit_output(pip_audit_json, "requirements.txt")
        assert len(findings) == 1
        assert findings[0].rule_id == "PYSEC-2023-001"
        assert findings[0].file_path == "requirements.txt"
        assert findings[0].severity == "high"
        assert "requests" in findings[0].message
        assert "2.28.0" in findings[0].remediation

    def test_parse_pip_audit_no_vulns(self) -> None:
        pip_audit_json = json.dumps(
            {
                "dependencies": [
                    {"name": "fastapi", "version": "0.110.0", "vulns": []}
                ]
            }
        )
        findings = _parse_pip_audit_output(pip_audit_json, "requirements.txt")
        assert findings == []

    def test_parse_pip_audit_empty_output(self) -> None:
        assert _parse_pip_audit_output("", "requirements.txt") == []

    def test_parse_pip_audit_invalid_json(self) -> None:
        assert _parse_pip_audit_output("not json", "requirements.txt") == []

    def test_parse_pip_audit_no_fix_versions(self) -> None:
        pip_audit_json = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "old-pkg",
                        "version": "0.1.0",
                        "vulns": [
                            {"id": "CVE-2020-9999", "fix_versions": [], "description": "Old issue"}
                        ],
                    }
                ]
            }
        )
        findings = _parse_pip_audit_output(pip_audit_json, "requirements.txt")
        assert len(findings) == 1
        assert "No fix available" in findings[0].remediation

    def test_parse_npm_audit_output_with_vuln(self) -> None:
        npm_audit_json = json.dumps(
            {
                "auditReportVersion": 2,
                "vulnerabilities": {
                    "lodash": {
                        "name": "lodash",
                        "severity": "high",
                        "isDirect": True,
                        "via": [
                            {
                                "source": 1179,
                                "name": "lodash",
                                "dependency": "lodash",
                                "title": "Prototype Pollution",
                                "url": "https://npmjs.com/advisories/1179",
                                "severity": "high",
                            }
                        ],
                        "effects": [],
                        "range": "<4.17.21",
                        "nodes": ["node_modules/lodash"],
                        "fixAvailable": True,
                    }
                },
                "metadata": {},
            }
        )
        findings = _parse_npm_audit_output(npm_audit_json, "frontend/package.json")
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert "lodash" in findings[0].message
        assert "Prototype Pollution" in findings[0].message
        assert findings[0].file_path == "frontend/package.json"
        assert "npm audit fix" in findings[0].remediation

    def test_parse_npm_audit_no_vulnerabilities(self) -> None:
        npm_audit_json = json.dumps({"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {}})
        findings = _parse_npm_audit_output(npm_audit_json, "package.json")
        assert findings == []

    def test_parse_npm_audit_empty_output(self) -> None:
        assert _parse_npm_audit_output("", "package.json") == []

    def test_parse_npm_audit_invalid_json(self) -> None:
        assert _parse_npm_audit_output("not json", "package.json") == []

    def test_parse_npm_audit_skips_non_dict_via(self) -> None:
        # When via contains a string reference (indirect dep), skip it
        npm_audit_json = json.dumps(
            {
                "vulnerabilities": {
                    "some-pkg": {
                        "severity": "moderate",
                        "via": ["lodash"],  # string, not dict
                        "fixAvailable": False,
                    }
                }
            }
        )
        findings = _parse_npm_audit_output(npm_audit_json, "package.json")
        assert findings == []

    @pytest.mark.asyncio
    async def test_run_dependency_audit_pip_not_installed_degrades(self) -> None:
        from app.security.dependency_audit import run_dependency_audit

        files = [{"path": "requirements.txt", "content": "requests==2.20.0\n", "language": "text"}]

        with patch("subprocess.run", side_effect=FileNotFoundError("pip-audit not found")):
            result = await run_dependency_audit(files)

        assert result == []

    @pytest.mark.asyncio
    async def test_run_dependency_audit_npm_not_installed_degrades(self) -> None:
        from app.security.dependency_audit import run_dependency_audit

        files = [
            {
                "path": "package.json",
                "content": json.dumps({"name": "app", "dependencies": {"lodash": "^4.0.0"}}),
                "language": "json",
            }
        ]

        with patch("subprocess.run", side_effect=FileNotFoundError("npm not found")):
            result = await run_dependency_audit(files)

        assert result == []

    @pytest.mark.asyncio
    async def test_run_dependency_audit_invalid_package_json(self) -> None:
        from app.security.dependency_audit import run_dependency_audit

        files = [{"path": "package.json", "content": "not valid json", "language": "json"}]
        result = await run_dependency_audit(files)
        assert result == []

    @pytest.mark.asyncio
    async def test_run_dependency_audit_no_manifest_files(self) -> None:
        from app.security.dependency_audit import run_dependency_audit

        files = [{"path": "backend/app/main.py", "content": "app = None\n", "language": "python"}]
        result = await run_dependency_audit(files)
        assert result == []


# ---------------------------------------------------------------------------
# 4. Secret scanner tests
# ---------------------------------------------------------------------------


class TestSecretScanner:
    def test_detects_openai_api_key(self) -> None:
        content = 'API_KEY = "sk-abcdefghij1234567890ABCDEFGHIJ"\n'
        findings = _scan_file("config.py", content)
        assert any(f.rule_id == "SECRET_OPENAI_KEY" for f in findings)
        assert all(f.severity == "critical" for f in findings)

    def test_detects_aws_access_key(self) -> None:
        content = 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'
        findings = _scan_file("settings.py", content)
        assert any(f.rule_id == "SECRET_AWS_ACCESS_KEY" for f in findings)

    def test_detects_private_key_header(self) -> None:
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
        findings = _scan_file("key.pem", content)
        assert any(f.rule_id == "SECRET_PRIVATE_KEY" for f in findings)

    def test_detects_hardcoded_password(self) -> None:
        content = 'password = "supersecret123"\n'
        findings = _scan_file("db.py", content)
        assert any(f.rule_id == "SECRET_HARDCODED_PASSWORD" for f in findings)

    def test_detects_hardcoded_token(self) -> None:
        content = 'token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"\n'
        findings = _scan_file("auth.py", content)
        assert any(f.rule_id == "SECRET_HARDCODED_TOKEN" for f in findings)

    def test_detects_generic_api_key(self) -> None:
        content = 'api_key = "abcd1234efgh5678"\n'
        findings = _scan_file("client.py", content)
        assert any(f.rule_id == "SECRET_GENERIC_API_KEY" for f in findings)

    def test_detects_stripe_live_key(self) -> None:
        content = 'STRIPE_KEY = "sk_live_abcdef1234567890abcdef12"\n'
        findings = _scan_file("payments.py", content)
        assert any(f.rule_id == "SECRET_STRIPE_LIVE_KEY" for f in findings)

    def test_placeholder_suppression_your_api_key(self) -> None:
        content = 'api_key = "your-api-key"\n'
        findings = _scan_file("config.py", content)
        secret_findings = [f for f in findings if f.rule_id == "SECRET_GENERIC_API_KEY"]
        assert secret_findings == []

    def test_placeholder_suppression_env_var_syntax(self) -> None:
        content = 'API_KEY = "${API_KEY}"\n'
        findings = _scan_file("config.py", content)
        assert findings == []

    def test_placeholder_suppression_changeme(self) -> None:
        content = 'password = "changeme"\n'
        findings = _scan_file("config.py", content)
        assert findings == []

    def test_placeholder_suppression_example(self) -> None:
        content = 'token = "example-token-value"\n'
        findings = _scan_file("config.py", content)
        secret_findings = [f for f in findings if f.rule_id == "SECRET_HARDCODED_TOKEN"]
        assert secret_findings == []

    def test_no_findings_on_clean_code(self) -> None:
        content = (
            "import os\n\n"
            "API_KEY = os.environ['API_KEY']\n"
            "DB_PASSWORD = os.environ.get('DB_PASSWORD')\n"
        )
        findings = _scan_file("config.py", content)
        assert findings == []

    def test_finding_includes_correct_line_number(self) -> None:
        content = "x = 1\ny = 2\nAPI_KEY = 'sk-realkey1234567890ABCDE'\n"
        findings = _scan_file("f.py", content)
        openai_findings = [f for f in findings if f.rule_id == "SECRET_OPENAI_KEY"]
        assert len(openai_findings) == 1
        assert openai_findings[0].line_number == 3

    def test_remediation_mentions_environment_variable(self) -> None:
        content = 'password = "hardcoded!"\n'
        findings = _scan_file("db.py", content)
        assert findings
        assert "environment variable" in findings[0].remediation.lower()

    @pytest.mark.asyncio
    async def test_run_secret_scan_skips_env_example(self) -> None:
        files = [
            {
                "path": "backend/.env.example",
                "content": 'API_KEY = "sk-yourapikey1234567890abcdef"\n',
                "language": "text",
            }
        ]
        findings = await run_secret_scan(files)
        assert findings == []

    @pytest.mark.asyncio
    async def test_run_secret_scan_skips_readme(self) -> None:
        files = [
            {
                "path": "README.md",
                "content": "Set your `API_KEY = sk-realkey1234567890ABCDE` in .env\n",
                "language": "markdown",
            }
        ]
        findings = await run_secret_scan(files)
        assert findings == []

    @pytest.mark.asyncio
    async def test_run_secret_scan_detects_across_multiple_files(self) -> None:
        files = [
            {
                "path": "backend/config.py",
                "content": 'SECRET_KEY = "sk-abcdefghij1234567890ABCDE"\n',
                "language": "python",
            },
            {
                "path": "backend/db.py",
                "content": 'password = "verysecret!"\n',
                "language": "python",
            },
            {
                "path": "backend/clean.py",
                "content": "import os\nSECRET = os.environ['SECRET']\n",
                "language": "python",
            },
        ]
        findings = await run_secret_scan(files)
        paths_with_findings = {f.file_path for f in findings}
        assert "backend/config.py" in paths_with_findings
        assert "backend/db.py" in paths_with_findings
        assert "backend/clean.py" not in paths_with_findings

    @pytest.mark.asyncio
    async def test_run_secret_scan_clean_files(self) -> None:
        findings = await run_secret_scan(_CLEAN_FILES)
        assert findings == []


# ---------------------------------------------------------------------------
# 5. SecurityGateHandler integration tests
# ---------------------------------------------------------------------------


class TestSecurityGateHandler:
    @pytest.mark.asyncio
    async def test_passes_with_clean_code(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "passed"
        assert result.artifact_data is not None
        report = SecurityReportContent.model_validate(result.artifact_data)
        assert report.passed is True
        assert report.findings == []
        assert result.context_updates is None

    @pytest.mark.asyncio
    async def test_fails_with_critical_finding(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        critical_finding = SecurityFinding(
            rule_id="SECRET_OPENAI_KEY",
            severity="critical",
            file_path="backend/config.py",
            line_number=5,
            message="OpenAI API key detected",
            remediation="Use environment variable",
        )

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[critical_finding])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failed"
        report = SecurityReportContent.model_validate(result.artifact_data)
        assert report.passed is False
        assert report.summary.critical == 1

    @pytest.mark.asyncio
    async def test_fails_with_high_finding(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        high_finding = SecurityFinding(
            rule_id="B301",
            severity="high",
            file_path="backend/utils.py",
            line_number=10,
            message="Use of pickle",
            remediation="Replace pickle with safer alternative",
        )

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[high_finding])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failed"
        report = SecurityReportContent.model_validate(result.artifact_data)
        assert report.passed is False
        assert report.summary.high == 1

    @pytest.mark.asyncio
    async def test_passes_with_only_medium_and_low(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        medium = SecurityFinding(
            rule_id="B201",
            severity="medium",
            file_path="app.py",
            line_number=1,
            message="Flask debug mode",
            remediation="Disable debug in production",
        )
        low = SecurityFinding(
            rule_id="B101",
            severity="low",
            file_path="app.py",
            line_number=2,
            message="assert statement",
            remediation="Remove assert",
        )

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[medium, low])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "passed"
        report = SecurityReportContent.model_validate(result.artifact_data)
        assert report.passed is True
        assert report.summary.medium == 1
        assert report.summary.low == 1

    @pytest.mark.asyncio
    async def test_resolved_high_finding_does_not_block(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        resolved_high = SecurityFinding(
            rule_id="B301",
            severity="high",
            file_path="app.py",
            line_number=1,
            message="Already fixed",
            remediation="N/A",
            resolved=True,
        )

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[resolved_high])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "passed"

    @pytest.mark.asyncio
    async def test_context_updates_contain_blocking_findings_on_failure(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        critical = SecurityFinding(
            rule_id="SECRET_AWS",
            severity="critical",
            file_path="config.py",
            line_number=3,
            message="AWS key",
            remediation="Use IAM role",
        )
        low = SecurityFinding(
            rule_id="B101",
            severity="low",
            file_path="app.py",
            line_number=1,
            message="assert",
            remediation="Remove",
        )

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[low])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[critical])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failed"
        assert result.context_updates is not None
        blocking = result.context_updates["security_findings"]
        # Only the critical finding is blocking, not the low one
        assert len(blocking) == 1
        assert blocking[0]["rule_id"] == "SECRET_AWS"
        assert blocking[0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_artifact_includes_all_scan_tools(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        report = SecurityReportContent.model_validate(result.artifact_data)
        assert "bandit" in report.scan_tools
        assert "pip-audit" in report.scan_tools
        assert "secret-scan" in report.scan_tools

    @pytest.mark.asyncio
    async def test_fails_gracefully_when_no_code_snapshot(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.error is not None
        assert "code_snapshot" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fails_gracefully_with_empty_snapshot(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        snapshot_with_no_files = {
            "files": [],
            "build_command": "npm run build",
            "test_command": "npm test",
            "entry_point": "backend/app/main.py",
        }
        await _seed_code_snapshot(db, seed_project, seed_run, snapshot=snapshot_with_no_files)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        result = await handler.execute(ctx)

        assert result.outcome == "failure"
        assert result.error is not None
        assert "files" in result.error.lower()

    @pytest.mark.asyncio
    async def test_loads_most_recent_snapshot_version(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        # Seed two versions — handler should use v2
        v1 = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.CODE_SNAPSHOT,
            version=1,
            content={"files": [], "build_command": "echo", "test_command": "echo", "entry_point": ""},
            model_profile=ModelProfile.PRIMARY,
        )
        v2_snapshot = {**_CLEAN_CODE_SNAPSHOT}
        v2 = ProjectArtifact(
            project_id=seed_project.id,
            run_id=seed_run.id,
            artifact_type=ArtifactType.CODE_SNAPSHOT,
            version=2,
            content=v2_snapshot,
            model_profile=ModelProfile.CUSTOMTOOLS,
        )
        db.add_all([v1, v2])
        await db.flush()

        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])) as mock_sast,
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        # v2 has files, so sast is called and gate passes
        assert result.outcome == "passed"
        mock_sast.assert_called_once()
        called_files = mock_sast.call_args[0][0]
        assert len(called_files) == len(_CLEAN_CODE_SNAPSHOT["files"])

    @pytest.mark.asyncio
    async def test_report_is_machine_readable_json(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        # Must be JSON-serialisable
        serialized = json.dumps(result.artifact_data)
        parsed = json.loads(serialized)
        assert "findings" in parsed
        assert "summary" in parsed
        assert "passed" in parsed
        assert "scan_tools" in parsed

    @pytest.mark.asyncio
    async def test_findings_include_file_and_line_for_ui(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        finding = SecurityFinding(
            rule_id="B301",
            severity="high",
            file_path="backend/app/utils.py",
            line_number=17,
            message="Use of pickle",
            remediation="Replace pickle",
        )

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[finding])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        dumped = result.artifact_data["findings"][0]
        assert dumped["file_path"] == "backend/app/utils.py"
        assert dumped["line_number"] == 17
        assert dumped["rule_id"] == "B301"


# ---------------------------------------------------------------------------
# 6. Acceptance scenario #5 — Security Block
# ---------------------------------------------------------------------------


class TestAcceptanceScenario5:
    """Validates the 'Security Block' acceptance test scenario.

    Clean code → gate passes.
    Code with hardcoded secret → gate fails and loops back with context.
    """

    @pytest.mark.asyncio
    async def test_clean_code_passes_gate(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        await _seed_code_snapshot(db, seed_project, seed_run, snapshot=_CLEAN_CODE_SNAPSHOT)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
            patch("app.security.secret_scan.run_secret_scan", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "passed"
        assert result.context_updates is None

    @pytest.mark.asyncio
    async def test_code_with_secret_fails_gate_and_returns_findings(
        self, db: AsyncSession, seed_run: ProjectRun, seed_project: Project
    ) -> None:
        dirty_snapshot = {
            **_CLEAN_CODE_SNAPSHOT,
            "files": [
                *_CLEAN_FILES,
                {
                    "path": "backend/app/config.py",
                    "content": 'OPENAI_KEY = "sk-abcdefghij1234567890ABCDEFGHIJ"\n',
                    "language": "python",
                },
            ],
        }
        await _seed_code_snapshot(db, seed_project, seed_run, snapshot=dirty_snapshot)
        handler = SecurityGateHandler()
        ctx = _make_ctx(db, seed_run)

        # Use the real secret scanner (no mock) — it should detect the key
        with (
            patch("app.security.sast.run_sast", new=AsyncMock(return_value=[])),
            patch("app.security.dependency_audit.run_dependency_audit", new=AsyncMock(return_value=[])),
        ):
            result = await handler.execute(ctx)

        assert result.outcome == "failed"
        assert result.context_updates is not None
        findings = result.context_updates["security_findings"]
        assert any(f["severity"] == "critical" for f in findings)
        # Confirms transition table routes to WriteCode on "failed"
        from app.orchestrator.transitions import resolve_next_node
        next_node = resolve_next_node("SecurityGate", "failed")
        assert next_node == "WriteCode"

    @pytest.mark.asyncio
    async def test_gate_passed_routes_to_prepare_pr(self) -> None:
        from app.orchestrator.transitions import resolve_next_node
        next_node = resolve_next_node("SecurityGate", "passed")
        assert next_node == "PreparePR"
