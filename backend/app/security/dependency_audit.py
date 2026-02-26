"""Dependency audit scanner.

Checks Python dependencies (requirements.txt / pyproject.toml) via pip-audit
and Node.js dependencies (package.json) via npm audit.  Both tools are run as
subprocesses against a temp directory so the generated code is never executed.

If either tool is not installed, the scanner logs a warning and returns an
empty list so the gate degrades gracefully.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.security_report import SecurityFinding

logger = logging.getLogger("id8.security.dependency_audit")

_PYTHON_MANIFESTS = {"requirements.txt", "pyproject.toml"}


async def run_dependency_audit(files: list[dict[str, Any]]) -> list[SecurityFinding]:
    """Audit dependencies found in generated manifest files.

    Parameters
    ----------
    files:
        List of ``{"path": str, "content": str, "language": str}`` dicts.

    Returns
    -------
    list[SecurityFinding]
        Aggregated vulnerability findings; empty when no manifests are found
        or the audit tools are unavailable.
    """
    findings: list[SecurityFinding] = []

    for f in files:
        path = str(f.get("path", ""))
        content = str(f.get("content", ""))
        basename = path.split("/")[-1] if "/" in path else path

        if basename in _PYTHON_MANIFESTS:
            findings.extend(await _audit_python_deps(path, content, basename))
        elif basename == "package.json":
            findings.extend(await _audit_node_deps(path, content))

    return findings


# ---------------------------------------------------------------------------
# Python — pip-audit
# ---------------------------------------------------------------------------


async def _audit_python_deps(
    file_path: str, content: str, basename: str
) -> list[SecurityFinding]:
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest = Path(tmpdir) / basename
        manifest.write_text(content, encoding="utf-8")

        if basename == "requirements.txt":
            cmd = ["pip-audit", "--format", "json", "-r", str(manifest)]
        else:
            # pyproject.toml: pip-audit detects it automatically
            cmd = ["pip-audit", "--format", "json"]

        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=tmpdir,
            )
        except FileNotFoundError:
            logger.warning("pip-audit not installed; skipping Python dependency audit")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("pip-audit timed out; skipping Python dependency audit")
            return []

    return _parse_pip_audit_output(result.stdout, file_path)


def _parse_pip_audit_output(output: str, file_path: str) -> list[SecurityFinding]:
    if not output.strip():
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("pip-audit produced non-JSON output")
        return []

    findings: list[SecurityFinding] = []

    for dep in data.get("dependencies", []):
        pkg_name = str(dep.get("name", "unknown"))
        pkg_version = str(dep.get("version", "?"))

        for vuln in dep.get("vulns", []):
            vuln_id = str(vuln.get("id", "UNKNOWN"))
            description = str(vuln.get("description", ""))
            fix_versions = vuln.get("fix_versions", [])
            remediation = (
                f"Upgrade to: {', '.join(fix_versions)}"
                if fix_versions
                else "No fix available — consider removing or replacing this dependency"
            )

            findings.append(
                SecurityFinding(
                    rule_id=vuln_id,
                    severity="high",  # treat all known vulnerabilities as high
                    file_path=file_path,
                    line_number=0,
                    message=(
                        f"{pkg_name}=={pkg_version} has known vulnerability"
                        f" {vuln_id}: {description}"
                    ),
                    remediation=remediation,
                    resolved=False,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Node.js — npm audit
# ---------------------------------------------------------------------------


async def _audit_node_deps(file_path: str, content: str) -> list[SecurityFinding]:
    try:
        json.loads(content)
    except json.JSONDecodeError:
        logger.warning("package.json is not valid JSON; skipping: %s", file_path)
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_file = Path(tmpdir) / "package.json"
        pkg_file.write_text(content, encoding="utf-8")

        try:
            result = subprocess.run(  # noqa: S603
                ["npm", "audit", "--json"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=tmpdir,
            )
        except FileNotFoundError:
            logger.warning("npm not installed; skipping Node.js dependency audit")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("npm audit timed out; skipping Node.js dependency audit")
            return []

    return _parse_npm_audit_output(result.stdout, file_path)


def _parse_npm_audit_output(output: str, file_path: str) -> list[SecurityFinding]:
    if not output.strip():
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("npm audit produced non-JSON output")
        return []

    findings: list[SecurityFinding] = []
    vulnerabilities: dict[str, Any] = data.get("vulnerabilities", {})

    for pkg_name, vuln_info in vulnerabilities.items():
        if not isinstance(vuln_info, dict):
            continue

        severity = str(vuln_info.get("severity", "low"))
        via = vuln_info.get("via", [])

        for advisory in via:
            if not isinstance(advisory, dict):
                continue

            source = advisory.get("source", advisory.get("url", f"npm-{pkg_name}"))
            title = str(advisory.get("title", "Vulnerability"))
            fix_available = vuln_info.get("fixAvailable", False)
            remediation = (
                "Run npm audit fix"
                if fix_available
                else "No automatic fix available — review and update manually"
            )

            findings.append(
                SecurityFinding(
                    rule_id=str(source),
                    severity=severity,
                    file_path=file_path,
                    line_number=0,
                    message=f"{pkg_name}: {title}",
                    remediation=remediation,
                    resolved=False,
                )
            )

    return findings
