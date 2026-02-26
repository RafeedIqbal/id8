from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True, slots=True)
class TokenPricing:
    """USD pricing per 1M input/output tokens for a model."""

    prompt_per_million: float
    completion_per_million: float


# MVP pricing table used for estimated-cost telemetry.
# Values can be adjusted as providers change pricing.
_MODEL_PRICING: dict[str, TokenPricing] = {
    "gemini-3.1-pro-preview": TokenPricing(prompt_per_million=2.00, completion_per_million=12.00),
    "gemini-3.1-pro-preview-customtools": TokenPricing(prompt_per_million=2.00, completion_per_million=12.00),
    "gemini-2.5-pro": TokenPricing(prompt_per_million=2.50, completion_per_million=7.50),
}


def estimate_llm_cost_usd(
    *,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Return estimated USD cost for a single model invocation."""
    pricing = _resolve_pricing_table().get(model_id)
    if pricing is None:
        return 0.0

    prompt_cost = (max(prompt_tokens, 0) / 1_000_000.0) * pricing.prompt_per_million
    completion_cost = (max(completion_tokens, 0) / 1_000_000.0) * pricing.completion_per_million
    return round(prompt_cost + completion_cost, 8)


def _resolve_pricing_table() -> dict[str, TokenPricing]:
    table = dict(_MODEL_PRICING)
    overrides = _parse_pricing_overrides(settings.llm_pricing_json)
    table.update(overrides)
    return table


def _parse_pricing_overrides(raw: str) -> dict[str, TokenPricing]:
    text = raw.strip()
    if not text:
        return {}

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, dict):
        return {}

    parsed: dict[str, TokenPricing] = {}
    for model_id, pricing in payload.items():
        if not isinstance(model_id, str) or not isinstance(pricing, dict):
            continue
        prompt = _to_float(pricing.get("prompt_per_million"))
        completion = _to_float(pricing.get("completion_per_million"))
        if prompt is None or completion is None:
            continue
        parsed[model_id] = TokenPricing(prompt_per_million=prompt, completion_per_million=completion)

    return parsed


def _to_float(raw: Any) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None
