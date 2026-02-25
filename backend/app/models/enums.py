from __future__ import annotations

import enum


class DesignProvider(enum.StrEnum):
    STITCH_MCP = "stitch_mcp"
    INTERNAL_SPEC = "internal_spec"
    MANUAL_UPLOAD = "manual_upload"


class ModelProfile(enum.StrEnum):
    PRIMARY = "primary"
    CUSTOMTOOLS = "customtools"
    FALLBACK = "fallback"


class ProjectStatus(enum.StrEnum):
    IDEATION = "ideation"
    PRD_DRAFT = "prd_draft"
    PRD_APPROVED = "prd_approved"
    DESIGN_DRAFT = "design_draft"
    DESIGN_APPROVED = "design_approved"
    TECH_PLAN_DRAFT = "tech_plan_draft"
    TECH_PLAN_APPROVED = "tech_plan_approved"
    CODEGEN = "codegen"
    SECURITY_GATE = "security_gate"
    DEPLOY_READY = "deploy_ready"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"


class ArtifactType(enum.StrEnum):
    PRD = "prd"
    DESIGN_SPEC = "design_spec"
    TECH_PLAN = "tech_plan"
    CODE_SNAPSHOT = "code_snapshot"
    SECURITY_REPORT = "security_report"
    DEPLOY_REPORT = "deploy_report"


class ApprovalStage(enum.StrEnum):
    PRD = "prd"
    DESIGN = "design"
    TECH_PLAN = "tech_plan"
    DEPLOY = "deploy"


# Compatibility aliases matching the Task 01 naming convention.
DesignProviderEnum = DesignProvider
ModelProfileEnum = ModelProfile
ProjectStatusEnum = ProjectStatus
ArtifactTypeEnum = ArtifactType
ApprovalStageEnum = ApprovalStage

__all__ = [
    "ApprovalStage",
    "ApprovalStageEnum",
    "ArtifactType",
    "ArtifactTypeEnum",
    "DesignProvider",
    "DesignProviderEnum",
    "ModelProfile",
    "ModelProfileEnum",
    "ProjectStatus",
    "ProjectStatusEnum",
]
