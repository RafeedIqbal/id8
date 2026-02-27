"""Base types and abstract interface for design providers.

Defines the ``DesignProvider`` ABC, data models (``DesignOutput``,
``DesignFeedback``, ``StitchAuthContext``), and error types shared across
all design provider implementations.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Stitch auth
# ---------------------------------------------------------------------------


class StitchAuthMethod(enum.StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth_access_token"


@dataclass(frozen=True, slots=True)
class StitchAuthContext:
    """Holds Stitch MCP credentials — secrets are never logged or persisted."""

    auth_method: StitchAuthMethod
    api_key: str = ""
    oauth_token: str = ""
    goog_user_project: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> StitchAuthContext | None:
        """Build a context from an untyped payload.

        Returns ``None`` when payload is missing or not a mapping.
        """
        if payload is None:
            return None

        method_raw = str(payload.get("auth_method", StitchAuthMethod.API_KEY.value))
        try:
            method = StitchAuthMethod(method_raw)
        except ValueError:
            method = StitchAuthMethod.API_KEY

        return cls(
            auth_method=method,
            api_key=str(payload.get("api_key", "")),
            oauth_token=str(payload.get("oauth_token", "")),
            goog_user_project=str(payload.get("goog_user_project", "")),
        )

    def build_headers(self) -> dict[str, str]:
        """Return HTTP headers required by the selected auth method."""
        if self.auth_method == StitchAuthMethod.API_KEY:
            return {"X-Goog-Api-Key": self.api_key}
        return {
            "Authorization": f"Bearer {self.oauth_token}",
            "X-Goog-User-Project": self.goog_user_project,
        }

    def redacted_summary(self) -> dict[str, str]:
        """Return metadata safe for logging / artifact storage."""
        return {"auth_method": self.auth_method.value}


# ---------------------------------------------------------------------------
# Design data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ScreenComponent:
    id: str
    name: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Screen:
    id: str
    name: str
    description: str = ""
    components: list[ScreenComponent] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DesignOutput:
    """Result of a design generation or regeneration call."""

    screens: list[Screen] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "screens": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "components": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "type": c.type,
                            "properties": c.properties,
                        }
                        for c in s.components
                    ],
                    "assets": s.assets,
                }
                for s in self.screens
            ],
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class DesignFeedback:
    """Structured feedback targeting a specific screen/component."""

    feedback_text: str
    target_screen_id: str | None = None
    target_component_id: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DesignProviderError(Exception):
    """Base error raised by design providers."""


class StitchAuthError(DesignProviderError):
    """Raised when Stitch credentials are missing or invalid.

    Carries a user-actionable payload that the frontend can render as a
    credential prompt.
    """

    def __init__(self, message: str, action_payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.action_payload = action_payload or self._default_payload()

    @staticmethod
    def _default_payload() -> dict[str, Any]:
        return {
            "error_type": "stitch_auth_required",
            "message": "Stitch MCP credentials are required to generate designs.",
            "instructions": [
                "Open Stitch Settings (stitch.withgoogle.com)",
                "Navigate to API Keys",
                "Click 'Create API Key'",
                "Paste the generated API key into ID8",
            ],
            "fallback_note": (
                "If API key entry is not supported in your environment, you may use OAuth access token mode instead."
            ),
        }


class StitchRuntimeError(DesignProviderError):
    """Non-auth Stitch error (timeout, rate-limit, service unavailable)."""


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class DesignProvider(ABC):
    """Contract for design generation providers."""

    @abstractmethod
    async def generate(
        self,
        prd_content: dict[str, Any],
        constraints: dict[str, Any],
        auth: StitchAuthContext | None = None,
    ) -> DesignOutput:
        """Generate an initial design from an approved PRD."""

    @abstractmethod
    async def regenerate(
        self,
        previous: DesignOutput,
        feedback: DesignFeedback,
        auth: StitchAuthContext | None = None,
    ) -> DesignOutput:
        """Regenerate a design incorporating targeted feedback."""
