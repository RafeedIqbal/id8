"""Stitch MCP design provider (primary).

Communicates with the Stitch MCP endpoint to generate and iterate on
UI designs. Handles authentication, tool discovery, and error mapping.
"""
from __future__ import annotations

import json
import logging
import re
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
_ALLOWED_STITCH_MODEL_IDS = {"GEMINI_3_PRO", "GEMINI_3_FLASH"}
_ALLOWED_STITCH_DEVICE_TYPES = {"MOBILE", "DESKTOP", "TABLET", "AGNOSTIC"}
_MAX_LIST_SCREEN_ITEMS = 16
_MAX_CONTEXT_SCREENS = 8
_MAX_GET_SCREEN_CALLS = 6
_MAX_SCREEN_PREVIEWS = 4
_MAX_SCREEN_ASSETS = 8
_MAX_COMPONENT_REGIONS = 16

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
            suggested_name=_project_name_from_prd(
                prd_content,
                preferred_title=str(constraints.get("project_title", "")).strip(),
            ),
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
        design_codegen_context = await self._build_design_codegen_context(
            auth=auth,
            project_id=project_id,
            seed_screen_ids=[screen.id for screen in output.screens],
        )
        output.metadata.update({
            "provider": "stitch_mcp",
            "endpoint": _endpoint(),
            "generation_time_ms": elapsed_ms,
            "usable_tools": STITCH_TOOLS,
            "stitch_project_id": project_id,
            "stitch_project_url": _project_url(project_id),
            "stitch_model_id": model_id,
            "stitch_device_type": device_type,
            "design_codegen_context": design_codegen_context,
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
        design_codegen_context = await self._build_design_codegen_context(
            auth=auth,
            project_id=project_id,
            seed_screen_ids=[
                *selected_screen_ids,
                *[screen.id for screen in output.screens],
            ],
        )
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
            "design_codegen_context": design_codegen_context,
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

    async def _build_design_codegen_context(
        self,
        *,
        auth: StitchAuthContext,
        project_id: str,
        seed_screen_ids: list[str],
    ) -> dict[str, Any]:
        """Fetch additional Stitch context so codegen can mirror the design output."""
        context: dict[str, Any] = {
            "provider": "stitch_mcp",
            "project_id": project_id,
            "screens": [],
        }

        try:
            listed = await self._call_stitch(
                tool="list_screens",
                params={"projectId": project_id},
                auth=auth,
            )
        except StitchRuntimeError as exc:
            logger.warning(
                "Stitch list_screens enrichment failed for project=%s: %s",
                project_id,
                exc,
            )
            context["enrichment_error"] = str(exc)
            return context

        summaries = _extract_screen_summaries(listed)[:_MAX_LIST_SCREEN_ITEMS]
        context["listed_screen_count"] = len(summaries)

        ordered_ids: list[str] = []
        seen_ids: set[str] = set()

        for raw_id in seed_screen_ids:
            normalized = _normalize_screen_id(raw_id)
            if normalized and normalized not in seen_ids:
                seen_ids.add(normalized)
                ordered_ids.append(normalized)

        for summary in summaries:
            screen_id = str(summary.get("id", "")).strip()
            if screen_id and screen_id not in seen_ids:
                seen_ids.add(screen_id)
                ordered_ids.append(screen_id)

        summary_by_id = {
            str(summary.get("id", "")).strip(): summary
            for summary in summaries
            if isinstance(summary, dict)
        }

        failed_screen_ids: list[str] = []
        screens: list[dict[str, Any]] = []

        for screen_id in ordered_ids[:_MAX_GET_SCREEN_CALLS]:
            detail = await self._get_screen_detail(
                auth=auth,
                project_id=project_id,
                screen_id=screen_id,
                summary=summary_by_id.get(screen_id),
            )
            if detail is None:
                failed_screen_ids.append(screen_id)
                continue
            screens.append(_screen_to_codegen_context(detail, fallback_id=screen_id))

        if not screens:
            # Fallback to list_screens payload when detailed fetch is unavailable.
            for summary in summaries[:_MAX_CONTEXT_SCREENS]:
                fallback_id = str(summary.get("id", "")).strip()
                screens.append(_summary_to_codegen_context(summary, fallback_id=fallback_id))

        context["screens"] = screens[:_MAX_CONTEXT_SCREENS]
        context["available_screen_ids"] = ordered_ids[:_MAX_LIST_SCREEN_ITEMS]
        if failed_screen_ids:
            context["failed_screen_ids"] = failed_screen_ids
        return context

    async def _get_screen_detail(
        self,
        *,
        auth: StitchAuthContext,
        project_id: str,
        screen_id: str,
        summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        params = {"projectId": project_id, "screenId": screen_id}
        if summary:
            resource_name = summary.get("resource_name")
            if isinstance(resource_name, str) and resource_name.strip():
                params["name"] = resource_name

        try:
            raw = await self._call_stitch(
                tool="get_screen",
                params=params,
                auth=auth,
            )
        except StitchRuntimeError as exc:
            logger.warning(
                "Stitch get_screen enrichment failed for project=%s screen=%s: %s",
                project_id,
                screen_id,
                exc,
            )
            return None

        raw_screens = _extract_raw_screen_objects(raw)
        if raw_screens:
            return raw_screens[0]

        if isinstance(summary, dict):
            return summary
        return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_generation_prompt(prd_content: dict[str, Any], constraints: dict[str, Any]) -> str:
    """Translate an approved PRD into a Stitch-compatible generation prompt."""
    parts = [
        "Generate UI screens for a DESKTOP WEB APPLICATION.",
        (
            "Target device type: DESKTOP. Prioritize desktop-first information density, "
            "navigation, and responsive web patterns."
        ),
        "",
        "Product context:",
    ]

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
    parts = [
        "Regenerate the desktop web app design with the following feedback:\n",
        "Keep target device type as DESKTOP unless explicitly overridden.\n",
    ]
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

def _project_name_from_prd(prd_content: dict[str, Any], preferred_title: str = "") -> str:
    cleaned_preferred = _clean_project_title(preferred_title)
    if cleaned_preferred:
        return cleaned_preferred

    for key in ("title", "project_title", "name"):
        cleaned = _clean_project_title(str(prd_content.get(key, "")).strip())
        if cleaned:
            return cleaned

    summary = str(prd_content.get("executive_summary", "")).strip()
    if summary:
        first_line = summary.splitlines()[0].strip()
        first_sentence = first_line.split(".", 1)[0].strip()
        cleaned = _clean_project_title(first_sentence or first_line)
        if cleaned:
            return cleaned
    return "id8 Design"


def _extract_project_id(raw: dict[str, Any]) -> str:
    direct = _extract_project_id_shallow(raw)
    if direct:
        return direct

    for candidate in _extract_projects(raw):
        project_id = _extract_project_id_shallow(candidate)
        if project_id:
            return project_id

    return ""


def _extract_project_id_shallow(raw: dict[str, Any]) -> str:
    project = raw.get("project")
    data = raw.get("data")
    structured = raw.get("structuredContent")
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
        structured.get("projectId") if isinstance(structured, dict) else None,
        structured.get("project_id") if isinstance(structured, dict) else None,
        structured.get("id") if isinstance(structured, dict) else None,
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
        structured.get("name") if isinstance(structured, dict) else None,
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
    raw_model_id = str(
        constraints.get("modelId")
        or constraints.get("model_id")
        or constraints.get("stitch_model_id")
        or _DEFAULT_STITCH_MODEL_ID
    ).strip()
    return _normalize_model_id(raw_model_id)


def _resolve_device_type(constraints: dict[str, Any]) -> str:
    raw_device_type = str(
        constraints.get("deviceType")
        or constraints.get("device_type")
        or constraints.get("stitch_device_type")
        or _DEFAULT_DEVICE_TYPE
    ).strip()
    return _normalize_device_type(raw_device_type)


def _normalize_model_id(raw_model_id: str) -> str:
    value = re.sub(r"[^A-Z0-9]+", "_", raw_model_id.strip().upper())
    value = re.sub(r"_+", "_", value).strip("_")
    if value in _ALLOWED_STITCH_MODEL_IDS:
        return value
    if "FLASH" in value:
        return "GEMINI_3_FLASH"
    if "PRO" in value:
        return "GEMINI_3_PRO"
    return _DEFAULT_STITCH_MODEL_ID


def _normalize_device_type(raw_device_type: str) -> str:
    value = re.sub(r"[^A-Z0-9]+", "_", raw_device_type.strip().upper())
    value = re.sub(r"_+", "_", value).strip("_")
    if value in _ALLOWED_STITCH_DEVICE_TYPES:
        return value
    if "DESKTOP" in value or "WEB" in value or "BROWSER" in value:
        return "DESKTOP"
    if "MOBILE" in value or "PHONE" in value:
        return "MOBILE"
    if "TABLET" in value or "IPAD" in value:
        return "TABLET"
    if "AGNOSTIC" in value:
        return "AGNOSTIC"
    return _DEFAULT_DEVICE_TYPE


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
    wanted = _normalize_title_for_match(title)
    if not wanted:
        return ""

    for project in _extract_projects(raw):
        project_title = _extract_project_title(project)
        if project_title and _normalize_title_for_match(project_title) == wanted:
            project_id = _extract_project_id(project)
            if project_id:
                return project_id
    return ""


def _normalize_title_for_match(title: str) -> str:
    text = title.strip().casefold()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.startswith("a "):
        text = text[2:].strip()
    elif text.startswith("an "):
        text = text[3:].strip()
    elif text.startswith("the "):
        text = text[4:].strip()
    return text


def _clean_project_title(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" .,:;|-_")
    if len(value) <= 64:
        return value
    short = value[:64].rstrip()
    if " " in short:
        short = short.rsplit(" ", 1)[0]
    return short.strip(" .,:;|-_")


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


def _extract_screen_summaries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a normalized list of screen metadata from list_screens payload."""
    summaries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for raw_screen in _extract_raw_screen_objects(raw):
        screen_id = ""
        for candidate in (
            raw_screen.get("screenId"),
            raw_screen.get("screen_id"),
            raw_screen.get("id"),
            raw_screen.get("name"),
        ):
            if isinstance(candidate, str):
                normalized = _normalize_screen_id(candidate)
                if normalized:
                    screen_id = normalized
                    break
        if not screen_id or screen_id in seen_ids:
            continue
        seen_ids.add(screen_id)

        resource_name = raw_screen.get("name")
        screen_name = raw_screen.get("title") or raw_screen.get("displayName") or resource_name or screen_id
        if isinstance(screen_name, str) and "/screens/" in screen_name:
            screen_name = screen_id

        summaries.append(
            {
                "id": screen_id,
                "resource_name": resource_name if isinstance(resource_name, str) else "",
                "name": str(screen_name).strip() if isinstance(screen_name, str) else screen_id,
                "description": str(raw_screen.get("description", "")).strip(),
                "preview_images": _extract_preview_images(raw_screen),
                "assets": _extract_assets(raw_screen)[:_MAX_SCREEN_ASSETS],
                "component_regions": _extract_component_regions(raw_screen),
                "render_metadata": _extract_render_metadata(raw_screen),
            }
        )

    return summaries


def _extract_preview_images(raw_screen: dict[str, Any]) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        if not _looks_like_image_asset(candidate):
            return
        seen.add(candidate)
        images.append(candidate)

    screenshot = raw_screen.get("screenshot")
    if isinstance(screenshot, str):
        add(screenshot)
    elif isinstance(screenshot, dict):
        for key in ("downloadUrl", "url", "name"):
            value = screenshot.get(key)
            if isinstance(value, str):
                add(value)

    for asset in _extract_assets(raw_screen):
        add(asset)

    return images[:_MAX_SCREEN_PREVIEWS]


def _looks_like_image_asset(value: str) -> bool:
    normalized = value.casefold()
    return any(
        token in normalized
        for token in (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".svg",
            "image",
            "screenshot",
        )
    )


def _extract_component_regions(raw_screen: dict[str, Any]) -> list[dict[str, Any]]:
    screen_metadata = raw_screen.get("screenMetadata")
    if not isinstance(screen_metadata, dict):
        return []

    raw_regions = screen_metadata.get("componentRegions")
    if not isinstance(raw_regions, list):
        return []

    regions: list[dict[str, Any]] = []
    for index, raw_region in enumerate(raw_regions[:_MAX_COMPONENT_REGIONS]):
        if not isinstance(raw_region, dict):
            continue

        region: dict[str, Any] = {
            "id": str(
                raw_region.get("id")
                or raw_region.get("componentId")
                or f"region-{index + 1}"
            ),
            "name": str(
                raw_region.get("name")
                or raw_region.get("label")
                or f"Region {index + 1}"
            ),
            "type": str(raw_region.get("type") or raw_region.get("componentType") or "region"),
        }

        bounds = raw_region.get("bounds")
        if isinstance(bounds, dict):
            region["bounds"] = _as_string_key_dict(bounds)

        for key in ("x", "y", "width", "height"):
            value = raw_region.get(key)
            if isinstance(value, (int, float)):
                region[key] = value

        regions.append(region)

    return regions


def _extract_render_metadata(raw_screen: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    screen_metadata = raw_screen.get("screenMetadata")
    if isinstance(screen_metadata, dict):
        for key in ("status", "statusMessage", "deviceType", "screenType", "viewport"):
            value = screen_metadata.get(key)
            if value is not None:
                metadata[key] = value

    for key in ("width", "height"):
        value = raw_screen.get(key)
        if isinstance(value, (int, float)):
            metadata[key] = value

    return metadata


def _screen_to_codegen_context(raw_screen: dict[str, Any], *, fallback_id: str) -> dict[str, Any]:
    parsed = _screen_from_raw(raw_screen, 0)
    screen_id = parsed.id if parsed is not None else fallback_id
    name = parsed.name if parsed is not None else (fallback_id or "Screen")
    description = parsed.description if parsed is not None else ""

    return {
        "id": screen_id or fallback_id,
        "name": name,
        "description": description,
        "preview_images": _extract_preview_images(raw_screen),
        "assets": _extract_assets(raw_screen)[:_MAX_SCREEN_ASSETS],
        "component_regions": _extract_component_regions(raw_screen),
        "render_metadata": _extract_render_metadata(raw_screen),
    }


def _summary_to_codegen_context(summary: dict[str, Any], *, fallback_id: str) -> dict[str, Any]:
    screen_id = str(summary.get("id", "")).strip() or fallback_id
    return {
        "id": screen_id,
        "name": str(summary.get("name", "")).strip() or screen_id or "Screen",
        "description": str(summary.get("description", "")).strip(),
        "preview_images": [
            value
            for value in summary.get("preview_images", [])
            if isinstance(value, str)
        ][: _MAX_SCREEN_PREVIEWS],
        "assets": [
            value
            for value in summary.get("assets", [])
            if isinstance(value, str)
        ][: _MAX_SCREEN_ASSETS],
        "component_regions": [
            value
            for value in summary.get("component_regions", [])
            if isinstance(value, dict)
        ][: _MAX_COMPONENT_REGIONS],
        "render_metadata": (
            summary.get("render_metadata")
            if isinstance(summary.get("render_metadata"), dict)
            else {}
        ),
    }


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
