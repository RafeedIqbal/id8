"""Stitch MCP design provider (primary).

Communicates with the Stitch MCP endpoint to generate and iterate on
UI designs.  Handles authentication, tool discovery, and error mapping.
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
_DEFAULT_STITCH_MODEL_ID = "gemini_3_flash"

# ---------------------------------------------------------------------------
# Canonical Stitch MCP tool inventory
# ---------------------------------------------------------------------------

STITCH_TOOLS: list[dict[str, Any]] = [
    {"name": "create_project", "params": ["name"], "description": "Create a new Stitch project"},
    {"name": "list_projects", "params": ["filter"], "description": "List Stitch projects"},
    {"name": "list_screens", "params": ["project_id"], "description": "List screens in a project"},
    {"name": "get_project", "params": ["name"], "description": "Get project details by name"},
    {"name": "get_screen", "params": ["project_id", "screen_id"], "description": "Get a specific screen"},
    {
        "name": "generate_screen_from_text",
        "params": ["project_id", "prompt", "model_id"],
        "description": "Generate a screen from a text prompt",
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

        start = time.monotonic()
        raw = await self._call_stitch(
            tool="generate_screen_from_text",
            params={
                "project_id": project_id,
                "prompt": prompt,
                "model_id": _DEFAULT_STITCH_MODEL_ID,
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
            "stitch_model_id": _DEFAULT_STITCH_MODEL_ID,
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
        params: dict[str, Any] = {
            "project_id": project_id,
            "prompt": prompt,
            "model_id": _DEFAULT_STITCH_MODEL_ID,
        }

        start = time.monotonic()
        raw = await self._call_stitch(
            tool="generate_screen_from_text",
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
            "stitch_model_id": _DEFAULT_STITCH_MODEL_ID,
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
            return existing_project_id

        try:
            existing = await self._call_stitch(
                tool="get_project",
                params={"name": suggested_name},
                auth=auth,
            )
            existing_id = _extract_project_id(existing)
            if existing_id:
                return existing_id
        except StitchRuntimeError:
            # Not found or unsupported lookup; fall through to create.
            pass

        created = await self._call_stitch(
            tool="create_project",
            params={"name": suggested_name},
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
    project = raw.get("project")
    data = raw.get("data")
    candidates: list[Any] = [
        raw.get("project_id"),
        raw.get("id"),
        project.get("project_id") if isinstance(project, dict) else None,
        project.get("id") if isinstance(project, dict) else None,
        data.get("project_id") if isinstance(data, dict) else None,
        data.get("id") if isinstance(data, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
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
    screens: list[Screen] = []

    # Stitch may return screens under various keys/shapes.
    raw_screens: Any = []
    if isinstance(raw.get("screens"), list):
        raw_screens = raw.get("screens", [])
    elif isinstance(raw.get("content"), dict):
        raw_screens = raw.get("content", {}).get("screens", [])
    elif isinstance(raw.get("data"), dict):
        raw_screens = raw.get("data", {}).get("screens", [])
    elif isinstance(raw.get("content"), list):
        for item in raw.get("content", []):
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("screens"), list):
                raw_screens = parsed.get("screens", [])
                break

    if isinstance(raw_screens, list):
        for i, rs in enumerate(raw_screens):
            if not isinstance(rs, dict):
                continue
            components = []
            for j, rc in enumerate(rs.get("components", [])):
                if not isinstance(rc, dict):
                    continue
                components.append(ScreenComponent(
                    id=rc.get("id", f"comp-{j}"),
                    name=rc.get("name", f"Component {j}"),
                    type=rc.get("type", "unknown"),
                    properties=rc.get("properties", {}),
                ))
            screens.append(Screen(
                id=rs.get("id", f"screen-{i}"),
                name=rs.get("name", f"Screen {i}"),
                description=rs.get("description", ""),
                components=components,
                assets=rs.get("assets", []),
            ))

    return DesignOutput(screens=screens)
