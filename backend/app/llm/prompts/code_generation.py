"""Prompt templates for phased code generation."""
from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT_FULL = """\
You are an expert full-stack software engineer. Generate production-quality code.

Runtime profile is fixed:
- Framework: Next.js full-stack (App Router)
- Hosting: Vercel
- Database: none required by default

Rules:
1. Produce a complete, runnable Next.js project that deploys on Vercel without manual edits.
2. Include dependency manifests and runtime configuration.
3. Every local import must resolve to another file in the set.
4. Never include secrets. Use environment variables and `.env.example`.
5. If `vercel.json` is present, all function patterns must be under `api/`.
6. Prefer Next.js route handlers / server actions over external backend runtimes.
7. Dependency policy (MUST):
   - Check for deprecated, unmaintained, or known-vulnerable packages.
8. Build reliability (MUST):
   - Every imported package, CLI, loader, or config plugin must be declared in `package.json`.
   - Prevent module-not-found failures from config-driven plugins (for example `autoprefixer`) by
     either declaring the required dependency or omitting that plugin/config.
   - Keep dependency versions mutually compatible with the selected Next.js runtime.
9. Avoid backend or API elements, Make the web app self-contained, and purely frontend, match the provide design/context as closely as possble, with reactive front-end elements and animations.
10. Use the provided design spec and context to generate the code.
11. Use dummy data to populate the app so that all elements render and are interactive.

You MUST return a single valid JSON object:
{
  "files": [
    {"path": "relative/path/to/file.ext", "content": "full file contents", "language": "typescript"}
  ],
  "build_command": "npm run build",
  "test_command": "npm test",
  "entry_point": "src/app/page.tsx"
}

Return ONLY JSON.
"""

_SYSTEM_PROMPT_CHUNK = """\
You are an expert full-stack software engineer. Generate ONE phased chunk of files.

Runtime profile is fixed:
- Framework: Next.js full-stack (App Router)
- Hosting: Vercel

Rules:
1. Output only files for the requested phase.
2. Use complete, production-ready content.
3. Do not include secrets; use env vars and `.env.example`.
4. Keep imports consistent with already-generated files and file inventory.
5. Return only valid JSON with this shape:
{
  "files": [
    {"path": "relative/path/to/file.ext", "content": "full file contents", "language": "typescript"}
  ]
}
6. Every relative JS/TS import must resolve to a generated file path.
7. Use stable paths under `src/`, `app/`, `components/`, `lib/`, `api/`, `public/`.
8. Ensure Vercel deploy baseline exists across phases:
   - `package.json` with Next.js build scripts.
   - Next.js runtime entry files (`app/page.tsx` or `src/app/page.tsx`).
   - Optional `vercel.json` uses only `api/...` function patterns.
9. Dependency policy (MUST):
   - Only introduce libraries required by files in this chunk.
   - Avoid deprecated, unmaintained, or known-vulnerable packages.
10. Build reliability (MUST):
   - Do not add imports/plugins unless matching dependencies are declared in `package.json`.
   - Prevent module-not-found build failures (for example missing `autoprefixer`) by adding required
     deps when config references them, or by not emitting that config/plugin.
11. Avoid backend or API elements, Make the web app self-contained, and purely frontend, match the provide design/context as closely as possble, with reactive front-end elements and animations.
12. Use the provided design spec and context to generate the code.
13. Use dummy data to populate the app so that all elements render and are interactive.

Return ONLY JSON.
"""

_USER_PROMPT_FULL = """\
Generate the complete source code for the project based on the following artifacts.

## Design Specification
{design_spec_content}

## Design Visual Context (for fidelity)
{design_visual_context}

## PRD Summary
{prd_content}

Generate all files needed for a working Vercel-deployable Next.js full-stack project.
"""

_USER_PROMPT_WITH_FEEDBACK_FULL = """\
Generate revised source code. A previous version was rejected by the security
gate. Fix these security issues:
{feedback}

## Design Specification
{design_spec_content}

## Design Visual Context (for fidelity)
{design_visual_context}

## PRD Summary
{prd_content}

## Previous Code Snapshot
{previous_code}

Fix all findings without regressions. Return the complete updated file set.
"""

_USER_PROMPT_CHUNK = """\
Generate only the {chunk_label} files for this project.

Chunk-specific requirements:
{chunk_requirements}

## Design Specification
{design_spec_content}

## Design Visual Context (for fidelity)
{design_visual_context}

## PRD Summary
{prd_content}

## Files generated in previous chunks
{generated_files}

## Current file path inventory (authoritative)
{generated_file_index}
{security_feedback_block}
{previous_code_block}
Return only JSON with a `files` array for this phase.
"""

_CHUNK_REQUIREMENTS = {
    "backend": (
        "Implement server-side logic using Next.js route handlers under `app/api` or `src/app/api` "
        "and reusable server utilities under `lib/`."
    ),
    "frontend": (
        "Create Next.js pages/components from design screens. Keep UI structure, hierarchy, and naming "
        "consistent with provided design context."
    ),
    "config": (
        "Create project configuration/manifests needed for Vercel deploy: package.json scripts, "
        "Next.js config, tsconfig, env example placeholders, and optional vercel.json."
    ),
    "migrations": (
        "If a durable data model is explicitly required, add lightweight SQL/schema files under `db/migrations/` "
        "or `sql/`; otherwise return an empty files array for this phase."
    ),
}


def _serialize(artifact: Any) -> str:
    """Best-effort serialisation of an artifact dict to a prompt string."""
    if isinstance(artifact, dict):
        cleaned = {k: v for k, v in artifact.items() if not k.startswith("__")}
        return json.dumps(cleaned, indent=2)
    return str(artifact) if artifact else "(not provided)"


