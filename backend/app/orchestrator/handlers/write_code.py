"""WriteCode node handler — generates a full merged code snapshot from approved artifacts.

Code generation is performed in phased chunks on top of the template project
to stay within token limits. The handler then assembles the merged snapshot
and runs static validation checks before artifact creation. When SecurityGate
fails and loops back, unresolved high/critical findings are fed into
generation as a remediation instruction.
"""

from __future__ import annotations

import ast
import json
import logging
import posixpath
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.models.enums import ArtifactType
from app.models.project_artifact import ProjectArtifact
from app.observability import emit_llm_usage_event
from app.orchestrator.base import NodeHandler, NodeResult, RunContext

logger = logging.getLogger("id8.orchestrator.handlers.write_code")

# How many times to retry when the LLM returns invalid JSON.
_MAX_PARSE_RETRIES = 1
_MAX_VALIDATION_REPAIR_ATTEMPTS = 1
_GENERATION_PHASES = ("shared_foundation", "pages")
_MAX_REPAIR_CONTEXT_FILES = 40
_MAX_REPAIR_FILE_CHARS = 4000
_NPM_LOCKFILE_TIMEOUT_SECONDS = 180
_DEPENDENCY_MANIFESTS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "poetry.lock",
    "Cargo.toml",
    "go.mod",
)
_CONFIG_FILE_NAMES = (
    ".env.example",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "next.config.js",
    "next.config.mjs",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    "alembic.ini",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
)
_TS_IMPORT_RE = re.compile(
    r"""(?x)
    (?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]
    |require\(\s*['"]([^'"]+)['"]\s*\)
"""
)
_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+")
_NPM_PACKAGE_NAME_RE = re.compile(r"^(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+$")

_ALLOWED_OVERRIDE_PATHS = {"app/page.tsx", "app/layout.tsx", "app/globals.css"}
_ALLOWED_NEW_DIRS = (
    "app/",
    "components/",
    "lib/",
    "types/",
    "data/",
    "public/",
)


def _is_path_allowed(path: str) -> bool:
    if path in _ALLOWED_OVERRIDE_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _ALLOWED_NEW_DIRS)


_REPAIR_SYSTEM_PROMPT = """\
You are fixing a generated code snapshot that failed static validation.

Return ONLY valid JSON:
{
  "files": [
    {"path": "relative/path.ext", "content": "full file contents", "language": "javascript"}
  ]
}

Rules:
1. Return only files that must be added or replaced to resolve validation errors.
2. Preserve project architecture and existing file paths.
3. Ensure JS/TS/Python syntax is valid.
4. Ensure relative imports resolve to files in the snapshot (create missing files if required).
5. Do not include secrets.
"""

