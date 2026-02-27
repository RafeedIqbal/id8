"""SAST scanner — runs bandit on generated Python code.

Uses bandit for Python SAST. Returns normalized SecurityFinding objects.
If bandit is not installed the scanner logs a warning and returns an empty
list so the gate degrades gracefully rather than blocking.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.schemas.security_report import SecurityFinding

logger = logging.getLogger("id8.security.sast")

_SEVERITY_MAP: dict[str, str] = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}


async def run_sast(files: list[dict[str, Any]]) -> list[SecurityFinding]:
    """Run bandit SAST on Python files from the code snapshot.

    Parameters
    ----------
    files:
        List of ``{"path": str, "content": str, "language": str}`` dicts.

    Returns
    -------
    list[SecurityFinding]
        Normalized findings; empty when no Python files are present or bandit
        is unavailable.
    """
    python_files = [f for f in files if str(f.get("path", "")).endswith(".py")]
    if not python_files:
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        written_files = 0
        for f in python_files:
            dest = _safe_tmp_destination(tmpdir, str(f.get("path", "")))
            if dest is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(str(f.get("content", "")), encoding="utf-8")
            written_files += 1

        if written_files == 0:
            logger.warning("no safe Python paths available for SAST scan; skipping")
            return []

        try:
            result = subprocess.run(  # noqa: S603
                ["bandit", "-r", tmpdir, "-f", "json", "-q"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            logger.warning("bandit not installed; skipping SAST scan")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("bandit timed out after 60 s; skipping SAST scan")
            return []

        return _parse_bandit_output(result.stdout, tmpdir)


def _safe_tmp_destination(tmpdir: str, relative_path: str) -> Path | None:
    """Return a temp-file destination constrained to *tmpdir*.

    Paths that are absolute or traverse outside the temp root are rejected.
    """
    root = Path(tmpdir).resolve()
    path = Path(relative_path)
    if path.is_absolute():
        logger.warning("ignoring absolute path during SAST scan: %s", relative_path)
        return None

    dest = (root / path).resolve()
    if dest != root and root not in dest.parents:
        logger.warning("ignoring unsafe path during SAST scan: %s", relative_path)
        return None
    return dest


def _parse_bandit_output(output: str, tmpdir: str) -> list[SecurityFinding]:
    """Parse bandit JSON output into SecurityFinding objects."""
    if not output.strip():
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("bandit produced non-JSON output; skipping SAST findings")
        return []

    prefix = tmpdir.rstrip("/") + "/"
    findings: list[SecurityFinding] = []

    for issue in data.get("results", []):
        severity = _SEVERITY_MAP.get(str(issue.get("issue_severity", "")).upper(), "low")
        raw_path = str(issue.get("filename", ""))
        file_path = raw_path.removeprefix(prefix)

        findings.append(
            SecurityFinding(
                rule_id=str(issue.get("test_id", "UNKNOWN")),
                severity=severity,
                file_path=file_path,
                line_number=int(issue.get("line_number", 0)),
                message=str(issue.get("issue_text", "")),
                remediation=str(issue.get("more_info", "See bandit documentation for details")),
                resolved=False,
            )
        )

    return findings
