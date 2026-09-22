"""Pydantic request/response models for the API layer."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    ticket_id: str
    hostname: str
    mount_point: str
    requested_gb: float = Field(gt=0)
    requester: str | None = None


class DecisionOut(BaseModel):
    request_id: int
    decision: str
    score: float | None
    recommended_gb: float | None
    reasoning: dict

    model_config = {"from_attributes": True}


class RequestOut(BaseModel):
    id: int
    ticket_id: str
    hostname: str
    mount_point: str
    requested_gb: float
    requester: str | None
    created_at: dt.datetime
    latest_decision: DecisionOut | None = None

    model_config = {"from_attributes": True}


class HostOut(BaseModel):
    id: int
    hostname: str
    dt_entity_id: str | None
    environment: str | None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class DiskMetricOut(BaseModel):
    mount_point: str
    capacity_bytes: int
    used_bytes: int
    used_pct: float
    collected_at: dt.datetime

    model_config = {"from_attributes": True}


class FilesystemGrowthOut(BaseModel):
    hostname: str
    mount_point: str
    growth_pct_points: float
    growth_gb: float
    current_used_pct: float
    current_used_gb: float
    current_capacity_gb: float

    model_config = {"from_attributes": True}


class FilesystemUsageOut(BaseModel):
    hostname: str
    mount_point: str
    used_pct: float
    used_gb: float
    capacity_gb: float
    collected_at: dt.datetime

    model_config = {"from_attributes": True}


class CorrelationPointOut(BaseModel):
    timestamp_ms: int
    value: float | None


class CorrelationSeriesOut(BaseModel):
    metric_id: str
    label: str
    unit: str
    points: list[CorrelationPointOut]


class OverrideRequest(BaseModel):
    new_decision: str
    reason: str = Field(min_length=1)
    user: str


class OverrideOut(BaseModel):
    id: int
    decision_id: int
    new_decision: str
    reason: str
    user: str
    created_at: dt.datetime

    model_config = {"from_attributes": True}
