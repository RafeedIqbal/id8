"""Gemini SDK client wrapper for the ID8 LLM layer.

Provides ``generate()`` for single-shot calls and
``generate_with_fallback()`` for automatic fallback retry logic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast

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
    tools: Sequence[types.Tool] | None = None,
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
        tools=cast(list[Any] | None, tools),
    )

    start = time.monotonic()
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model_id,
                contents=prompt,
                config=config,
            ),
            timeout=max(0.1, float(settings.llm_request_timeout_seconds)),
        )
    except TimeoutError as exc:
        raise RetryableError(f"Gemini request timed out after {settings.llm_request_timeout_seconds}s") from exc
    except genai_errors.APIError as exc:
        _handle_api_error(exc)
        raise  # unreachable — _handle_api_error always raises

    elapsed_ms = (time.monotonic() - start) * 1000

    # Extract token usage from response metadata
    usage = TokenUsage()
    if response.usage_metadata is not None:
        usage_metadata = response.usage_metadata
        prompt_tokens = (
            getattr(usage_metadata, "prompt_token_count", None)
            or getattr(usage_metadata, "input_token_count", None)
            or 0
        )
        completion_tokens = getattr(usage_metadata, "candidates_token_count", None) or getattr(
            usage_metadata, "output_token_count", None
        )
        if completion_tokens is None:
            total_tokens = getattr(usage_metadata, "total_token_count", None) or 0
            completion_tokens = max(0, total_tokens - prompt_tokens)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
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

_MAX_INTERNAL_RETRIES = 3  # total attempts = 1 initial + 3 retries
_REDUCED_PROMPT_MAX_CHARS = 4_000


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
        4. Fourth attempt: ``fallback`` profile model with reduced prompt.

    If all attempts fail the final exception is re-raised.
    """
    primary_model = resolve_model(profile)
    fallback_model = resolve_model(ModelProfile.FALLBACK)
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_INTERNAL_RETRIES + 2):  # 1, 2, 3, 4
        current_profile = profile
        current_model = primary_model
        current_prompt = prompt

        # On third attempt and beyond, switch to fallback
        if attempt >= 3:
            current_profile = ModelProfile.FALLBACK
            current_model = fallback_model
            if attempt == 3 and profile != ModelProfile.FALLBACK:
                logger.warning(
                    "AUDIT llm_model_switch node=%s from_profile=%s to_profile=%s from_model=%s to_model=%s",
                    node_name,
                    profile,
                    ModelProfile.FALLBACK,
                    primary_model,
                    fallback_model,
                )

        # Third retry uses fallback with a compacted prompt.
        if attempt == 4:
            current_prompt = _reduce_prompt(prompt)
            if current_prompt != prompt:
                logger.warning(
                    "AUDIT llm_prompt_reduced node=%s model=%s original_chars=%d reduced_chars=%d",
                    node_name,
                    current_model,
                    len(prompt),
                    len(current_prompt),
                )

        try:
            resp = await generate(
                model_id=current_model,
                prompt=current_prompt,
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
        except RetryableError as exc:
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


def _reduce_prompt(prompt: str, *, max_chars: int = _REDUCED_PROMPT_MAX_CHARS) -> str:
    """Return a compact prompt variant for final fallback attempts."""
    if len(prompt) <= max_chars:
        return prompt

    # Keep both the beginning and end to preserve task context and constraints.
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return f"{prompt[:head_chars]}\n\n[...prompt truncated for fallback retry...]\n\n{prompt[-tail_chars:]}"


def _parse_retry_after(raw_value: str | int | float) -> float | None:
    """Parse a Retry-After header value into seconds."""
    if isinstance(raw_value, (int, float)):
        return max(0.0, float(raw_value))

    raw = str(raw_value).strip()
    if not raw:
        return None

    try:
        return max(0.0, float(raw))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(raw)
    except TypeError, ValueError, IndexError:
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)

    return max(0.0, (retry_at - datetime.now(tz=UTC)).total_seconds())


def _extract_retry_after_seconds(exc: genai_errors.APIError) -> float | None:
    """Best-effort extraction of Retry-After seconds from a Gemini API error."""
    headers: object | None = None
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(exc, "headers", None)

    if headers is None or not hasattr(headers, "get"):
        return None

    headers_map = cast(Any, headers)
    raw = headers_map.get("retry-after") or headers_map.get("Retry-After")
    if raw is None:
        return None
    return _parse_retry_after(raw)


def _handle_api_error(exc: genai_errors.APIError) -> None:
    """Translate a Gemini ``APIError`` into the appropriate retry exception."""
    status = getattr(exc, "code", None) or 0

    if status == 429:
        # Extract retry-after hint if available
        retry_after = _extract_retry_after_seconds(exc)

        msg = "Rate limited (429) from Gemini API"
        if retry_after is not None:
            msg += f" — retry after {retry_after}s"
        raise RateLimitError(msg, retry_after_seconds=retry_after) from exc

    if status in _RETRYABLE_STATUS_CODES:
        raise RetryableError(f"Transient Gemini API error ({status})") from exc

    # Permanent error — let it propagate
    raise exc
