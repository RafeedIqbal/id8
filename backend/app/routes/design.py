from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies.idempotency import get_idempotency_key
from app.design.auth_cache import cache_stitch_auth, get_cached_stitch_auth
from app.design.base import (
    DesignFeedback,
    DesignOutput,
    Screen,
    ScreenComponent,
    StitchAuthContext,
    StitchAuthError,
)
from app.design.provider_factory import regenerate_with_fallback
from app.design.stitch_mcp import STITCH_TOOLS
from app.models.enums import ArtifactType, DesignProvider, ProjectStatus
from app.models.project import Project
from app.models.project_artifact import ProjectArtifact
from app.models.project_run import ProjectRun
from app.schemas.artifact import ArtifactResponse, ProjectArtifactResponse
from app.schemas.design import DesignFeedbackRequest, DesignGenerateRequest, StitchAuthPayload

router = APIRouter(tags=["design"])

_DESIGN_VALID_STATUSES = {ProjectStatus.PRD_APPROVED, ProjectStatus.DESIGN_DRAFT}


async def _latest_run(db: AsyncSession, project_id: uuid.UUID) -> ProjectRun:
    result = await db.execute(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id)
        .order_by(ProjectRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=409, detail="No active run for this project")
    return run


async def _next_design_version(db: AsyncSession, project_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(ProjectArtifact.version), 0)).where(
            ProjectArtifact.project_id == project_id,
            ProjectArtifact.artifact_type == ArtifactType.DESIGN_SPEC,
        )
    )
    return (result.scalar() or 0) + 1


async def _latest_completed_design_artifact(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> ProjectArtifact | None:
    result = await db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.project_id == project_id,
            ProjectArtifact.artifact_type == ArtifactType.DESIGN_SPEC,
        )
        .order_by(ProjectArtifact.version.desc())
    )

    for artifact in result.scalars():
        content = artifact.content
        if isinstance(content, dict) and content.get("status") == "pending":
            continue
        return artifact
    return None


def _auth_from_payload(payload: StitchAuthPayload | None) -> StitchAuthContext | None:
    if payload is None:
        return None
    return StitchAuthContext.from_mapping(payload.model_dump(exclude_none=True))


def _design_output_from_content(content: dict[str, Any]) -> DesignOutput:
    screens: list[Screen] = []
    raw_screens = content.get("screens", [])
    if not isinstance(raw_screens, list):
        return DesignOutput()

    for rs in raw_screens:
        if not isinstance(rs, dict):
            continue
        raw_components = rs.get("components", [])
        components: list[ScreenComponent] = []
        if isinstance(raw_components, list):
            for rc in raw_components:
                if not isinstance(rc, dict):
                    continue
                components.append(
                    ScreenComponent(
                        id=str(rc.get("id", "")),
                        name=str(rc.get("name", "")),
                        type=str(rc.get("type", "")),
                        properties=rc.get("properties", {}),
                    )
                )

        screens.append(
            Screen(
                id=str(rs.get("id", "")),
                name=str(rs.get("name", "")),
                description=str(rs.get("description", "")),
                components=components,
                assets=rs.get("assets", []),
            )
        )

    return DesignOutput(screens=screens)


@router.get(
    "/design/tools",
    operation_id="listDesignTools",
)
async def list_design_tools() -> dict[str, Any]:
    return {
        "provider": DesignProvider.STITCH_MCP.value,
        "usable_tools": STITCH_TOOLS,
    }


