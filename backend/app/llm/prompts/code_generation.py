"""Prompt templates for phased code generation."""

from __future__ import annotations

import json
from typing import Any

_SYSTEM_PROMPT_FULL = """\
You are an expert frontend engineer. Generate a visually polished, self-contained Next.js prototype.

Stack (fixed):
- Next.js 14+ App Router, TypeScript, Tailwind CSS
- Hosting: Vercel (static export compatible)
- Backend: NONE. Zero API routes, zero server actions, zero database.

Core requirements:
1. **Purely visual frontend.** All data is hardcoded in typed
   `src/data/*.ts` files. No fetch(), no API calls, no server
   components that fetch data.
2. **Every page is routable.** Use Next.js App Router file-based
   routing. Each design screen = one `page.tsx`. Include persistent
   navigation (sidebar or topnav) linking all routes.
3. **Rich dummy data.** Realistic, diverse mock data (names, dates,
   amounts, statuses, avatars via ui-avatars.com URLs). 5-15 items
   per entity. Typed with TypeScript interfaces in `src/types/`.
4. **Interactive UI.** Client-side state for: filters, search,
   sorting, tab switching, modals, form inputs, toggles, accordions.
   Use `useState`/`useReducer`. In-memory only, no persistence.
5. **Visually polished.** Consistent color palette, typography scale,
   spacing, rounded corners, shadows, hover/focus states. Tailwind
   CSS utilities. Subtle animations via CSS transitions or
   framer-motion.
6. **Responsive.** Mobile-first breakpoints. Sidebar collapses on
   small screens.
7. **Deploy-ready.** Must `npm run build` on Vercel with zero config.
   Every import resolves. Every dependency in `package.json`.

Dependency rules:
- MUST include: next, react, react-dom, typescript, tailwindcss, @tailwindcss/postcss, lucide-react.
- RECOMMENDED: framer-motion (animations), clsx or tailwind-merge (conditional classes).
- NEVER include: any database driver, ORM, auth library, API framework, or server-only package.
- Every imported package must be in `package.json` with compatible versions.

File structure:
- `src/app/layout.tsx` — root layout with navigation, font import, global styles
- `src/app/page.tsx` — home/landing page
- `src/app/[route]/page.tsx` — one per screen
- `src/components/` — reusable UI components
- `src/data/` — hardcoded mock data (typed exports)
- `src/types/` — TypeScript interfaces
- `src/lib/` — utils (cn helper, formatters)

Output format — return a single valid JSON object:
{
  "files": [
    {"path": "relative/path", "content": "full contents", "language": "typescript"}
  ],
  "build_command": "npm run build",
  "test_command": "npx tsc --noEmit",
  "entry_point": "src/app/page.tsx"
}

Return ONLY JSON. No markdown fences, no commentary.
"""

_SYSTEM_PROMPT_CHUNK = """\
You are an expert frontend engineer. Generate ONE phased chunk of files for a self-contained Next.js prototype.

Stack: Next.js 14+ App Router, TypeScript, Tailwind CSS. Hosting: Vercel. Backend: NONE.

Rules:
1. Output only files for the requested phase. Complete, production-ready content.
2. No secrets, no env vars needed (no backend). No API routes, no server actions.
3. Keep imports consistent with already-generated files and file inventory.
4. Return valid JSON: {"files": [{"path": "string", "content": "string", "language": "string"}]}
5. Every import must resolve to a generated file path or a declared package.
6. Paths under `src/` only: `src/app/`, `src/components/`, `src/data/`, `src/lib/`, `src/types/`.
7. Build reliability: every imported package must be in `package.json` with compatible versions.
8. All data is hardcoded in `src/data/` files. Realistic dummy data with TypeScript types.
9. All UI must be interactive (client-side state), visually polished (Tailwind), and routable (App Router).
10. Include animations/transitions. Use hover/focus states. Responsive layout.
11. Match the design spec closely: colors, layout, typography, component hierarchy.

Return ONLY JSON.
"""

_USER_PROMPT_FULL = """\
Generate all files for a complete, Vercel-deployable Next.js frontend prototype.

## Design Specification
{design_spec_content}

## Visual Context
{design_visual_context}

## PRD
{prd_content}

Match the design closely. Every screen routable. All elements
interactive with dummy data. No backend code.
"""

_USER_PROMPT_WITH_FEEDBACK_FULL = """\
Revise the code. Previous version was rejected. Fix these issues:
{feedback}

## Design Specification
{design_spec_content}

## Visual Context
{design_visual_context}

## PRD
{prd_content}

## Previous Code
{previous_code}

Fix all findings. Keep all interactive elements and dummy data. Return the complete updated file set.
"""

_USER_PROMPT_CHUNK = """\
Generate the **{chunk_label}** phase files.

Phase requirements:
{chunk_requirements}

## Design Spec
{design_spec_content}

## Visual Context
{design_visual_context}

## PRD
{prd_content}

## Already generated files
{generated_files}

## File inventory
{generated_file_index}
{security_feedback_block}
{previous_code_block}
Return only JSON with a `files` array. No backend code. All UI interactive with dummy data.
"""

_CHUNK_REQUIREMENTS = {
    "backend": (
        "Generate TypeScript interfaces in `src/types/` and hardcoded dummy data files in `src/data/`. "
        "Include realistic mock data (5-15 items per entity) with proper types. "
        "Add utility helpers in `src/lib/` (cn helper, date formatters, currency formatters). "
        "NO API routes, NO server logic, NO database — data layer is purely static typed arrays."
    ),
    "frontend": (
        "Create Next.js App Router pages and React components matching the design spec. "
        "Each screen = one `page.tsx` under `src/app/`. Include persistent navigation (sidebar/topnav). "
        "All components are interactive: filters, search, sort, modals, tabs, toggles via useState. "
        "Use Tailwind CSS for styling. Add animations (fade-in, slide, hover states). "
        "Import dummy data from `src/data/`. Responsive, mobile-first layout."
    ),
    "config": (
        "Create project config for Vercel deploy: package.json (with all dependencies + build scripts), "
        "next.config.ts, tsconfig.json, tailwind.config.ts, postcss.config.mjs, "
        "src/app/globals.css (Tailwind directives + custom properties), src/app/layout.tsx (root layout with "
        "font imports and navigation shell). No .env needed — no backend."
    ),
    "migrations": ("Return an empty files array. This is a frontend-only prototype with no database."),
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


def _serialize_generated_file_index(files: list[dict[str, Any]] | None) -> str:
    """Serialize a compact list of generated paths for import/dependency planning."""
    if not files:
        return "(none yet)"

    paths = sorted(
        {str(file_data.get("path", "")).strip() for file_data in files if str(file_data.get("path", "")).strip()}
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
        security_feedback_block = f"\n## Security Remediation (MUST FIX)\nFix these security issues:\n{feedback}\n"
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
