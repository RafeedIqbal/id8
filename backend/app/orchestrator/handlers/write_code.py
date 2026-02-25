"""WriteCode node handler — generates a full code snapshot from approved artifacts.

Calls the LLM with the ``customtools`` model profile to produce structured
source code from the approved PRD, design spec, and tech plan.  When the
SecurityGate fails and loops back, this handler incorporates the security
findings into a remediation prompt.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.models.enums import ArtifactType
from app.models.project_artifact import ProjectArtifact
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.write_code")

# How many times to retry when the LLM returns invalid JSON.
_MAX_PARSE_RETRIES = 1


async def generate_with_fallback(*args: Any, **kwargs: Any) -> Any:
    """Late-bound wrapper to avoid llm/orchestrator circular imports in tests."""
    from app.llm.client import generate_with_fallback as _generate_with_fallback

    return await _generate_with_fallback(*args, **kwargs)


class WriteCodeHandler(NodeHandler):
    """Generate a full code snapshot via LLM from approved artifacts."""

    async def execute(self, ctx: RunContext) -> NodeResult:
        from app.llm.prompts.code_generation import build_prompts
        from app.llm.router import resolve_profile

        # 1. Verify required inputs.
        tech_plan = _clean_artifact_content(ctx.previous_artifacts.get("tech_plan"))
        if not tech_plan:
            return NodeResult(
                outcome="failure",
                error="No approved tech plan artifact available",
            )

        design = _clean_artifact_content(ctx.previous_artifacts.get("design_spec"))
        if not design:
            return NodeResult(
                outcome="failure",
                error="No approved design artifact available",
            )

        prd = _clean_artifact_content(ctx.previous_artifacts.get("prd"))

        # 2. Check for security gate feedback (remediation loop).
        feedback = await _load_security_feedback(ctx)

        # 3. Build prompts with all available context.
        profile = resolve_profile(ctx.current_node)
        artifacts_for_prompt: dict[str, Any] = {
            "tech_plan": tech_plan,
            "design_spec": design,
            "prd": prd,
        }

        # Include previous code snapshot if we're in a remediation loop.
        if feedback:
            code_snapshot = _clean_artifact_content(
                ctx.previous_artifacts.get("code_snapshot")
            )
            if code_snapshot:
                artifacts_for_prompt["code_snapshot"] = code_snapshot

        system_prompt, user_prompt = build_prompts(
            previous_artifacts=artifacts_for_prompt,
            feedback=feedback,
        )

        # 4. Capture artifact lineage.
        source_artifacts = await _load_source_artifact_references(ctx)

        # 5. Call LLM with retry on parse failure.
        last_error: str | None = None
        for attempt in range(_MAX_PARSE_RETRIES + 1):
            effective_system = system_prompt
            if attempt > 0 and last_error:
                effective_system += (
                    "\n\nIMPORTANT: Your previous response was not valid JSON. "
                    f"Error: {last_error}\n"
                    "You MUST return ONLY a valid JSON object, no markdown fences or extra text."
                )

            llm_response = await generate_with_fallback(
                profile=profile,
                node_name=ctx.current_node,
                prompt=user_prompt,
                system_prompt=effective_system,
            )

            # 6. Parse and validate.
            snapshot_data, parse_error = _parse_code_response(llm_response.content)
            if snapshot_data is not None:
                # 7. Run basic validation on generated files.
                validation_errors = _validate_code_snapshot(snapshot_data)
                if validation_errors:
                    logger.warning(
                        "Code snapshot validation warnings for project=%s: %s",
                        ctx.project_id,
                        "; ".join(validation_errors),
                    )
                    # Attach warnings but don't fail — the security gate
                    # will catch critical issues.
                    snapshot_data["__validation_warnings"] = validation_errors

                snapshot_data["__code_metadata"] = {
                    "source_artifacts": source_artifacts,
                    "security_feedback": feedback or "",
                    "file_count": len(snapshot_data.get("files", [])),
                    "total_loc": sum(
                        f.get("content", "").count("\n") + 1
                        for f in snapshot_data.get("files", [])
                    ),
                }

                logger.info(
                    "Generated code snapshot for project=%s (%d files, attempt=%d, model=%s)",
                    ctx.project_id,
                    len(snapshot_data.get("files", [])),
                    attempt + 1,
                    llm_response.model_id,
                )
                return NodeResult(
                    outcome="success",
                    artifact_data=snapshot_data,
                    llm_response=llm_response,
                )

            last_error = parse_error
            logger.warning(
                "Code snapshot parse failed (attempt %d/%d): %s",
                attempt + 1,
                _MAX_PARSE_RETRIES + 1,
                parse_error,
            )

        # All parse retries exhausted.
        logger.error(
            "Code generation failed schema validation after retries: %s",
            last_error,
        )
        return NodeResult(
            outcome="failure",
            error=f"Code snapshot schema validation failed after retries: {last_error}",
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_security_feedback(ctx: RunContext) -> str | None:
    """Load the most recent security report findings if this is a remediation loop.

    When SecurityGate fails, the transition table routes back to WriteCode.
    We detect this by checking for an existing security_report artifact.
    """
    result = await ctx.db.execute(
        select(ProjectArtifact)
        .where(
            ProjectArtifact.run_id == ctx.run_id,
            ProjectArtifact.artifact_type == ArtifactType.SECURITY_REPORT,
        )
        .order_by(ProjectArtifact.version.desc())
        .limit(1)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        return None

    content = artifact.content or {}
    findings = content.get("findings", [])
    if not findings:
        return None

    # Format findings into a readable string for the LLM.
    parts = []
    for finding in findings:
        severity = finding.get("severity", "unknown")
        title = finding.get("title", finding.get("description", "Untitled"))
        detail = finding.get("detail", finding.get("description", ""))
        file_path = finding.get("file", "")
        line = finding.get("line", "")
        loc = f" ({file_path}:{line})" if file_path else ""
        parts.append(f"- [{severity.upper()}]{loc} {title}: {detail}")

    return "\n".join(parts)


def _clean_artifact_content(raw: Any) -> dict[str, Any]:
    """Return a metadata-stripped artifact dict or ``{}`` when invalid."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("__")}


