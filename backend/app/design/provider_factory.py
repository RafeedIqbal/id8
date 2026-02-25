"""Design provider factory with automatic fallback.

Default selection order: stitch_mcp -> internal_spec.
On non-auth Stitch failures, automatically falls back to internal_spec
with an audit log entry.
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
    StitchAuthError,
    StitchRuntimeError,
)
from .internal_spec import InternalSpecProvider
from .stitch_mcp import StitchMcpProvider

logger = logging.getLogger("id8.design.provider_factory")

_PROVIDERS: dict[str, type[DesignProvider]] = {
    DesignProviderEnum.STITCH_MCP: StitchMcpProvider,
    DesignProviderEnum.INTERNAL_SPEC: InternalSpecProvider,
}

_FALLBACK_ORDER = [DesignProviderEnum.STITCH_MCP, DesignProviderEnum.INTERNAL_SPEC]


def get_provider(provider_name: str | DesignProviderEnum) -> DesignProvider:
    """Instantiate a design provider by name."""
    name = str(provider_name)
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown design provider: {name}")
    return cls()


async def generate_with_fallback(
    *,
    prd_content: dict[str, Any],
    constraints: dict[str, Any],
    auth: StitchAuthContext | None = None,
    preferred_provider: str | DesignProviderEnum = DesignProviderEnum.STITCH_MCP,
) -> tuple[DesignOutput, str]:
    """Generate a design, falling back on non-auth runtime errors.

    Returns ``(output, provider_used)`` where *provider_used* is the
    enum value of the provider that successfully generated the design.

    Raises ``StitchAuthError`` immediately if Stitch credentials are
    missing — auth errors are user-actionable and should not be
    silently swallowed.
    """
    preferred = str(preferred_provider)
    providers_to_try = [preferred]

    # Add fallback if not already preferred
    for name in _FALLBACK_ORDER:
        if name not in providers_to_try:
            providers_to_try.append(name)

    for provider_name in providers_to_try:
        provider = get_provider(provider_name)
        try:
            output = await provider.generate(
                prd_content=prd_content,
                constraints=constraints,
                auth=auth,
            )
            return output, provider_name
        except StitchAuthError:
            # Auth errors are user-actionable — surface immediately
            raise
        except StitchRuntimeError as exc:
            logger.warning(
                "AUDIT design_provider_fallback from=%s reason=%s",
                provider_name,
                str(exc)[:200],
            )
            continue

    # Should not reach here since internal_spec doesn't raise StitchRuntimeError,
    # but guard against unexpected errors
    raise RuntimeError("All design providers failed")


async def regenerate_with_fallback(
    *,
    previous: DesignOutput,
    feedback: DesignFeedback,
    auth: StitchAuthContext | None = None,
    preferred_provider: str | DesignProviderEnum = DesignProviderEnum.STITCH_MCP,
) -> tuple[DesignOutput, str]:
    """Regenerate a design with feedback, falling back on runtime errors."""
    preferred = str(preferred_provider)
    providers_to_try = [preferred]
    for name in _FALLBACK_ORDER:
        if name not in providers_to_try:
            providers_to_try.append(name)

    for provider_name in providers_to_try:
        provider = get_provider(provider_name)
        try:
            output = await provider.regenerate(
                previous=previous,
                feedback=feedback,
                auth=auth,
            )
            return output, provider_name
        except StitchAuthError:
            raise
        except StitchRuntimeError as exc:
            logger.warning(
                "AUDIT design_regenerate_fallback from=%s reason=%s",
                provider_name,
                str(exc)[:200],
            )
            continue

    raise RuntimeError("All design providers failed during regeneration")
