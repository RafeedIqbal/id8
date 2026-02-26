"""SecurityGate node handler.

Runs SAST (bandit), dependency audit (pip-audit / npm audit), and secret
scanning on the latest code_snapshot artifact.  Aggregates all findings into
a SecurityReportContent artifact and returns:

* ``"passed"``  — zero unresolved high/critical findings → transition to PreparePR
* ``"failed"``  — one or more blocking findings → loop back to WriteCode with
                  findings attached to ``context_updates`` for remediation
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.models.enums import ArtifactType
from app.models.project_artifact import ProjectArtifact
from app.orchestrator.base import NodeHandler, NodeResult, RunContext
from app.schemas.security_report import SecurityFinding, SecurityReportContent, SecuritySummary

logger = logging.getLogger("id8.orchestrator.handlers.security_gate")

_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


class SecurityGateHandler(NodeHandler):
    """Run all security scanners and determine pass/fail."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        from app.security.dependency_audit import run_dependency_audit
        from app.security.sast import run_sast
        from app.security.secret_scan import run_secret_scan

        # 1. Load the latest code_snapshot artifact.
        code_snapshot = await _load_latest_code_snapshot(ctx)
        if code_snapshot is None:
            return NodeResult(
                outcome="failure",
                error="No code_snapshot artifact found; SecurityGate cannot proceed",
            )

        files: list[dict[str, Any]] = code_snapshot.get("files", [])
        if not files:
            return NodeResult(
                outcome="failure",
                error="code_snapshot contains no files to scan",
            )

        # 2. Run all three scanners.
        scan_tools: list[str] = []

        sast_findings = await run_sast(files)
        scan_tools.append("bandit")

        dep_findings = await run_dependency_audit(files)
        scan_tools.append("pip-audit")
        scan_tools.append("npm-audit")

        secret_findings = await run_secret_scan(files)
        scan_tools.append("secret-scan")

        # 3. Aggregate.
        all_findings: list[SecurityFinding] = [
            *sast_findings,
            *dep_findings,
            *secret_findings,
        ]

        # 4. Build summary.
        summary = _build_summary(all_findings)

        # 5. Determine pass/fail: any unresolved high/critical finding blocks.
        blocking = [
            f
            for f in all_findings
            if f.severity.lower() in _BLOCKING_SEVERITIES and not f.resolved
        ]
        passed = len(blocking) == 0

        logger.info(
            "SecurityGate project=%s passed=%s critical=%d high=%d medium=%d low=%d",
            ctx.project_id,
            passed,
            summary.critical,
            summary.high,
            summary.medium,
            summary.low,
        )

        # 6. Build report artifact.
        report = SecurityReportContent(
            findings=all_findings,
            summary=summary,
            scan_tools=scan_tools,
            passed=passed,
        )

        outcome = "passed" if passed else "failed"
        context_updates: dict[str, Any] | None = None
        if not passed:
            context_updates = {
                "security_findings": [f.model_dump() for f in blocking],
            }

        return NodeResult(
            outcome=outcome,
            artifact_data=report.model_dump(),
            context_updates=context_updates,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_latest_code_snapshot(ctx: RunContext) -> dict[str, Any] | None:
    """Return the most recent code_snapshot artifact content for this run."""
    result = await ctx.db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.run_id == ctx.run_id,
            ProjectArtifact.artifact_type == ArtifactType.CODE_SNAPSHOT,
        )
        .order_by(ProjectArtifact.version.desc())
        .limit(1)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        return None
    return artifact.content


def _build_summary(findings: list[SecurityFinding]) -> SecuritySummary:
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        key = f.severity.lower()
        if key in counts:
            counts[key] += 1
    return SecuritySummary(
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
        total=len(findings),
    )
