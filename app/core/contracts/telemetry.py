from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MetricCategory(str, Enum):
    EXECUTION = "execution"
    MEMORY = "memory"
    AGENT = "agent"
    WORKER = "worker"
    RECOVERY = "recovery"
    ROUTING = "routing"
    WORKFLOW = "workflow"


class TelemetryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: MetricCategory
    name: str
    value: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class TelemetrySnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: dict[str, Any] = Field(default_factory=dict)