_REPAIR_USER_PROMPT = """\
Repair the generated code snapshot using the validation errors below.

## Validation Errors (must fix all)
{validation_errors}

## Existing File Inventory
{file_inventory}

## Relevant Existing Files
{file_context}

Return ONLY JSON with a `files` array containing the corrected/new files.
"""


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
        design = _clean_artifact_content(ctx.previous_artifacts.get("design_spec"))
        if not design:
            return NodeResult(
                outcome="failure",
                error="No approved design artifact available",
            )

        prd = _clean_artifact_content(ctx.previous_artifacts.get("prd"))

        # 2. Check for security gate feedback (remediation loop) or validation feedback
        feedback = await _load_security_feedback(ctx)

        validation_errors_from_prev = []
        code_snapshot = _clean_artifact_content(ctx.previous_artifacts.get("code_snapshot"))
        if code_snapshot:
            meta = code_snapshot.get("__code_metadata", {})
            validation_errors_from_prev = meta.get("validation_errors", [])
            if validation_errors_from_prev:
                val_text = "\n".join(f"- {err}" for err in validation_errors_from_prev)
                val_feedback = f"Previous code snapshot validation failed with the following errors:\n{val_text}"
                feedback = f"{feedback}\n\n{val_feedback}" if feedback else val_feedback

        validation_loop_count = int(ctx.workflow_payload.get("validation_loop_count", 0))
        if validation_errors_from_prev and validation_loop_count >= 2:
            return NodeResult(
                outcome="failure",
                error="Exceeded maximum validation repair loops (2 attempts).",
            )

        # 3. Build generation context.
        profile = resolve_profile(ctx.current_node)
        artifacts_for_prompt: dict[str, Any] = {
            "design_spec": design,
            "prd": prd,
        }

        # Include previous code snapshot if we're in a remediation or validation loop.
        if feedback and code_snapshot:
            artifacts_for_prompt["code_snapshot"] = code_snapshot

        # 4. Capture artifact lineage.
        source_artifacts = await _load_source_artifact_references(ctx)

        from app.codegen.template_project import (
            TemplateProjectConfigError,
            get_template_filepaths,
            load_template_tree,
            merge_project,
            resolve_template_dir,
        )
        from app.config import settings
        from app.schemas.code_snapshot import CodeFile

        # 4.5 Load Template Context
        try:
            template_dir = str(resolve_template_dir(settings.codegen_template_dir))
            template_inventory = get_template_filepaths(template_dir)
            template_files = load_template_tree(template_dir)
        except TemplateProjectConfigError as exc:
            return NodeResult(outcome="failure", error=str(exc))

        key_files = {"package.json", "app/layout.tsx", "app/page.tsx", "app/globals.css"}
        template_files_dict = {f.path: f.content for f in template_files if f.path in key_files}

        template_context = {
            "inventory": template_inventory,
            "files": template_files_dict,
        }

        # 5. Generate files in structured chunks.
        files_by_path: dict[str, dict[str, str]] = {}
        all_package_requirements: dict[str, dict[str, str]] = {}
        phase_file_counts: dict[str, int] = {}
        last_llm_response: Any | None = None
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_estimated_cost_usd = 0.0
        repair_attempted = False

        for phase in _GENERATION_PHASES:
            system_prompt, user_prompt = build_prompts(
                previous_artifacts=artifacts_for_prompt,
                feedback=feedback,
                chunk=phase,
                generated_files=list(files_by_path.values()),
                template_context=template_context,
            )
            chunk_files, chunk_requirements, llm_response, chunk_error = await _generate_chunk(
                profile=profile,
                node_name=ctx.current_node,
                phase=phase,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            if chunk_error:
                logger.error(
                    "Code generation failed in phase=%s for project=%s: %s",
                    phase,
                    ctx.project_id,
                    chunk_error,
                )
                return NodeResult(
                    outcome="failure",
                    error=f"Code generation failed during '{phase}' phase: {chunk_error}",
                )

            if llm_response is not None:
                last_llm_response = llm_response
                total_prompt_tokens += llm_response.token_usage.prompt_tokens
                total_completion_tokens += llm_response.token_usage.completion_tokens
                estimated_cost_usd = await emit_llm_usage_event(
                    project_id=ctx.project_id,
                    run_id=ctx.run_id,
                    node=f"{ctx.current_node}:{phase}",
                    model_profile=llm_response.profile_used,
                    model_id=llm_response.model_id,
                    prompt_tokens=llm_response.token_usage.prompt_tokens,
                    completion_tokens=llm_response.token_usage.completion_tokens,
                    db=ctx.db,
                )
                total_estimated_cost_usd += estimated_cost_usd

            phase_file_counts[phase] = 0
            for item in chunk_files:
                path = str(item.get("path", "")).strip()
                if not path or not _is_path_allowed(path):
                    continue
                normalized = {
                    "path": path,
                    "content": str(item.get("content", "")),
                    "language": str(item.get("language", "text")),
                }
                existing = files_by_path.get(path)
                if existing != normalized:
                    files_by_path[path] = normalized
                    phase_file_counts[phase] += 1

            _merge_package_requirements(all_package_requirements, chunk_requirements)

        if not files_by_path:
            return NodeResult(
                outcome="failure",
                error="Code generation returned no allowed files across all phases",
            )

        # 6. Assemble and validate the full merged snapshot.
        ai_code_files = [CodeFile(**f) for f in files_by_path.values()]
        try:
            merged_files = merge_project(template_dir, ai_code_files)
        except ValueError as e:
            return NodeResult(
                outcome="failure",
                error=f"Template merge failed: {e}",
            )

        merged_files, dependency_resolution_errors = _resolve_npm_package_files(
            merged_files,
            _ordered_package_requirements(all_package_requirements),
        )
        merged_files_dict = {f.path: f.model_dump() for f in merged_files}
        snapshot_data = _assemble_code_snapshot(list(merged_files_dict.values()))
        validation_errors = dependency_resolution_errors + _validate_code_snapshot(snapshot_data)
        for _ in range(_MAX_VALIDATION_REPAIR_ATTEMPTS):
            if not validation_errors:
                break

            repair_attempted = True
            repair_system_prompt, repair_user_prompt = _build_validation_repair_prompts(
                validation_errors=validation_errors,
                files_by_path=merged_files_dict,
            )
            repair_files, repair_requirements, repair_llm_response, repair_error = await _generate_chunk(
                profile=profile,
                node_name=f"{ctx.current_node}:repair",
                phase="repair",
                system_prompt=repair_system_prompt,
                user_prompt=repair_user_prompt,
            )
            if repair_error:
                remediation = "\n".join(f"- {err}" for err in validation_errors)
                return NodeResult(
                    outcome="failure",
                    error=(
                        "Code snapshot validation failed. Repair pass could not produce valid JSON.\n"
                        f"Repair error: {repair_error}\n"
                        "Remediation required:\n" + remediation
                    ),
                    context_updates={"validation_errors": validation_errors, "repair_attempted": True},
                )
            if not repair_files:
                remediation = "\n".join(f"- {err}" for err in validation_errors)
                return NodeResult(
                    outcome="failure",
                    error=(
                        "Code snapshot validation failed. Repair pass returned no file updates.\n"
                        "Remediation required:\n" + remediation
                    ),
                    context_updates={"validation_errors": validation_errors, "repair_attempted": True},
                )

            if repair_llm_response is not None:
                last_llm_response = repair_llm_response
                total_prompt_tokens += repair_llm_response.token_usage.prompt_tokens
                total_completion_tokens += repair_llm_response.token_usage.completion_tokens
                estimated_cost_usd = await emit_llm_usage_event(
                    project_id=ctx.project_id,
                    run_id=ctx.run_id,
                    node=f"{ctx.current_node}:repair",
                    model_profile=repair_llm_response.profile_used,
                    model_id=repair_llm_response.model_id,
                    prompt_tokens=repair_llm_response.token_usage.prompt_tokens,
                    completion_tokens=repair_llm_response.token_usage.completion_tokens,
                    db=ctx.db,
                )
                total_estimated_cost_usd += estimated_cost_usd

            phase_file_counts["repair"] = 0
            for item in repair_files:
                path = str(item.get("path", "")).strip()
                if not path or not _is_path_allowed(path):
                    continue
                normalized = {
                    "path": path,
                    "content": str(item.get("content", "")),
                    "language": str(item.get("language", "text")),
                }
                existing = files_by_path.get(path)
                if existing != normalized:
                    files_by_path[path] = normalized
                    phase_file_counts["repair"] += 1

            _merge_package_requirements(all_package_requirements, repair_requirements)

            ai_code_files = [CodeFile(**f) for f in files_by_path.values()]
            try:
                merged_files = merge_project(template_dir, ai_code_files)
            except ValueError as e:
                return NodeResult(
                    outcome="failure",
                    error=f"Repair failed on merge: {e}",
                    context_updates={"validation_errors": validation_errors, "repair_attempted": True},
                )

            merged_files, dependency_resolution_errors = _resolve_npm_package_files(
                merged_files,
                _ordered_package_requirements(all_package_requirements),
            )
            merged_files_dict = {f.path: f.model_dump() for f in merged_files}
            snapshot_data = _assemble_code_snapshot(list(merged_files_dict.values()))
            validation_errors = dependency_resolution_errors + _validate_code_snapshot(snapshot_data)

        if validation_errors:
            remediation = "\n".join(f"- {err}" for err in validation_errors)
            logger.error(
                "Code snapshot validation failed for project=%s: %s",
                ctx.project_id,
                "; ".join(validation_errors),
            )

            # Persist the snapshot even though it's invalid, so the next loop can read the errors and code.
            snapshot_data["__code_metadata"] = {
                "validation_errors": validation_errors,
            }
            return NodeResult(
                outcome="failed",
                error="Code snapshot validation failed. Remediation required:\n" + remediation,
                artifact_data=snapshot_data,  # Return it so orchestrator saves the intermediate state
                context_updates={
                    "validation_errors": validation_errors,
                    "repair_attempted": repair_attempted,
                    "validation_loop_count": validation_loop_count + 1,
                },
            )

        if last_llm_response is None:
            return NodeResult(
                outcome="failure",
                error="Code generation completed without a model response",
            )

        snapshot_data["__code_metadata"] = {
            "source_artifacts": source_artifacts,
            "security_feedback": feedback or "",
            "template_dir": template_dir,
            "template_file_count": len(template_files),
            "ai_delta_file_count": len(files_by_path),
            "merged_file_count": len(merged_files),
            "allowed_override_paths": list(_ALLOWED_OVERRIDE_PATHS),
            "package_requirements": _ordered_package_requirements(all_package_requirements),
            "is_authoritative_merged_tree": True,
            "file_count": len(snapshot_data.get("files", [])),
            "total_loc": sum(f.get("content", "").count("\n") + 1 for f in snapshot_data.get("files", [])),
            "generation_phases": list(_GENERATION_PHASES),
            "phase_file_counts": phase_file_counts,
            "repair_attempted": repair_attempted,
            "repair_updates": phase_file_counts.get("repair", 0),
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "estimated_cost_usd": round(total_estimated_cost_usd, 8),
        }

        logger.info(
            "Generated code snapshot for project=%s (%d files, model=%s)",
            ctx.project_id,
            len(snapshot_data.get("files", [])),
            last_llm_response.model_id,
        )
        return NodeResult(
            outcome="success",
            artifact_data=snapshot_data,
            llm_response=last_llm_response,
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

    # Include only unresolved high/critical findings.
    parts = []
    for finding in findings:
        severity = str(finding.get("severity", "unknown")).lower()
        if severity not in {"high", "critical"}:
            continue
        if _finding_is_resolved(finding):
            continue

        # Support both legacy security-report keys and the normalized
        # SecurityFinding schema from Task 09.
        title = str(
            finding.get("title")
            or finding.get("rule_id")
            or finding.get("message")
            or finding.get("description")
            or "Untitled"
        )
        detail = str(finding.get("detail") or finding.get("message") or finding.get("description") or "")
        remediation = str(finding.get("remediation", "")).strip()
        if remediation:
            detail = f"{detail} Remediation: {remediation}" if detail else f"Remediation: {remediation}"

        file_path = str(finding.get("file_path") or finding.get("file") or "")
        line = finding.get("line_number", finding.get("line", ""))
        line_number: int | None = None
        if isinstance(line, int):
            line_number = line
        elif isinstance(line, str) and line.isdigit():
            line_number = int(line)

        if file_path and line_number and line_number > 0:
            loc = f" ({file_path}:{line_number})"
        elif file_path:
            loc = f" ({file_path})"
        else:
            loc = ""

        entry = f"- [{severity.upper()}]{loc} {title}"
        if detail:
            entry += f": {detail}"
        parts.append(entry)

    if not parts:
        return None

    return "\n".join(parts)


def _finding_is_resolved(finding: dict[str, Any]) -> bool:
    """Return True when a finding is explicitly marked as resolved."""
    resolved = finding.get("resolved")
    if isinstance(resolved, bool):
        return resolved
    status = str(finding.get("status", "unresolved")).lower()
    return status in {"resolved", "fixed", "dismissed", "ignored"}


def _clean_artifact_content(raw: Any) -> dict[str, Any]:
    """Return a metadata-stripped artifact dict or ``{}`` when invalid."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("__")}


def _build_validation_repair_prompts(
    *,
    validation_errors: list[str],
    files_by_path: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """Build prompts for a focused validation repair pass."""
    all_paths = sorted(files_by_path.keys())
    target_paths = _extract_paths_from_validation_errors(validation_errors)
    selected_paths = [path for path in all_paths if path in target_paths]
    if not selected_paths:
        selected_paths = all_paths[:_MAX_REPAIR_CONTEXT_FILES]

    # Keep context bounded to reduce token pressure.
    selected_paths = selected_paths[:_MAX_REPAIR_CONTEXT_FILES]

    file_context_parts: list[str] = []
    for path in selected_paths:
        file_data = files_by_path.get(path)
        if not file_data:
            continue
        language = str(file_data.get("language", ""))
        content = str(file_data.get("content", ""))
        if len(content) > _MAX_REPAIR_FILE_CHARS:
            content = content[:_MAX_REPAIR_FILE_CHARS] + "\n# ...truncated for repair context..."
        file_context_parts.append(f"### {path}\n```{language}\n{content}\n```")

    if not file_context_parts:
        file_context = "(no contextual files selected)"
    else:
        file_context = "\n\n".join(file_context_parts)

    validation_text = "\n".join(f"- {err}" for err in validation_errors)
    file_inventory = "\n".join(f"- {path}" for path in all_paths) if all_paths else "(none)"
    user_prompt = _REPAIR_USER_PROMPT.format(
        validation_errors=validation_text,
        file_inventory=file_inventory,
        file_context=file_context,
    )
    return _REPAIR_SYSTEM_PROMPT, user_prompt


def _extract_paths_from_validation_errors(errors: list[str]) -> set[str]:
    """Extract likely project file paths from validation error text."""
    known_extensions = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".json",
        ".sql",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".env",
        ".md",
        ".txt",
        ".html",
    }
    paths: set[str] = set()
    for error in errors:
        for token in _PATH_TOKEN_RE.findall(error):
            normalized = token.strip(" '\"")
            if normalized.startswith("."):
                continue
            if "/" not in normalized:
                continue
            if any(normalized.endswith(ext) for ext in known_extensions):
                paths.add(normalized)
    return paths


async def _load_source_artifact_references(ctx: RunContext) -> dict[str, dict[str, Any]]:
    """Return artifact references used in this run for traceability."""
    refs: dict[str, dict[str, Any]] = {}

    for key, artifact_type in (
        ("prd", ArtifactType.PRD),
        ("design_spec", ArtifactType.DESIGN_SPEC),
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


async def _generate_chunk(
    *,
    profile: Any,
    node_name: str,
    phase: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float | None = 1200.0,
) -> tuple[list[dict[str, str]], list[dict[str, str]], Any | None, str | None]:
    """Run a generation phase with parse retries and return files."""
    last_error: str | None = None
    last_response: Any | None = None

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
            node_name=node_name,
            prompt=user_prompt,
            system_prompt=effective_system,
            timeout=timeout,
        )
        last_response = llm_response

        chunk_data, parse_error = _parse_chunk_response(llm_response.content)
        if chunk_data is not None:
            return (
                chunk_data.get("files", []),
                chunk_data.get("package_requirements", []),
                llm_response,
                None,
            )

        last_error = parse_error
        logger.warning(
            "Code chunk parse failed (phase=%s attempt=%d/%d): %s",
            phase,
            attempt + 1,
            _MAX_PARSE_RETRIES + 1,
            parse_error,
        )

    return [], [], last_response, last_error or "Unknown parse failure"


def _parse_chunk_response(content: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a chunk response into ``{'files': [...]}``."""
    from app.schemas.code_snapshot import CodeChunkContent

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
        chunk = CodeChunkContent.model_validate(raw)
    except ValidationError as exc:
        return None, f"Schema validation failed: {exc}"

    return chunk.model_dump(), None


def _assemble_code_snapshot(files: list[dict[str, str]]) -> dict[str, Any]:
    """Create a validated CodeSnapshotContent dict from merged files."""
    from app.schemas.code_snapshot import CodeSnapshotContent

    ordered_files = sorted(files, key=lambda item: item.get("path", ""))
    paths = [f.get("path", "") for f in ordered_files]
    snapshot = CodeSnapshotContent(
        files=ordered_files,
        build_command=_infer_build_command(paths),
        test_command=_infer_test_command(paths),
        entry_point=_infer_entry_point(paths),
    )
    return snapshot.model_dump(by_alias=True)


def _merge_package_requirements(
    all_requirements: dict[str, dict[str, str]],
    new_requirements: list[dict[str, str]],
) -> None:
    """Merge package requirements by package name, preferring runtime deps over dev deps."""
    for requirement in new_requirements:
        name = str(requirement.get("name", "")).strip()
        if not name:
            continue

        section = str(requirement.get("section", "dependencies")).strip() or "dependencies"
        reason = str(requirement.get("reason", "")).strip()

        existing = all_requirements.get(name)
        if existing is None:
            all_requirements[name] = {
                "name": name,
                "section": section,
                "reason": reason,
            }
            continue

        if existing.get("section") != "dependencies" and section == "dependencies":
            existing["section"] = "dependencies"
        if reason and not existing.get("reason"):
            existing["reason"] = reason


def _ordered_package_requirements(all_requirements: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """Return package requirements in stable section/name order."""
    return sorted(
        all_requirements.values(),
        key=lambda item: (item.get("section", "dependencies"), item.get("name", "")),
    )


def _normalize_package_requirements(package_requirements: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    """Validate package requirements before handing them to npm."""
    normalized: dict[str, dict[str, str]] = {}
    errors: list[str] = []

    for index, requirement in enumerate(package_requirements, start=1):
        name = str(requirement.get("name", "")).strip()
        if not name:
            errors.append(f"package_requirements[{index}] is missing a package name")
            continue
        if not _NPM_PACKAGE_NAME_RE.fullmatch(name):
            errors.append(f"package_requirements[{index}] has an invalid npm package name: '{name}'")
            continue

        section = str(requirement.get("section", "dependencies")).strip() or "dependencies"
        if section not in {"dependencies", "devDependencies"}:
            errors.append(
                f"package_requirements[{index}] for '{name}' has invalid section '{section}'. "
                "Use 'dependencies' or 'devDependencies'."
            )
            continue

        reason = str(requirement.get("reason", "")).strip()
        existing = normalized.get(name)
        if existing is None:
            normalized[name] = {
                "name": name,
                "section": section,
                "reason": reason,
            }
            continue

        if existing["section"] != "dependencies" and section == "dependencies":
            existing["section"] = "dependencies"
        if reason and not existing["reason"]:
            existing["reason"] = reason

    return _ordered_package_requirements(normalized), errors


def _resolve_npm_package_files(
    files: list[Any],
    package_requirements: list[dict[str, str]],
) -> tuple[list[Any], list[str]]:
    """Resolve package requirements into a server-owned package.json and package-lock.json."""
    package_file = next((file for file in files if getattr(file, "path", "") == "package.json"), None)
    if package_file is None:
        return files, []

    try:
        base_package_json = json.loads(package_file.content)
    except json.JSONDecodeError as exc:
        return files, [f"package.json is not valid JSON: {exc.msg}"]
    if not isinstance(base_package_json, dict):
        return files, ["package.json must contain a JSON object"]

    normalized_requirements, requirement_errors = _normalize_package_requirements(package_requirements)
    if requirement_errors:
        return files, requirement_errors

    existing_dependencies = base_package_json.get("dependencies", {})
    existing_dev_dependencies = base_package_json.get("devDependencies", {})
    dependency_names: list[str] = []
    dev_dependency_names: list[str] = []

    for requirement in normalized_requirements:
        name = requirement["name"]
        if (
            isinstance(existing_dependencies, dict)
            and name in existing_dependencies
            or isinstance(existing_dev_dependencies, dict)
            and name in existing_dev_dependencies
        ):
            continue
        if requirement["section"] == "devDependencies":
            dev_dependency_names.append(name)
        else:
            dependency_names.append(name)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        (tmpdir_path / "package.json").write_text(package_file.content, encoding="utf-8")

        try:
            if dependency_names:
                result = _run_npm_install_command(
                    cwd=tmpdir,
                    package_names=dependency_names,
                    save_dev=False,
                )
                if result.returncode != 0:
                    failure_detail = _summarize_npm_failure(result.stderr or result.stdout)
                    requested = ", ".join(dependency_names)
                    return files, [
                        "npm dependency resolution failed while resolving dependencies "
                        f"({requested}): {failure_detail}"
                    ]

            if dev_dependency_names:
                result = _run_npm_install_command(
                    cwd=tmpdir,
                    package_names=dev_dependency_names,
                    save_dev=True,
                )
                if result.returncode != 0:
                    failure_detail = _summarize_npm_failure(result.stderr or result.stdout)
                    requested = ", ".join(dev_dependency_names)
                    return files, [
                        "npm dependency resolution failed while resolving devDependencies "
                        f"({requested}): {failure_detail}"
                    ]

            if not dependency_names and not dev_dependency_names:
                result = _run_npm_install_command(
                    cwd=tmpdir,
                    package_names=[],
                    save_dev=False,
                )
                if result.returncode != 0:
                    failure_detail = _summarize_npm_failure(result.stderr or result.stdout)
                    return files, [f"npm dependency resolution failed for package.json: {failure_detail}"]
        except FileNotFoundError:
            return files, ["npm is required to verify Vercel dependency resolution but is not installed"]
        except subprocess.TimeoutExpired:
            return files, [
                "npm dependency resolution timed out while generating package-lock.json "
                f"after {_NPM_LOCKFILE_TIMEOUT_SECONDS} seconds"
            ]

        resolved_package_json_path = tmpdir_path / "package.json"
        lockfile_path = tmpdir_path / "package-lock.json"
        if not resolved_package_json_path.is_file():
            return files, ["npm dependency resolution succeeded but did not write package.json"]
        if not lockfile_path.is_file():
            return files, ["npm dependency resolution succeeded but did not create package-lock.json"]

        resolved_package_json = resolved_package_json_path.read_text(encoding="utf-8")
        lockfile_content = lockfile_path.read_text(encoding="utf-8")

    file_type = type(package_file)
    updated_files = [
        file
        for file in files
        if getattr(file, "path", "") not in {"package.json", "package-lock.json"}
    ]
    updated_files.append(file_type(path="package.json", content=resolved_package_json, language="json"))
    updated_files.append(file_type(path="package-lock.json", content=lockfile_content, language="json"))
    return sorted(updated_files, key=lambda file: str(getattr(file, "path", ""))), []


def _run_npm_install_command(
    *,
    cwd: str,
    package_names: list[str],
    save_dev: bool,
) -> subprocess.CompletedProcess[str]:
    """Run npm install in lockfile-only mode for the requested package set."""
    command = [
        "npm",
        "install",
        "--package-lock-only",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
    ]
    if save_dev:
        command.append("--save-dev")
    if package_names:
        command.append("--save-exact")
        command.extend(package_names)

    return subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        text=True,
        timeout=_NPM_LOCKFILE_TIMEOUT_SECONDS,
        cwd=cwd,
    )


def _summarize_npm_failure(output: str) -> str:
    """Condense npm install output into a repair-friendly single-line error."""
    normalized_lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not normalized_lines:
        return "npm reported an unknown dependency resolution failure"

    cleaned_lines: list[str] = []
    for line in normalized_lines:
        cleaned = re.sub(r"^npm error\s*", "", line, flags=re.IGNORECASE).strip()
        if cleaned and cleaned not in cleaned_lines:
            cleaned_lines.append(cleaned)
        if len(cleaned_lines) >= 8:
            break

    if not cleaned_lines:
        return "npm reported an unknown dependency resolution failure"

    return " | ".join(cleaned_lines)


def _validate_code_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """Run basic validation on a parsed code snapshot.

    Returns a list of actionable validation errors (empty if valid).
    """
    errors: list[str] = []
    files = snapshot.get("files", [])

    if not files:
        errors.append("Code snapshot contains no files")
        return errors

    file_paths = {
        str(f.get("path", "")).strip() for f in files if isinstance(f, dict) and str(f.get("path", "")).strip()
    }
    if not file_paths:
        errors.append("Code snapshot contains files with missing/empty paths")
        return errors

    if any(path.startswith("app/") for path in file_paths) and any(path.startswith("src/app/") for path in file_paths):
        errors.append("Merged snapshot cannot contain both root-level 'app/' and 'src/app/' trees")

    has_python_files = any(path.endswith(".py") for path in file_paths)
    has_frontend_assets = any(
        path.endswith((".js", ".jsx", ".ts", ".tsx", ".html", ".vue", ".svelte"))
        or "frontend/" in path
        or path.startswith("src/")
        for path in file_paths
    )

    if has_python_files:
        errors.append(
            "Python files are not allowed for the fixed runtime profile. "
            "Generate a Next.js full-stack project for Vercel."
        )

    # Required files.
    entry_point = snapshot.get("entry_point", "")
    if not entry_point and has_frontend_assets and not _has_frontend_entrypoint(file_paths):
        errors.append("Frontend entry point is missing")
    elif entry_point not in file_paths and has_frontend_assets and not _has_frontend_entrypoint(file_paths):
        errors.append(f"Entry point '{entry_point}' not found and no frontend runtime entry file detected")

    if not any(_is_dependency_manifest(path) for path in file_paths):
        errors.append("No dependency manifest found (package.json, requirements.txt, etc.)")
    if not _has_nextjs_dependency(files):
        errors.append("package.json must include next.js dependencies for Vercel deployment")

    if not any(_is_configuration_file(path) for path in file_paths):
        errors.append("No configuration file found (e.g. Dockerfile, .env.example, tsconfig)")

    errors.extend(_validate_vercel_configs(files))

    python_modules = _build_python_module_index(file_paths)
    known_top_modules = {module.split(".", 1)[0] for module in python_modules if module}

    for f in files:
        path = f.get("path", "")
        content = f.get("content", "")
        if not path or not isinstance(content, str):
            continue

        if path.endswith(".py") and content.strip():
            tree, syntax_error = _parse_python_ast(content, path)
            if syntax_error:
                errors.append(syntax_error)
            elif tree is not None:
                errors.extend(
                    _check_python_imports(
                        path=path,
                        tree=tree,
                        file_paths=file_paths,
                        known_top_modules=known_top_modules,
                    )
                )

        if path.endswith((".ts", ".tsx", ".js", ".jsx")) and content.strip():
            if path.endswith("next-env.d.ts"):
                continue
            syntax_error = _check_jsts_syntax(content, path)
            if syntax_error:
                errors.append(syntax_error)
            errors.extend(_check_jsts_imports(path, content, file_paths))

    return errors


def _validate_vercel_configs(files: list[dict[str, Any]]) -> list[str]:
    """Validate generated vercel.json files for common invalid function patterns."""
    errors: list[str] = []

    for file_data in files:
        path = str(file_data.get("path", "")).strip()
        if not path.endswith("vercel.json"):
            continue

        content = file_data.get("content", "")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{path} is empty; remove it or provide valid JSON")
            continue

        try:
            config = json.loads(content)
        except json.JSONDecodeError as exc:
            errors.append(f"{path} is not valid JSON: {exc.msg}")
            continue

        if not isinstance(config, dict):
            errors.append(f"{path} must contain a JSON object")
            continue

        functions = config.get("functions")
        if functions is None:
            continue

        if not isinstance(functions, dict):
            errors.append(f"{path} field 'functions' must be an object mapping glob patterns")
            continue

        for pattern in functions:
            if not isinstance(pattern, str) or not pattern.strip():
                errors.append(f"{path} has a non-string function pattern")
                continue

            normalized = _normalize_vercel_function_pattern(pattern)
            if normalized.startswith("backend/"):
                errors.append(
                    f"{path} functions pattern '{pattern}' points to backend sources. "
                    "Vercel Serverless Functions must be under api/ (for example 'api/index.py')."
                )
                continue

            if normalized != "api" and not normalized.startswith("api/"):
                errors.append(
                    f"{path} functions pattern '{pattern}' is not under api/. "
                    "Use api/*.py or api/**/*.py and route into backend code from that entry file."
                )

    return errors


def _normalize_vercel_function_pattern(pattern: str) -> str:
    """Normalize a vercel.json function glob for path prefix checks."""
    normalized = pattern.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    return normalized


def _infer_entry_point(file_paths: list[str]) -> str:
    path_set = set(file_paths)

    for candidate in (
        "app/page.tsx",
        "app/page.jsx",
        "frontend/src/main.tsx",
        "frontend/src/main.jsx",
        "frontend/src/pages/index.tsx",
        "frontend/src/pages/index.jsx",
        "frontend/src/app/page.tsx",
        "frontend/src/app/page.jsx",
        "src/main.tsx",
        "src/main.jsx",
        "src/pages/index.tsx",
        "src/pages/index.jsx",
        "src/app/page.tsx",
        "src/app/page.jsx",
        "frontend/index.html",
        "index.html",
    ):
        if candidate in path_set:
            return candidate

    if file_paths:
        return sorted(file_paths)[0]
    return "app/page.tsx"


def _infer_build_command(file_paths: list[str]) -> str:
    if any(path.endswith("package.json") for path in file_paths):
        return "npm run build"
    if any(path.endswith(("requirements.txt", "pyproject.toml")) for path in file_paths):
        return "python -m compileall backend/app"
    return "echo build"


def _infer_test_command(file_paths: list[str]) -> str:
    if any(path.endswith("package.json") for path in file_paths):
        return "npx tsc --noEmit && npm run lint"
    if any(path.endswith((".py", "requirements.txt", "pyproject.toml")) for path in file_paths):
        return "pytest"
    return "echo test"


def _is_dependency_manifest(path: str) -> bool:
    return any(path.endswith(name) for name in _DEPENDENCY_MANIFESTS)


def _is_configuration_file(path: str) -> bool:
    return any(path.endswith(name) for name in _CONFIG_FILE_NAMES)


def _has_nextjs_dependency(files: list[dict[str, Any]]) -> bool:
    """Return True when at least one package manifest includes next.js."""
    for file_data in files:
        path = str(file_data.get("path", "")).strip()
        if not path.endswith("package.json"):
            continue
        content = file_data.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        try:
            package_json = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(package_json, dict):
            continue
        deps = package_json.get("dependencies")
        dev_deps = package_json.get("devDependencies")
        if isinstance(deps, dict) and "next" in deps:
            return True
        if isinstance(dev_deps, dict) and "next" in dev_deps:
            return True
    return False


def _build_python_module_index(file_paths: set[str]) -> set[str]:
    modules: set[str] = set()
    for path in file_paths:
        if not path.endswith(".py"):
            continue
        without_ext = path[:-3]
        parts = without_ext.split("/")
        for idx in range(len(parts)):
            suffix = parts[idx:]
            if suffix and suffix[-1] == "__init__":
                suffix = suffix[:-1]
            if suffix:
                modules.add(".".join(suffix))
    return modules


def _parse_python_ast(source: str, path: str) -> tuple[ast.Module | None, str | None]:
    try:
        return ast.parse(source), None
    except SyntaxError as exc:
        line_info = f" (line {exc.lineno})" if exc.lineno else ""
        return None, f"Python syntax error in {path}{line_info}: {exc.msg}"


def _check_python_imports(
    *,
    path: str,
    tree: ast.Module,
    file_paths: set[str],
    known_top_modules: set[str],
) -> list[str]:
    errors: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if _looks_like_local_python_module(module, known_top_modules) and not _python_module_exists(
                    module, file_paths
                ):
                    errors.append(f"Python import in {path} does not resolve in snapshot: '{module}'")

        if isinstance(node, ast.ImportFrom):
            if node.level > 0:
                resolved = _resolve_relative_python_import_path(
                    source_path=path,
                    level=node.level,
                    module=node.module,
                )
                if not resolved or not _python_path_exists(resolved, file_paths):
                    target = "." * node.level + (node.module or "")
                    errors.append(f"Relative Python import in {path} does not resolve in snapshot: '{target}'")
                continue

            module = node.module or ""
            if not module:
                continue
            if _looks_like_local_python_module(module, known_top_modules) and not _python_module_exists(
                module, file_paths
            ):
                errors.append(f"Python import in {path} does not resolve in snapshot: '{module}'")

    return errors


def _looks_like_local_python_module(module: str, known_top_modules: set[str]) -> bool:
    return module.split(".", 1)[0] in known_top_modules


def _python_module_exists(module: str, file_paths: set[str]) -> bool:
    module_path = module.replace(".", "/")
    direct_candidates = (
        f"{module_path}.py",
        f"{module_path}/__init__.py",
    )
    for candidate in direct_candidates:
        if candidate in file_paths:
            return True
        suffix = f"/{candidate}"
        if any(path.endswith(suffix) for path in file_paths):
            return True

    package_prefix = f"{module_path}/"
    if any(path.startswith(package_prefix) or f"/{package_prefix}" in path for path in file_paths):
        return True

    return False


def _resolve_relative_python_import_path(
    *,
    source_path: str,
    level: int,
    module: str | None,
) -> str | None:
    base_parts = source_path.split("/")[:-1]
    up_levels = max(level - 1, 0)
    if up_levels > len(base_parts):
        return None
    if up_levels:
        base_parts = base_parts[:-up_levels]
    if module:
        base_parts.extend(module.split("."))
    if not base_parts:
        return None
    return "/".join(base_parts)


def _python_path_exists(module_path: str, file_paths: set[str]) -> bool:
    for candidate in (f"{module_path}.py", f"{module_path}/__init__.py"):
        if candidate in file_paths:
            return True
    return False


def _check_jsts_syntax(source: str, path: str) -> str | None:
    stack: list[tuple[str, int]] = []
    in_single = False
    in_double = False
    in_template = False
    in_block_comment = False
    in_line_comment = False
    escape = False
    line = 1
    i = 0

    pairs = {"(": ")", "{": "}", "[": "]"}
    closing = {")": "(", "}": "{", "]": "["}

    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""

        if ch == "\n":
            line += 1
            in_line_comment = False

        if in_line_comment:
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_single or in_double or in_template:
            if escape:
                escape = False
                i += 1
                continue
            if ch == "\\":
                escape = True
                i += 1
                continue
            if in_single and ch == "'":
                in_single = False
            elif in_double and ch == '"':
                in_double = False
            elif in_template and ch == "`":
                in_template = False
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue

        if ch in pairs:
            stack.append((ch, line))
            i += 1
            continue
        if ch in closing:
            if not stack or stack[-1][0] != closing[ch]:
                return f"Syntax mismatch in {path} line {line}: unexpected '{ch}'"
            stack.pop()

        i += 1

    if in_single or in_double or in_template:
        return f"Unterminated string literal in {path}"
    if in_block_comment:
        return f"Unterminated block comment in {path}"
    if stack:
        opener, opener_line = stack[-1]
        expected = pairs[opener]
        return f"Syntax mismatch in {path} line {opener_line}: missing '{expected}'"
    return None


def _check_jsts_imports(path: str, source: str, file_paths: set[str]) -> list[str]:
    errors: list[str] = []
    for match in _TS_IMPORT_RE.finditer(source):
        spec = match.group(1) or match.group(2) or ""
        if not spec.startswith("."):
            continue
        if not _resolve_jsts_import(path, spec, file_paths):
            errors.append(f"JS/TS import in {path} does not resolve in snapshot: '{spec}'")
    return errors


def _has_frontend_entrypoint(file_paths: set[str]) -> bool:
    for candidate in (
        "app/page.tsx",
        "app/page.jsx",
        "frontend/src/main.tsx",
        "frontend/src/main.jsx",
        "frontend/src/pages/index.tsx",
        "frontend/src/pages/index.jsx",
        "frontend/src/app/page.tsx",
        "frontend/src/app/page.jsx",
        "src/main.tsx",
        "src/main.jsx",
        "src/pages/index.tsx",
        "src/pages/index.jsx",
        "src/app/page.tsx",
        "src/app/page.jsx",
        "frontend/index.html",
        "index.html",
    ):
        if candidate in file_paths:
            return True
    return False


def _resolve_jsts_import(path: str, spec: str, file_paths: set[str]) -> bool:
    base_dir = posixpath.dirname(path)
    target = posixpath.normpath(posixpath.join(base_dir, spec))
    target = target.lstrip("./")

    extensions = (".ts", ".tsx", ".js", ".jsx", ".json")
    candidates = [target]

    if not target.endswith(extensions):
        candidates.extend([f"{target}{ext}" for ext in extensions])
        candidates.extend([f"{target}/index{ext}" for ext in extensions])

    return any(candidate in file_paths for candidate in candidates)
