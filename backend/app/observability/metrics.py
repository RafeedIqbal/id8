from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

NODE_P95_TARGET_MS: dict[str, float] = {
    "GeneratePRD": 120_000.0,
    "GenerateDesign": 240_000.0,
}

PIPELINE_P95_TARGET_MS: float = 30.0 * 60.0 * 1000.0


def percentile(values: Iterable[float], p: float) -> float | None:
    """Compute percentile *p* using linear interpolation."""
    sorted_values = sorted(float(v) for v in values)
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)

    rank = (len(sorted_values) - 1) * (p / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(sorted_values[lower], 2)

    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    interpolated = lower_value + (upper_value - lower_value) * (rank - lower)
    return round(interpolated, 2)


def summarize_distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    """Return count, p50, p95, and average for *values*."""
    materialized = [float(v) for v in values]
    if not materialized:
        return {
            "count": 0,
            "p50_ms": None,
            "p95_ms": None,
            "avg_ms": None,
        }

    return {
        "count": len(materialized),
        "p50_ms": percentile(materialized, 50.0),
        "p95_ms": percentile(materialized, 95.0),
        "avg_ms": round(sum(materialized) / len(materialized), 2),
    }


def categorize_failure_reason(
    *,
    error_message: str | None,
    error_code: str | None = None,
) -> str:
    """Map raw errors to MVP failure classes required by observability."""
    code = (error_code or "").strip().lower()
    message = (error_message or "").strip().lower()

    if code == "rate_limit" or "rate limit" in message or "retry after" in message:
        return "rate_limit"

    validation_markers = (
        "schema validation",
        "validation failed",
        "invalid json",
        "parse failed",
        "unprocessable",
    )
    if any(marker in message for marker in validation_markers):
        return "validation_error"

    policy_markers = (
        "approval",
        "policy",
        "forbidden",
        "unauthorized",
        "blocked",
        "permission",
    )
    if any(marker in message for marker in policy_markers):
        return "policy_violation"

    provider_markers = (
        "gemini",
        "stitch",
        "supabase",
        "vercel",
        "github",
        "provider",
        "api error",
    )
    if any(marker in message for marker in provider_markers):
        return "provider_error"

    return "provider_error"


def aggregate_numeric_by_key(
    rows: Iterable[tuple[str, float]],
) -> dict[str, float]:
    """Utility for summing numeric values grouped by string key."""
    grouped: dict[str, float] = defaultdict(float)
    for key, value in rows:
        grouped[key] += float(value)
    return dict(grouped)
