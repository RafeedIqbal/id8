"""Prompt templates for phased code generation."""

from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT_FULL = """\
You are an elite Staff Frontend Engineer. Your objective is to generate a visually polished,
flawless, and completely self-contained Next.js prototype.

The output MUST compile successfully on Vercel with zero modifications, zero build-time errors,
and zero runtime errors.

STACK (Strictly Enforced):
- Next.js 16+ App Router, React 19+, TypeScript, Tailwind CSS v4
- Hosting: Vercel (static export compatible)
- Backend: NONE. Zero API routes, zero server actions, zero database.

CORE MANDATES:
1. **Flawless Execution & Vercel Deployability:** The code MUST pass `next build`, `tsc --noEmit`, and `npm run lint`.
   - For Next.js 16+, use `proxy.ts` (not `middleware.ts`) and export `proxy`.
   - For React 19, `startTransition` callbacks must return `void` (wrap async actions as `async () => { await ... }`).
   - Add `'use client'` at the top of files using React hooks (`useState`, `useEffect`, `useRef`).
   - Prevent hydration errors: Do not render browser-specific globals (`window`, `document`) directly
      in the component body without `useEffect` or dynamic imports.
   - All imports MUST resolve perfectly. Do not import phantom packages.
2. **Strict TypeScript:** No `any` types. Define comprehensive interfaces for all data structures in `types/`.
3. **Purely Visual Frontend:** All data must be hardcoded in typed `data/*.ts` files. Use realistic,
   rich mock data (5-15 items per entity, populated with ui-avatars.com URLs, realistic dates, etc.).
   NO `fetch()`, NO backend logic.
4. **Interactive UI:** Client-side state must be fully implemented for filters, search, sorting, tabs,
   modals, and toggles using React hooks. State is in-memory only.
5. **Routable Architecture:** Utilize Next.js App Router file-based routing. Every distinct screen
   must have a dedicated `page.tsx`. Include a persistent layout (sidebar or topnav) linking all routes.
6. **Visual Polish & Responsiveness:** Use Tailwind CSS utilities for a cohesive design system (typography
   scales, consistent spacing, rounded corners, subtle shadows, hover/focus/active states).
   Ensure strictly mobile-first, responsive layouts.

DEPENDENCY RULES:
- If you need a new dependency, declare it in `package_changes`.
- DO NOT EVER output a replacement `package.json` file. Template packages win on conflicts.
- Every imported package MUST be explicitly defined in `package_changes` if not in template `package.json`.
- Choose dependency versions that are installable together with the template's
  Next.js/React stack. If a package has React or Next peer dependencies,
  they must explicitly support React 19 / Next 16.

OUTPUT FORMAT:
Return a single, purely valid JSON object.
DO NOT wrap the response in Markdown formatting blocks (e.g., no ```json).
DO NOT include any conversational text or commentary.
The JSON must perfectly match this schema:
{
  "files": [
    {"path": "relative/path/to/file.ts", "content": "raw file contents", "language": "typescript"}
  ],
  "package_changes": {
    "dependencies": {},
    "devDependencies": {}
  }
}
"""

_SYSTEM_PROMPT_CHUNK = """\
You are an elite Staff Frontend Engineer generating ONE phased chunk of a Next.js prototype
built on top of an existing template project.

STACK: Next.js 16+ App Router, React 19+, TypeScript, Tailwind CSS v4. Hosting: Vercel. Backend: NONE.

STRICT RULES:
1. Output ONLY the files required for the requested phase, or overrides to allowed template files
   (app/page.tsx, app/layout.tsx, app/globals.css). Content must be complete and production-ready.
2. Ensure flawless integration with the provided template context. Do NOT redefine standard
   configurations (like next.config.ts); they are managed by the template.
3. Zero Errors: Code MUST pass `tsc --noEmit` and `npm run lint`. Use strict TypeScript
   (no `any`). Use `'use client'` where hooks are required. Prevent hydration mismatches.
4. Package Additions: If you need a new dependency, declare it in `package_changes`.
   DO NOT EVER output a replacement `package.json` file. Template packages win on conflicts.
   Any package with React/Next peer dependencies must explicitly support the template stack (React 19 / Next 16).
5. Static Data Only: All data comes from typed `data/` files. No backend APIs,
   no server components fetching external data, no secrets.
6. Polish & Interactivity: UI must be highly interactive (client-side state), fully
   responsive (mobile-first Tailwind), and visually refined (hover states, transitions).
7. Match the provided design specifications with high fidelity.

OUTPUT FORMAT:
Return ONLY a valid, unescaped JSON object. NO markdown fences (```json). NO commentary.
Schema:
{
  "files": [{"path": "string", "content": "string", "language": "string"}],
  "package_changes": {
    "dependencies": {},
    "devDependencies": {}
  }
}
"""

_USER_PROMPT_FULL = """\
Generate all files for a complete, Vercel-deployable Next.js frontend prototype.

## Design Specification
{design_spec_content}

## Visual Context
{design_visual_context}

## PRD
{prd_content}

CRITICAL EXECUTION STEPS:
1. Thoroughly analyze the Design Spec and PRD.
2. Mentally verify all imports, component props, and state logic to prevent runtime/build errors.
3. Ensure all screens are routable and visually match the spec.
4. Output the complete, interactive prototype as strictly structured JSON.
"""

