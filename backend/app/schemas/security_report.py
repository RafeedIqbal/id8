"""Security report schema — produced by the SecurityGate node.

Normalized representation of findings from SAST, dependency audit, and
secret scanning, plus the overall pass/fail verdict.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SecurityFinding(BaseModel):
    """A single normalized security finding."""

    rule_id: str
    severity: str  # critical, high, medium, low
    file_path: str
    line_number: int
    message: str
    remediation: str
    resolved: bool = False


class SecuritySummary(BaseModel):
    """Counts of findings by severity."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    total: int = 0


class SecurityReportContent(BaseModel):
    """Full security gate report persisted as a ProjectArtifact."""

    findings: list[SecurityFinding] = Field(default_factory=list)
    summary: SecuritySummary = Field(default_factory=SecuritySummary)
    scan_tools: list[str] = Field(default_factory=list)
    passed: bool  # True only when zero unresolved high/critical findings
