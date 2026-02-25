"""Gemini SDK client wrapper for the ID8 LLM layer.

Provides ``generate()`` for single-shot calls and
``generate_with_fallback()`` for automatic fallback retry logic.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import settings
from app.models.enums import ModelProfile
from app.orchestrator.retry import RateLimitError, RetryableError

from .router import resolve_model

logger = logging.getLogger("id8.llm.client")

# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts from a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LlmResponse:
    """Normalised response from a Gemini ``generate_content`` call."""

    content: str
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    model_id: str = ""
    latency_ms: float = 0.0
    profile_used: ModelProfile = ModelProfile.PRIMARY


# ---------------------------------------------------------------------------
# Lazy singleton Gemini client
# ---------------------------------------------------------------------------

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Return (and lazily create) the module-level Gemini client."""
    global _client  # noqa: PLW0603
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


# ---------------------------------------------------------------------------
# Low-level generate
# ---------------------------------------------------------------------------

# Retryable HTTP status codes from the Gemini API.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


async def generate(
    *,
    model_id: str,
    prompt: str,
    system_prompt: str = "",
    tools: list[types.Tool] | None = None,
) -> LlmResponse:
    """Call Gemini ``generate_content`` and return an :class:`LlmResponse`.

    Raises:
        RateLimitError: on HTTP 429 responses.
        RetryableError: on transient server errors (5xx).
        google.genai.errors.APIError: on permanent client errors.
    """
    client = _get_client()

    config = types.GenerateContentConfig(
        system_instruction=system_prompt or None,
        tools=tools,
    )

    start = time.monotonic()
    try:
        response = await client.aio.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config,
        )
    except genai_errors.APIError as exc:
        _handle_api_error(exc)
        raise  # unreachable — _handle_api_error always raises

    elapsed_ms = (time.monotonic() - start) * 1000

    # Extract token usage from response metadata
    usage = TokenUsage()
    if response.usage_metadata is not None:
        usage = TokenUsage(
            prompt_tokens=response.usage_metadata.input_token_count or 0,
            completion_tokens=response.usage_metadata.output_token_count or 0,
        )

    content = response.text or ""
    return LlmResponse(
        content=content,
        token_usage=usage,
        model_id=model_id,
        latency_ms=round(elapsed_ms, 2),
    )


# ---------------------------------------------------------------------------
# High-level generate with fallback
# ---------------------------------------------------------------------------

_MAX_INTERNAL_RETRIES = 2  # total attempts = 1 initial + 2 retries


async def generate_with_fallback(
    *,
    profile: ModelProfile,
    node_name: str,
    prompt: str,
    system_prompt: str = "",
    tools: list[types.Tool] | None = None,
) -> LlmResponse:
    """Generate content with automatic fallback retry logic.

    Retry tiers:
        1. First attempt: model resolved from *profile*.
        2. Second attempt: same model (transient blip).
        3. Third attempt: ``fallback`` profile model.

    If all attempts fail the final exception is re-raised.
    """
    model_id = resolve_model(profile)
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_INTERNAL_RETRIES + 2):  # 1, 2, 3
        current_model = model_id
        current_profile = profile

        # On third attempt, switch to fallback
        if attempt == 3 and profile != ModelProfile.FALLBACK:
            current_model = resolve_model(ModelProfile.FALLBACK)
            current_profile = ModelProfile.FALLBACK
            logger.warning(
                "Switching to fallback model=%s for node=%s (attempt %d)",
                current_model,
                node_name,
                attempt,
            )

        try:
            resp = await generate(
                model_id=current_model,
                prompt=prompt,
                system_prompt=system_prompt,
                tools=tools,
            )
            return LlmResponse(
                content=resp.content,
                token_usage=resp.token_usage,
                model_id=resp.model_id,
                latency_ms=resp.latency_ms,
                profile_used=current_profile,
            )
        except (RetryableError, RateLimitError) as exc:
            last_exc = exc
            logger.warning(
                "Attempt %d failed for node=%s model=%s: %s",
                attempt,
                node_name,
                current_model,
                exc,
            )
            if attempt >= _MAX_INTERNAL_RETRIES + 1:
                break
            continue

    # All internal retries exhausted — surface the error
    assert last_exc is not None  # noqa: S101
    raise last_exc


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _handle_api_error(exc: genai_errors.APIError) -> None:
    """Translate a Gemini ``APIError`` into the appropriate retry exception."""
    status = getattr(exc, "code", None) or 0

    if status == 429:
        # Extract retry-after hint if available
        retry_after: float | None = None
        headers = getattr(exc, "headers", None) or {}
        if isinstance(headers, dict):
            raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw is not None:
                try:
                    retry_after = float(raw)
                except (ValueError, TypeError):
                    pass

        msg = f"Rate limited (429) from Gemini API"
        if retry_after is not None:
            msg += f" — retry after {retry_after}s"
        raise RateLimitError(msg) from exc

    if status in _RETRYABLE_STATUS_CODES:
        raise RetryableError(f"Transient Gemini API error ({status})") from exc

    # Permanent error — let it propagate
    raise exc