def _serialize_code_snapshot(artifact: Any) -> str:
    """Serialize a previous code snapshot for inclusion in feedback prompts."""
    if not isinstance(artifact, dict):
        return "(no previous code)"
    files = artifact.get("files", [])
    if not files:
        return "(no previous code)"
    parts = []
    for f in files[:30]:
        parts.append(
            f"### {f.get('path', '?')}\n```{f.get('language', '')}\n{f.get('content', '')}\n```"
        )
    return "\n\n".join(parts)


def _serialize_generated_files(files: list[dict[str, Any]] | None) -> str:
    """Serialize previously generated chunk files with conservative truncation."""
    if not files:
        return "(none yet)"

    parts: list[str] = []
    for file_data in files[:20]:
        path = file_data.get("path", "?")
        language = file_data.get("language", "")
        content = str(file_data.get("content", ""))
        if len(content) > 2000:
            content = content[:2000] + "\n# ...truncated for context..."
        parts.append(f"### {path}\n```{language}\n{content}\n```")
    return "\n\n".join(parts)


def _serialize_generated_file_index(files: list[dict[str, Any]] | None) -> str:
    """Serialize a compact list of generated paths for import/dependency planning."""
    if not files:
        return "(none yet)"

    paths = sorted(
        {
            str(file_data.get("path", "")).strip()
            for file_data in files
            if str(file_data.get("path", "")).strip()
        }
    )
    if not paths:
        return "(none yet)"

    max_paths = 400
    display = paths[:max_paths]
    lines = [f"- {path}" for path in display]
    if len(paths) > max_paths:
        lines.append(f"- ... ({len(paths) - max_paths} more paths omitted)")
    return "\n".join(lines)


def _serialize_design_codegen_context(design_spec: Any) -> str:
    """Serialize normalized design visual context with bounded payload size."""
    if not isinstance(design_spec, dict):
        return "(none)"

    context = (
        design_spec.get("design_codegen_context")
        or design_spec.get("metadata", {}).get("design_codegen_context")
    )
    if not isinstance(context, dict):
        return "(none)"

    screens = context.get("screens")
    if isinstance(screens, list):
        capped_screens = []
        for raw_screen in screens[:8]:
            if not isinstance(raw_screen, dict):
                continue
            screen = {
                "id": raw_screen.get("id"),
                "name": raw_screen.get("name"),
                "description": raw_screen.get("description"),
                "preview_images": (raw_screen.get("preview_images") or [])[:4],
                "assets": (raw_screen.get("assets") or [])[:6],
                "component_regions": (raw_screen.get("component_regions") or [])[:12],
            }
            capped_screens.append(screen)
        context = {**context, "screens": capped_screens}

    text = json.dumps(context, indent=2)
    max_chars = 14_000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...truncated..."
    return text


def build_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
    chunk: str = "full_snapshot",
    generated_files: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for code generation."""
    arts = previous_artifacts or {}
    design_spec = _serialize(arts.get("design_spec"))
    design_visual_context = _serialize_design_codegen_context(arts.get("design_spec"))
    prd = _serialize(arts.get("prd"))

    if chunk == "full_snapshot":
        if feedback:
            previous_code = _serialize_code_snapshot(arts.get("code_snapshot"))
            user_prompt = _USER_PROMPT_WITH_FEEDBACK_FULL.format(
                design_spec_content=design_spec,
                design_visual_context=design_visual_context,
                prd_content=prd,
                feedback=feedback,
                previous_code=previous_code,
            )
        else:
            user_prompt = _USER_PROMPT_FULL.format(
                design_spec_content=design_spec,
                design_visual_context=design_visual_context,
                prd_content=prd,
            )
        return _SYSTEM_PROMPT_FULL, user_prompt

    chunk_requirements = _CHUNK_REQUIREMENTS.get(chunk, _CHUNK_REQUIREMENTS["backend"])
    security_feedback_block = ""
    previous_code_block = ""
    if feedback:
        security_feedback_block = (
            f"\n## Security Remediation (MUST FIX)\nFix these security issues:\n{feedback}\n"
        )
        previous_code = _serialize_code_snapshot(arts.get("code_snapshot"))
        previous_code_block = f"\n## Previous Code Snapshot\n{previous_code}\n"

    user_prompt = _USER_PROMPT_CHUNK.format(
        chunk_label=chunk,
        chunk_requirements=chunk_requirements,
        design_spec_content=design_spec,
        design_visual_context=design_visual_context,
        prd_content=prd,
        generated_files=_serialize_generated_files(generated_files),
        generated_file_index=_serialize_generated_file_index(generated_files),
        security_feedback_block=security_feedback_block,
        previous_code_block=previous_code_block,
    )

    return _SYSTEM_PROMPT_CHUNK, user_prompt


def build_full_snapshot_prompts(
    *,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> tuple[str, str]:
    """Compatibility wrapper for existing tests/callers expecting full mode."""
    return build_prompts(
        previous_artifacts=previous_artifacts,
        feedback=feedback,
        chunk="full_snapshot",
    )


def build_chunk_prompts(
    *,
    chunk: str,
    previous_artifacts: dict[str, Any] | None = None,
    feedback: str | None = None,
    generated_files: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Convenience wrapper for phased generation prompts."""
    return build_prompts(
        previous_artifacts=previous_artifacts,
        feedback=feedback,
        chunk=chunk,
        generated_files=generated_files,
    )