async def _load_source_artifact_references(ctx: RunContext) -> dict[str, dict[str, Any]]:
    """Return artifact references used in this run for traceability."""
    refs: dict[str, dict[str, Any]] = {}

    for key, artifact_type in (
        ("prd", ArtifactType.PRD),
        ("design_spec", ArtifactType.DESIGN_SPEC),
        ("tech_plan", ArtifactType.TECH_PLAN),
    ):
        result = await ctx.db.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.run_id == ctx.run_id,
                ProjectArtifact.artifact_type == artifact_type,
            )
            .order_by(ProjectArtifact.version.desc())
            .limit(1)
        )
        artifact = result.scalar_one_or_none()
        refs[key] = {
            "artifact_type": str(artifact_type),
            "artifact_id": str(artifact.id) if artifact is not None else "",
            "run_id": str(artifact.run_id) if artifact is not None else "",
            "version": artifact.version if artifact is not None else 0,
        }

    return refs


def _parse_code_response(content: str) -> tuple[dict | None, str | None]:
    """Try to parse the LLM response into a validated code snapshot dict.

    Returns ``(snapshot_dict, None)`` on success or ``(None, error_message)``
    on failure.
    """
    from app.schemas.code_snapshot import CodeSnapshotContent

    # Strip markdown fences if the model wrapped the JSON.
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"

    try:
        snapshot = CodeSnapshotContent.model_validate(raw)
    except ValidationError as exc:
        return None, f"Schema validation failed: {exc}"

    return snapshot.model_dump(), None


def _validate_code_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """Run basic validation on a parsed code snapshot.

    Returns a list of warning strings (empty if everything looks good).
    These are non-fatal — the security gate will catch critical issues.
    """
    warnings: list[str] = []
    files = snapshot.get("files", [])

    if not files:
        warnings.append("Code snapshot contains no files")
        return warnings

    # Collect all file paths for cross-reference checking.
    file_paths = {f["path"] for f in files}

    # Check entry point exists.
    entry_point = snapshot.get("entry_point", "")
    if entry_point and entry_point not in file_paths:
        warnings.append(f"Entry point '{entry_point}' not found in generated files")

    # Check for basic Python syntax (AST parse) on .py files.
    for f in files:
        path = f.get("path", "")
        content = f.get("content", "")
        if path.endswith(".py") and content.strip():
            error = _check_python_syntax(content, path)
            if error:
                warnings.append(error)

    # Check that required file types are present.
    has_config = any(
        f["path"].endswith(name)
        for f in files
        for name in (
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "Cargo.toml",
        )
    )
    if not has_config:
        warnings.append("No dependency manifest found (package.json, requirements.txt, etc.)")

    return warnings


def _check_python_syntax(source: str, path: str) -> str | None:
    """Return an error string if *source* has a Python syntax error, else None."""
    import ast

    try:
        ast.parse(source)
    except SyntaxError as exc:
        line_info = f" (line {exc.lineno})" if exc.lineno else ""
        return f"Python syntax error in {path}{line_info}: {exc.msg}"
    return None
