"""Design provider factory.

Currently only supports Stitch MCP.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.enums import DesignProvider as DesignProviderEnum

from .base import (
    DesignFeedback,
    DesignOutput,
    DesignProvider,
    StitchAuthContext,
)
from .stitch_mcp import StitchMcpProvider

logger = logging.getLogger("id8.design.provider_factory")

_PROVIDERS: dict[str, type[DesignProvider]] = {
    DesignProviderEnum.STITCH_MCP: StitchMcpProvider,
}


def get_provider(provider_name: str | DesignProviderEnum) -> DesignProvider:
    """Instantiate a design provider by name."""
    name = str(provider_name)
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown design provider: {name}")
    return cls()


async def generate_design(
    *,
    prd_content: dict[str, Any],
    constraints: dict[str, Any],
    auth: StitchAuthContext | None = None,
    preferred_provider: str | DesignProviderEnum = DesignProviderEnum.STITCH_MCP,
) -> tuple[DesignOutput, str]:
    """Generate a design.

    Returns ``(output, provider_used)`` where *provider_used* is the
    enum value of the provider that successfully generated the design.

    Raises ``StitchAuthError`` immediately if Stitch credentials are
    missing — auth errors are user-actionable and should not be
    silently swallowed.
    """
    provider_name = str(preferred_provider)
    provider = get_provider(provider_name)

    output = await provider.generate(
        prd_content=prd_content,
        constraints=constraints,
        auth=auth,
    )
    return output, provider_name


async def regenerate_design(
    *,
    previous: DesignOutput,
    feedback: DesignFeedback,
    auth: StitchAuthContext | None = None,
    preferred_provider: str | DesignProviderEnum = DesignProviderEnum.STITCH_MCP,
) -> tuple[DesignOutput, str]:
    """Regenerate a design with feedback."""
    provider_name = str(preferred_provider)
    provider = get_provider(provider_name)

    output = await provider.regenerate(
        previous=previous,
        feedback=feedback,
        auth=auth,
    )
    return output, provider_name
