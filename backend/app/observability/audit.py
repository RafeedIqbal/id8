from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent
from app.models.enums import ModelProfile
from app.observability.costs import estimate_llm_cost_usd

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


async def emit_audit_event(
    project_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    event_type: str,
    event_payload: Mapping[str, Any] | None,
    db: AsyncSession,
) -> AuditEvent:
    """Persist an audit event into ``audit_events``."""
    payload = _to_json_value(dict(event_payload or {}))
    if not isinstance(payload, dict):
        payload = {}

    event = AuditEvent(
        project_id=project_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        event_payload=payload,
    )
    db.add(event)
    return event


async def emit_llm_usage_event(
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    node: str,
    model_profile: ModelProfile | str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    db: AsyncSession,
) -> float:
    """Emit normalized LLM token/cost telemetry as an audit event."""
    estimated_cost_usd = estimate_llm_cost_usd(
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    await emit_audit_event(
        project_id=project_id,
        actor_user_id=None,
        event_type="llm.usage_recorded",
        event_payload={
            "run_id": str(run_id),
            "node": node,
            "model_profile": str(model_profile),
            "model_id": model_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": max(prompt_tokens, 0) + max(completion_tokens, 0),
            "estimated_cost_usd": estimated_cost_usd,
        },
        db=db,
    )
    return estimated_cost_usd


def _to_json_value(value: Any) -> JsonValue:
    """Convert SQLAlchemy/enum/uuid payload values into JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        converted: dict[str, JsonValue] = {}
        for key, nested in value.items():
            converted[str(key)] = _to_json_value(nested)
        return converted
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_json_value(item) for item in value]
    return str(value)
