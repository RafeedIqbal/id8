"""Stitch MCP design provider (primary).

Communicates with the Stitch MCP endpoint to generate and iterate on
UI designs. Handles authentication, tool discovery, and error mapping.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

from .base import (
    DesignFeedback,
    DesignOutput,
    DesignProvider,
    Screen,
    ScreenComponent,
    StitchAuthContext,
    StitchAuthError,
    StitchRuntimeError,
)

logger = logging.getLogger("id8.design.stitch_mcp")

_DEFAULT_ENDPOINT = "https://stitch.googleapis.com/mcp"
_REQUEST_TIMEOUT = 120  # seconds
_DEFAULT_STITCH_MODEL_ID = "GEMINI_3_FLASH"
_DEFAULT_DEVICE_TYPE = "DESKTOP"

# ---------------------------------------------------------------------------
# Canonical Stitch MCP tool inventory
# ---------------------------------------------------------------------------

STITCH_TOOLS: list[dict[str, Any]] = [
    {"name": "create_project", "params": ["title"], "description": "Create a new Stitch project"},
    {"name": "get_project", "params": ["name"], "description": "Get a Stitch project by resource name"},
    {"name": "delete_project", "params": ["name"], "description": "Delete a Stitch project"},
    {"name": "list_projects", "params": ["filter"], "description": "List Stitch projects"},
    {"name": "list_screens", "params": ["projectId"], "description": "List screens in a project"},
    {
        "name": "get_screen",
        "params": ["name", "projectId", "screenId"],
        "description": "Get a specific screen in a project",
    },
    {
        "name": "generate_screen_from_text",
        "params": ["projectId", "prompt", "deviceType", "modelId"],
        "description": "Generate a screen from a text prompt",
    },
    {
        "name": "upload_screens_from_images",
        "params": ["projectId", "images"],
        "description": "Upload images as project screens",
    },
    {
        "name": "edit_screens",
        "params": ["projectId", "selectedScreenIds", "prompt", "deviceType", "modelId"],
        "description": "Edit one or more existing screens",
    },
    {
        "name": "generate_variants",
        "params": ["projectId", "selectedScreenIds", "prompt", "variantOptions", "deviceType", "modelId"],
        "description": "Generate variants for existing screens",
    },
    {
        "name": "create_design_system",
        "params": ["designSystem", "projectId"],
        "description": "Create a design system",
    },
    {"name": "update_design_system", "params": ["designSystem"], "description": "Update a design system"},
    {"name": "list_design_systems", "params": ["projectId"], "description": "List design systems"},
    {
        "name": "apply_design_system",
        "params": ["projectId", "selectedScreenIds", "assetId"],
        "description": "Apply a design system to screens",
    },
]


def _endpoint() -> str:
    return settings.stitch_mcp_endpoint or _DEFAULT_ENDPOINT


# ---------------------------------------------------------------------------
# Provider implementation
# ---------------------------------------------------------------------------


class StitchMcpProvider(DesignProvider):
    """Design provider backed by the Stitch MCP remote endpoint."""

    async def generate(
        self,
        prd_content: dict[str, Any],
        constraints: dict[str, Any],
        auth: StitchAuthContext | None = None,
    ) -> DesignOutput:
        self._validate_auth(auth)
        assert auth is not None  # ensured by _validate_auth

        prompt = _build_generation_prompt(prd_content, constraints)
        project_id = await self._ensure_project_id(
            auth=auth,
            suggested_name=_project_name_from_prd(prd_content),
        )
        model_id = _resolve_model_id(constraints)
        device_type = _resolve_device_type(constraints)

        start = time.monotonic()
        raw = await self._call_stitch(
            tool="generate_screen_from_text",
            params={
                "projectId": project_id,
                "prompt": prompt,
                "modelId": model_id,
                "deviceType": device_type,
            },
            auth=auth,
        )
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        output = _parse_stitch_response(raw)
        output.metadata.update({
            "provider": "stitch_mcp",
            "endpoint": _endpoint(),
            "generation_time_ms": elapsed_ms,
            "usable_tools": STITCH_TOOLS,
            "stitch_project_id": project_id,
            "stitch_project_url": _project_url(project_id),
            "stitch_model_id": model_id,
            "stitch_device_type": device_type,
            **auth.redacted_summary(),
        })
        return output

    async def regenerate(
        self,
        previous: DesignOutput,
        feedback: DesignFeedback,
        auth: StitchAuthContext | None = None,
    ) -> DesignOutput:
        self._validate_auth(auth)
        assert auth is not None

        prompt = _build_regeneration_prompt(previous, feedback)

        existing_project_id = str(previous.metadata.get("stitch_project_id", "")).strip()
        project_id = await self._ensure_project_id(
            auth=auth,
            suggested_name="id8-design",
            existing_project_id=existing_project_id or None,
        )
        selected_screen_ids = _selected_screen_ids(previous, feedback.target_screen_id)
        model_id = _resolve_model_id(previous.metadata)
        device_type = _resolve_device_type(previous.metadata)
        tool = "edit_screens" if selected_screen_ids else "generate_screen_from_text"
        params: dict[str, Any] = {
            "projectId": project_id,
            "prompt": prompt,
            "modelId": model_id,
            "deviceType": device_type,
        }
        if selected_screen_ids:
            params["selectedScreenIds"] = selected_screen_ids

        start = time.monotonic()
        raw = await self._call_stitch(
            tool=tool,
            params=params,
            auth=auth,
        )
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        output = _parse_stitch_response(raw)
        output.metadata.update({
            "provider": "stitch_mcp",
            "endpoint": _endpoint(),
            "generation_time_ms": elapsed_ms,
            "feedback_text": feedback.feedback_text,
            "usable_tools": STITCH_TOOLS,
            "stitch_project_id": project_id,
            "stitch_project_url": _project_url(project_id),
            "stitch_model_id": model_id,
            "stitch_device_type": device_type,
            "stitch_edit_tool": tool,
            "selected_screen_ids": selected_screen_ids,
            **auth.redacted_summary(),
        })
        return output

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _validate_auth(auth: StitchAuthContext | None) -> None:
        if auth is None:
            raise StitchAuthError("Stitch MCP credentials not provided")
        if auth.auth_method.value == "api_key":
            if not auth.api_key.strip():
                raise StitchAuthError("Stitch MCP API key is missing")
            return
        if not auth.oauth_token.strip() or not auth.goog_user_project.strip():
            raise StitchAuthError(
                "Stitch OAuth requires both oauth_access_token and X-Goog-User-Project"
            )

    async def _call_stitch(
        self,
        *,
        tool: str,
        params: dict[str, Any],
        auth: StitchAuthContext,
    ) -> dict[str, Any]:
        """Send an MCP tool call to the Stitch endpoint."""
        endpoint = _endpoint()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **auth.build_headers(),
        }
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": params},
            "id": 1,
        }

        logger.info(
            "AUDIT stitch_mcp_call tool=%s endpoint=%s auth_method=%s",
            tool,
            endpoint,
            auth.auth_method.value,
        )

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise StitchRuntimeError(f"Stitch MCP request timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise StitchRuntimeError(f"Stitch MCP connection failed: {exc}") from exc

        if resp.status_code == 401:
            raise StitchAuthError("Stitch returned 401 — credentials are invalid")
        if resp.status_code == 403:
            raise StitchAuthError("Stitch returned 403 — access denied")
        if resp.status_code == 429:
            raise StitchRuntimeError("Stitch rate limit exceeded (429)")
        if resp.status_code == 503:
            raise StitchRuntimeError("Stitch service unavailable (503)")
        if resp.status_code >= 400:
            raise StitchRuntimeError(
                f"Stitch MCP error: HTTP {resp.status_code} — {resp.text[:500]}"
            )

        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise StitchRuntimeError(f"Invalid JSON from Stitch: {exc}") from exc

        if "error" in body:
            err = body["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise StitchRuntimeError(f"Stitch MCP error: {msg}")

        result = body.get("result", body)
        if not isinstance(result, dict):
            raise StitchRuntimeError("Unexpected Stitch response shape")
        if result.get("isError") is True:
            raise StitchRuntimeError(f"Stitch MCP error: {_extract_error_text(result)}")
        return result

    async def _ensure_project_id(
        self,
        *,
        auth: StitchAuthContext,
        suggested_name: str,
        existing_project_id: str | None = None,
    ) -> str:
        """Return a valid Stitch project_id, creating one when needed."""
        if existing_project_id:
            normalized = _normalize_project_id(existing_project_id)
            if normalized:
                return normalized

        try:
            listed = await self._call_stitch(
                tool="list_projects",
                params={},
                auth=auth,
            )
            existing_id = _find_project_id_by_title(listed, suggested_name)
            if existing_id:
                return existing_id
        except StitchRuntimeError:
            # If listing fails, fall through to project creation.
            pass

        created = await self._call_stitch(
            tool="create_project",
            params={"title": suggested_name},
            auth=auth,
        )
        created_id = _extract_project_id(created)
        if not created_id:
            raise StitchRuntimeError("Stitch create_project did not return project_id")
        return created_id


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_generation_prompt(prd_content: dict[str, Any], constraints: dict[str, Any]) -> str:
    """Translate an approved PRD into a Stitch-compatible generation prompt."""
    parts = ["Generate UI screens for the following product:\n"]

    summary = prd_content.get("executive_summary", "")
    if summary:
        parts.append(f"Product Summary: {summary}\n")

    stories = prd_content.get("user_stories", [])
    if stories:
        parts.append("Key User Stories:")
        for s in stories[:5]:
            persona = s.get("persona", "user")
            action = s.get("action", "")
            parts.append(f"- As a {persona}, I want to {action}")
        parts.append("")

    entities = prd_content.get("entity_list", [])
    if entities:
        parts.append("Domain Entities: " + ", ".join(e.get("name", "") for e in entities))
        parts.append("")

    if constraints:
        parts.append(f"Design Constraints: {json.dumps(constraints)}")

    return "\n".join(parts)


def _build_regeneration_prompt(previous: DesignOutput, feedback: DesignFeedback) -> str:
    """Build a targeted regeneration prompt incorporating feedback."""
    parts = ["Regenerate the design with the following feedback:\n"]
    parts.append(f"Feedback: {feedback.feedback_text}\n")

    if feedback.target_screen_id:
        parts.append(f"Target Screen ID: {feedback.target_screen_id}")
    if feedback.target_component_id:
        parts.append(f"Target Component ID: {feedback.target_component_id}")

    parts.append("\nPrevious design context:")
    for screen in previous.screens[:10]:
        parts.append(f"- Screen '{screen.name}' ({screen.id}): {screen.description}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _project_name_from_prd(prd_content: dict[str, Any]) -> str:
    summary = str(prd_content.get("executive_summary", "")).strip()
    if summary:
        return summary[:80]
    title = str(prd_content.get("title", "")).strip()
    if title:
        return title[:80]
    return "id8-design"


def _extract_project_id(raw: dict[str, Any]) -> str:
    return _extract_project_id_shallow(raw)


def _extract_project_id_shallow(raw: dict[str, Any]) -> str:
    project = raw.get("project")
    data = raw.get("data")
    candidates: list[Any] = [
        raw.get("projectId"),
        raw.get("project_id"),
        raw.get("id"),
        project.get("projectId") if isinstance(project, dict) else None,
        project.get("project_id") if isinstance(project, dict) else None,
        project.get("id") if isinstance(project, dict) else None,
        data.get("projectId") if isinstance(data, dict) else None,
        data.get("project_id") if isinstance(data, dict) else None,
        data.get("id") if isinstance(data, dict) else None,
    ]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = _normalize_project_id(candidate)
        if normalized:
            return normalized

    resource_candidates: list[Any] = [
        raw.get("name"),
        project.get("name") if isinstance(project, dict) else None,
        data.get("name") if isinstance(data, dict) else None,
    ]
    for candidate in resource_candidates:
        if not isinstance(candidate, str):
            continue
        normalized = _normalize_project_resource_name(candidate)
        if normalized:
            return normalized

    return ""


def _extract_error_text(raw: dict[str, Any]) -> str:
    content = raw.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return "Unknown Stitch error"


def _parse_stitch_response(raw: dict[str, Any]) -> DesignOutput:
    """Parse a Stitch MCP response into a ``DesignOutput``."""
    screens = _extract_screens(raw)
    suggestions = _extract_suggestions(raw)
    metadata: dict[str, Any] = {}
    if suggestions:
        metadata["stitch_suggestions"] = suggestions
    return DesignOutput(screens=screens, metadata=metadata)


def _normalize_project_id(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("projects/"):
        return value.split("/", 1)[1].strip()
    return value


def _normalize_project_resource_name(raw: str) -> str:
    value = raw.strip()
    if not value.startswith("projects/"):
        return ""
    return value.split("/", 1)[1].strip()


def _normalize_screen_id(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if "/screens/" in value:
        return value.rsplit("/screens/", 1)[1].strip()
    if value.startswith("screens/"):
        return value.split("/", 1)[1].strip()
    return value


def _project_url(project_id: str) -> str:
    return f"https://stitch.withgoogle.com/project/{project_id}"


def _resolve_model_id(constraints: dict[str, Any]) -> str:
    model_id = str(
        constraints.get("modelId")
        or constraints.get("model_id")
        or constraints.get("stitch_model_id")
        or _DEFAULT_STITCH_MODEL_ID
    ).strip()
    return model_id or _DEFAULT_STITCH_MODEL_ID


def _resolve_device_type(constraints: dict[str, Any]) -> str:
    device_type = str(
        constraints.get("deviceType")
        or constraints.get("device_type")
        or constraints.get("stitch_device_type")
        or _DEFAULT_DEVICE_TYPE
    ).strip()
    return device_type or _DEFAULT_DEVICE_TYPE


def _selected_screen_ids(previous: DesignOutput, target_screen_id: str | None) -> list[str]:
    if target_screen_id:
        normalized = _normalize_screen_id(target_screen_id)
        if normalized:
            return [normalized]

    selected: list[str] = []
    seen: set[str] = set()
    for screen in previous.screens:
        normalized = _normalize_screen_id(screen.id)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(normalized)
    return selected


def _find_project_id_by_title(raw: dict[str, Any], title: str) -> str:
    wanted = title.strip().casefold()
    if not wanted:
        return ""

    for project in _extract_projects(raw):
        project_title = _extract_project_title(project)
        if project_title and project_title.strip().casefold() == wanted:
            project_id = _extract_project_id(project)
            if project_id:
                return project_id
    return ""


def _extract_project_title(raw: dict[str, Any]) -> str:
    project = raw.get("project")
    data = raw.get("data")
    candidates: list[Any] = [
        raw.get("title"),
        raw.get("displayName"),
        project.get("title") if isinstance(project, dict) else None,
        project.get("displayName") if isinstance(project, dict) else None,
        data.get("title") if isinstance(data, dict) else None,
        data.get("displayName") if isinstance(data, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _extract_projects(raw: dict[str, Any]) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add_project(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        marker = id(candidate)
        if marker in seen:
            return
        seen.add(marker)
        projects.append(candidate)

    def from_value(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                from_value(item)
            return
        if not isinstance(value, dict):
            return

        if _extract_project_id_shallow(value):
            add_project(value)

        for key in ("projects", "data", "structuredContent", "project"):
            child = value.get(key)
            if isinstance(child, (dict, list)):
                from_value(child)

        content = value.get("content")
        if isinstance(content, dict):
            from_value(content)
        elif isinstance(content, list):
            from_value(content)
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    continue
                from_value(parsed)

    from_value(raw)
    return projects


def _extract_screens(raw: dict[str, Any]) -> list[Screen]:
    raw_screens = _extract_raw_screen_objects(raw)
    screens: list[Screen] = []

    for i, raw_screen in enumerate(raw_screens):
        screen = _screen_from_raw(raw_screen, i)
        if screen is not None:
            screens.append(screen)

    return screens


def _extract_raw_screen_objects(raw: dict[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add(candidate: dict[str, Any]) -> None:
        marker = id(candidate)
        if marker in seen:
            return
        seen.add(marker)
        collected.append(candidate)

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return

        if not isinstance(node, dict):
            return

        if _looks_like_screen(node):
            add(node)

        for key in (
            "screens",
            "screen",
            "updatedScreens",
            "generatedScreens",
            "variants",
            "data",
            "structuredContent",
            "design",
            "output_components",
            "outputComponents",
            "content",
        ):
            child = node.get(key)
            if isinstance(child, (dict, list)):
                visit(child)

        text = node.get("text")
        if isinstance(text, str) and text.strip() and "{" in text:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return
            visit(parsed)

    visit(raw)
    return collected


def _looks_like_screen(candidate: dict[str, Any]) -> bool:
    name = candidate.get("name")
    if isinstance(name, str) and "/screens/" in name:
        return True

    if any(key in candidate for key in ("screenshot", "htmlCode", "figmaExport", "screenMetadata")):
        return True

    if isinstance(candidate.get("id"), str) and (
        isinstance(candidate.get("components"), list)
        or any(
            key in candidate
            for key in ("assets", "prompt", "deviceType", "screenType", "width", "height")
        )
    ):
        return True

    return False


def _screen_from_raw(raw_screen: dict[str, Any], index: int) -> Screen | None:
    raw_id_candidates = [
        raw_screen.get("id"),
        raw_screen.get("screenId"),
        raw_screen.get("screen_id"),
        raw_screen.get("name"),
    ]

    screen_id = ""
    for candidate in raw_id_candidates:
        if not isinstance(candidate, str):
            continue
        normalized = _normalize_screen_id(candidate)
        if normalized:
            screen_id = normalized
            break

    if not screen_id:
        screen_id = f"screen-{index + 1}"

    raw_name = raw_screen.get("title") or raw_screen.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) else ""
    if "/screens/" in name:
        name = ""
    if not name:
        name = f"Screen {index + 1}"

    description = ""
    if isinstance(raw_screen.get("description"), str):
        description = str(raw_screen["description"]).strip()
    elif isinstance(raw_screen.get("prompt"), str):
        description = str(raw_screen["prompt"]).strip()
    else:
        screen_metadata = raw_screen.get("screenMetadata")
        if isinstance(screen_metadata, dict):
            status_message = screen_metadata.get("statusMessage")
            if isinstance(status_message, str):
                description = status_message.strip()

    components = _extract_components(raw_screen)
    assets = _extract_assets(raw_screen)
    return Screen(
        id=screen_id,
        name=name,
        description=description,
        components=components,
        assets=assets,
    )


def _extract_components(raw_screen: dict[str, Any]) -> list[ScreenComponent]:
    components: list[ScreenComponent] = []

    raw_components = raw_screen.get("components")
    if isinstance(raw_components, list):
        for idx, raw_component in enumerate(raw_components):
            if not isinstance(raw_component, dict):
                continue
            components.append(
                ScreenComponent(
                    id=str(raw_component.get("id", f"comp-{idx + 1}")),
                    name=str(raw_component.get("name", f"Component {idx + 1}")),
                    type=str(raw_component.get("type", "unknown")),
                    properties=_as_string_key_dict(raw_component.get("properties")),
                )
            )
        return components

    screen_metadata = raw_screen.get("screenMetadata")
    if not isinstance(screen_metadata, dict):
        return components

    raw_regions = screen_metadata.get("componentRegions")
    if not isinstance(raw_regions, list):
        return components

    for idx, region in enumerate(raw_regions):
        if not isinstance(region, dict):
            continue
        component_id = str(
            region.get("id")
            or region.get("componentId")
            or f"comp-region-{idx + 1}"
        )
        component_name = str(
            region.get("name")
            or region.get("label")
            or f"Component {idx + 1}"
        )
        component_type = str(
            region.get("type")
            or region.get("componentType")
            or "region"
        )
        properties = {
            key: value
            for key, value in region.items()
            if key not in {"id", "componentId", "name", "label", "type", "componentType"}
        }
        components.append(
            ScreenComponent(
                id=component_id,
                name=component_name,
                type=component_type,
                properties=properties,
            )
        )
    return components


def _as_string_key_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _extract_assets(raw_screen: dict[str, Any]) -> list[str]:
    assets: list[str] = []
    seen: set[str] = set()

    def add_asset(value: str) -> None:
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        assets.append(candidate)

    raw_assets = raw_screen.get("assets")
    if isinstance(raw_assets, list):
        for item in raw_assets:
            if isinstance(item, str):
                add_asset(item)
            elif isinstance(item, dict):
                for key in ("downloadUrl", "name"):
                    val = item.get(key)
                    if isinstance(val, str):
                        add_asset(val)

    for key in ("screenshot", "htmlCode", "figmaExport"):
        raw_file = raw_screen.get(key)
        if isinstance(raw_file, str):
            add_asset(raw_file)
        elif isinstance(raw_file, dict):
            for candidate_key in ("downloadUrl", "name"):
                val = raw_file.get(candidate_key)
                if isinstance(val, str):
                    add_asset(val)

    return assets


def _extract_suggestions(raw: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        suggestions.append(candidate)

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        suggestion = node.get("suggestion")
        if isinstance(suggestion, str):
            add(suggestion)

        for key in ("output_components", "outputComponents", "content", "data", "structuredContent"):
            child = node.get(key)
            if isinstance(child, (dict, list)):
                walk(child)

        text = node.get("text")
        if isinstance(text, str) and text.strip() and "{" in text:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return
            walk(parsed)

    walk(raw)
    return suggestions
