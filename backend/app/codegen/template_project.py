from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.schemas.code_snapshot import CodeFile

IGNORED_DIRS = {".git", "node_modules", ".next", ".turbo", "dist", "build"}
IGNORED_FILES = {".DS_Store", "Thumbs.db", "package-lock.json"}


class TemplateProjectConfigError(RuntimeError):
    """Raised when the configured template directory is unavailable."""


def infer_language(filename: str) -> str:
    """Infer the language identifier from file extension."""
    ext = filename.split(".")[-1].lower()
    mapping = {
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "json": "json",
        "md": "markdown",
        "css": "css",
        "html": "html",
        "mjs": "javascript",
        "cjs": "javascript",
    }
    return mapping.get(ext, "plaintext")


def resolve_template_dir(template_dir: str | Path | None = None) -> Path:
    """Return the absolute template directory and fail fast when it is unavailable."""
    if template_dir is None:
        resolved = settings.resolved_codegen_template_dir
    else:
        configured = Path(template_dir).expanduser()
        if configured.is_absolute():
            resolved = configured.resolve()
        else:
            resolved = (settings.repo_root / configured).resolve()

    if not resolved.is_dir():
        configured_value = template_dir if template_dir is not None else settings.codegen_template_dir
        raise TemplateProjectConfigError(
            "Codegen template directory does not exist or is not a directory: "
            f"{resolved} (configured as {configured_value!r})"
        )

    return resolved


def get_template_filepaths(template_dir: str) -> list[str]:
    """Get all valid file paths in the template, relative to template_dir."""
    root = resolve_template_dir(template_dir)
    paths: list[str] = []

    for p in root.rglob("*"):
        if p.is_file():
            # Check if any part of the path is in IGNORED_DIRS
            parts = p.relative_to(root).parts
            if any(part in IGNORED_DIRS for part in parts):
                continue
            if p.name in IGNORED_FILES:
                continue
            paths.append(str(p.relative_to(root)))

    # Always sort paths to ensure deterministic order
    return sorted(paths)


def load_template_tree(template_dir: str) -> list[CodeFile]:
    """Load the full template tree as CodeFile objects."""
    root = resolve_template_dir(template_dir)
    paths = get_template_filepaths(template_dir)
    files = []

    for rel_path in paths:
        path = root / rel_path
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # Skip binary files if any slipped through

        files.append(
            CodeFile(
                path=rel_path,
                content=content,
                language=infer_language(rel_path),
            )
        )

    return files


def merge_package_json(template_content: str, package_additions: dict[str, dict[str, str]]) -> str:
    """Merge AI package additions into the template package.json.

    Raises ValueError if the model attempts to override an existing version.
    """
    try:
        pkg = json.loads(template_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Template package.json is invalid JSON: {e}")

    for section in ["dependencies", "devDependencies"]:
        if section not in package_additions:
            continue

        if section not in pkg:
            pkg[section] = {}

        for name, version in package_additions[section].items():
            if name in pkg[section] and pkg[section][name] != version:
                raise ValueError(
                    f"Blocked modification of existing template package: {name} "
                    f"(template: {pkg[section][name]}, requested: {version})"
                )
            pkg[section][name] = version

    return json.dumps(pkg, indent=2) + "\n"


def merge_project(
    template_dir: str, ai_files: list[CodeFile], package_additions: dict[str, dict[str, str]]
) -> list[CodeFile]:
    """Merge AI-generated files and package additions into the template tree.

    Returns the fully merged list of CodeFiles, sorted by path.
    """
    template_files = load_template_tree(template_dir)
    merged_map = {f.path: f for f in template_files}

    # Process AI file deltas (new or override)
    for ai_file in ai_files:
        merged_map[ai_file.path] = ai_file

    # Merge package.json
    if "package.json" in merged_map:
        template_pkg = merged_map["package.json"].content
        merged_pkg_content = merge_package_json(template_pkg, package_additions)
        merged_map["package.json"].content = merged_pkg_content

    # Sort and return
    return sorted(list(merged_map.values()), key=lambda x: x.path)