@router.post(
    "/projects/{projectId}/design/generate",
    operation_id="generateDesign",
    response_model=ArtifactResponse,
    status_code=202,
)
async def generate_design(
    body: DesignGenerateRequest,
    project_id: uuid.UUID = Path(alias="projectId"),
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status not in _DESIGN_VALID_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot generate design in status {project.status}")

    run = await _latest_run(db, project_id)
    version = await _next_design_version(db, project_id)

    # Store provider/auth config in the pending artifact so the orchestrator
    # handler can retrieve it when the GenerateDesign node executes.
    content: dict[str, Any] = {
        "status": "pending",
        "provider": body.provider.value,
    }
    if body.prompt_constraints:
        content["design_constraints"] = body.prompt_constraints
    if body.stitch_auth:
        auth = _auth_from_payload(body.stitch_auth)
        if auth is not None:
            cache_stitch_auth(run.id, auth)
            content["stitch_auth_method"] = auth.auth_method.value

    artifact = ProjectArtifact(
        project_id=project_id,
        run_id=run.id,
        artifact_type=ArtifactType.DESIGN_SPEC,
        version=version,
        model_profile=body.model_profile,
        content=content,
    )
    db.add(artifact)

    # Transition to design_draft if not already
    if project.status != ProjectStatus.DESIGN_DRAFT:
        project.status = ProjectStatus.DESIGN_DRAFT

    await db.commit()
    await db.refresh(artifact)

    return {"artifact": ProjectArtifactResponse.model_validate(artifact)}


@router.post(
    "/projects/{projectId}/design/feedback",
    operation_id="submitDesignFeedback",
    response_model=ArtifactResponse,
    status_code=202,
)
async def submit_design_feedback(
    body: DesignFeedbackRequest,
    project_id: uuid.UUID = Path(alias="projectId"),
    idempotency_key: str | None = Depends(get_idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != ProjectStatus.DESIGN_DRAFT:
        raise HTTPException(status_code=409, detail="Design feedback only accepted in design_draft status")

    run = await _latest_run(db, project_id)
    previous_artifact = await _latest_completed_design_artifact(db, project_id)
    if previous_artifact is None:
        raise HTTPException(status_code=409, detail="No existing design artifact available for feedback")

    previous_content = previous_artifact.content
    if not isinstance(previous_content, dict):
        raise HTTPException(status_code=500, detail="Existing design artifact has invalid content")

    previous_design = _design_output_from_content(previous_content)
    previous_meta = previous_content.get("__design_metadata", {})
    if not isinstance(previous_meta, dict):
        previous_meta = {}

    preferred_provider_raw = previous_meta.get("provider_used") or previous_meta.get("provider")
    try:
        preferred_provider = DesignProvider(str(preferred_provider_raw))
    except ValueError:
        preferred_provider = DesignProvider.STITCH_MCP

    auth = _auth_from_payload(body.stitch_auth)
    if auth is not None:
        cache_stitch_auth(run.id, auth)
    elif preferred_provider == DesignProvider.STITCH_MCP:
        auth = get_cached_stitch_auth(run.id)

    feedback = DesignFeedback(
        feedback_text=body.feedback_text,
        target_screen_id=body.target_screen_id,
        target_component_id=body.target_component_id,
    )

    try:
        regenerated, provider_used = await regenerate_with_fallback(
            previous=previous_design,
            feedback=feedback,
            auth=auth,
            preferred_provider=preferred_provider,
        )
    except StitchAuthError as exc:
        raise HTTPException(status_code=401, detail=exc.action_payload) from exc

    version = await _next_design_version(db, project_id)
    artifact_content = regenerated.to_dict()

    merged_meta = dict(previous_meta)
    merged_meta.update(regenerated.metadata or {})
    merged_meta.update(
        {
            "provider_used": str(provider_used),
            "feedback_text": body.feedback_text,
        }
    )
    if body.target_screen_id:
        merged_meta["target_screen_id"] = body.target_screen_id
    if body.target_component_id:
        merged_meta["target_component_id"] = body.target_component_id
    artifact_content["__design_metadata"] = merged_meta

    artifact = ProjectArtifact(
        project_id=project_id,
        run_id=run.id,
        artifact_type=ArtifactType.DESIGN_SPEC,
        version=version,
        model_profile=previous_artifact.model_profile,
        content=artifact_content,
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)

    return {"artifact": ProjectArtifactResponse.model_validate(artifact)}
