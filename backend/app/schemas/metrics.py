from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class DistributionMetric(BaseModel):
    count: int
    p50_ms: float | None = None
    p95_ms: float | None = None
    avg_ms: float | None = None


class NodeLatencyMetric(BaseModel):
    node: str
    stats: DistributionMetric


class StageSloMetric(BaseModel):
    stage: str
    stats: DistributionMetric
    target_p50_ms: float
    target_p95_ms: float
    meets_p50: bool | None = None
    meets_p95: bool | None = None


class TokenCostTotals(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class ProfileTokenCostMetric(BaseModel):
    model_profile: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class RunTokenCostMetric(BaseModel):
    run_id: uuid.UUID
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class RetryMetric(BaseModel):
    node: str
    retry_count: int
    retry_delay_ms: float


class FailureReasonMetric(BaseModel):
    reason: str
    count: int


class DeploymentMetric(BaseModel):
    attempts: int
    succeeded: int
    failed: int
    success_rate: float | None = None
    time_to_live_url: DistributionMetric | None = None


class ProjectMetricsResponse(BaseModel):
    project_id: uuid.UUID
    generated_at: datetime
    node_latencies: list[NodeLatencyMetric]
    stage_slos: list[StageSloMetric]
    token_cost_totals: TokenCostTotals
    token_cost_by_profile: list[ProfileTokenCostMetric]
    token_cost_by_run: list[RunTokenCostMetric]
    retries: list[RetryMetric]
    failure_reasons: list[FailureReasonMetric]
    deployment: DeploymentMetric
