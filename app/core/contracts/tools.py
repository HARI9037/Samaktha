"""Tool chain execution contracts for Samaktha Core.

Defines the data models used for deterministic multi-step tool execution.
"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ToolFailurePolicy(str, Enum):
    STOP_ON_FAILURE = "stop_on_failure"
    CONTINUE_ON_FAILURE = "continue_on_failure"
    RETRY_FAILED_STEP = "retry_failed_step"


class ToolStep(BaseModel):
    """Represents a single tool execution step within a chain."""

    step_id: str
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str = ""
    optional_timeout: Optional[float] = None


class ToolChain(BaseModel):
    """A deterministic sequence of tool executions."""

    chain_id: str
    name: str
    steps: list[ToolStep] = Field(default_factory=list)
    max_steps: int = 10
    metadata: dict[str, Any] = Field(default_factory=dict)
    failure_policy: ToolFailurePolicy = ToolFailurePolicy.STOP_ON_FAILURE


class ToolExecutionResult(BaseModel):
    """Normalized result of a single tool execution within a chain."""

    step_id: str
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: float