_USER_PROMPT_WITH_FEEDBACK_FULL = """\
Revise the previously generated code. The previous version failed validation or requires updates.

## Critical Issues to Fix
{feedback}

## Design Specification
{design_spec_content}

## Visual Context
{design_visual_context}

## PRD
{prd_content}

## Previous Code
{previous_code}

CRITICAL EXECUTION STEPS:
1. Address EVERY finding listed in the feedback.
2. Ensure the resulting code remains a fully interactive, statically-driven frontend with no backend dependencies.
3. Double-check for missing imports, syntax errors, or linting failures.
4. Return the complete updated file set as strictly structured JSON.
"""

_USER_PROMPT_CHUNK = """\
Generate the **{chunk_label}** phase files.

Phase Requirements:
{chunk_requirements}

## Design Spec
{design_spec_content}

## Visual Context
{design_visual_context}

## PRD
{prd_content}

## Template Context
{template_context}

## Already Generated Files (Context Only)
{generated_files}
{security_feedback_block}
{previous_code_block}

CRITICAL EXECUTION STEPS:
1. Generate ONLY the files and package additions for the **{chunk_label}** phase.
2. Ensure all exports align with the template inventory and generated files.
3. Verify that there are no TS errors, linting warnings, or missing dependencies.
4. Return ONLY valid JSON matching the exact schema. No markdown, no backend code.
"""

_CHUNK_REQUIREMENTS = {
    "shared_foundation": (
        "Generate strict TypeScript interfaces in `types/`, hardcoded dummy data arrays in `data/`, "
        "reusable UI components in `components/`, and generic utility helpers in `lib/`. "
        "Also include any overrides to the template shell (e.g. `app/layout.tsx`, `app/globals.css`). "
        "Include realistic mock data (5-15 items per entity). Output package additions for components used. "
        "ABSOLUTELY NO API routes, server actions, or database logic."
    ),
    "pages": (
        "Generate all application pages/routes including the root `app/page.tsx` and any required sub-routes. "
        "Create Next.js App Router pages meticulously matching the design spec. "
        "Include `'use client'` directives on interactive components if they hold state. "
        "Ensure all filters, search, sort, modals, and tabs work purely via local state. "
        "Import and utilize the dummy data from `data/` and components from `components/`. "
        "Output package additions if distinct page-specific libraries are needed."
    ),
    "repair": (
        "Review the previous code and security feedback. Output ONLY the files that must be corrected to fix "
        "the reported issues. Ensure you do NOT break existing working code."
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
        parts.append(f"### {f.get('path', '?')}\n```{f.get('language', '')}\n{f.get('content', '')}\n```")
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


def _serialize_template_context(template_context: dict[str, Any] | None) -> str:
    """Serialize the template context including file inventory and key file contents."""
    if not template_context:
        return "(no template context provided)"

    inventory = template_context.get("inventory", [])
    files = template_context.get("files", {})

    parts = ["### Template Inventory"]
    parts.extend([f"- {path}" for path in inventory])

    parts.append("\n### Template Key Files")
    for path in sorted(files):
        content = files[path]
        parts.append(f"#### {path}\n```\n{content}\n```\n")

    return "\n".join(parts)


def _serialize_design_codegen_context(design_spec: Any) -> str:
    """Serialize normalized design visual context with bounded payload size."""
    if not isinstance(design_spec, dict):
        return "(none)"

    context = design_spec.get("design_codegen_context") or design_spec.get("metadata", {}).get("design_codegen_context")
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
    template_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for code generation."""
    arts = previous_artifacts or {}
    design_spec = _serialize(arts.get("design_spec"))
    design_visual_context = _serialize_design_codegen_context(arts.get("design_spec"))
    prd = _serialize(arts.get("prd"))
    serialized_template_context = _serialize_template_context(template_context)

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

    chunk_requirements = _CHUNK_REQUIREMENTS.get(chunk, _CHUNK_REQUIREMENTS["shared_foundation"])
    security_feedback_block = ""
    previous_code_block = ""
    if feedback:
        security_feedback_block = f"\n## Feedback (MUST FIX)\nFix these issues:\n{feedback}\n"
        previous_code = _serialize_code_snapshot(arts.get("code_snapshot"))
        previous_code_block = f"\n## Previous Code Snapshot\n{previous_code}\n"

    user_prompt = _USER_PROMPT_CHUNK.format(
        chunk_label=chunk,
        chunk_requirements=chunk_requirements,
        design_spec_content=design_spec,
        design_visual_context=design_visual_context,
        prd_content=prd,
        template_context=serialized_template_context,
        generated_files=_serialize_generated_files(generated_files),
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
    template_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Convenience wrapper for phased generation prompts."""
    return build_prompts(
        previous_artifacts=previous_artifacts,
        feedback=feedback,
        chunk=chunk,
        generated_files=generated_files,
        template_context=template_context,
    )
