"""Shared tool models: permissions, policies, contexts and reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ToolPermission(StrEnum):
    """Fine-grained permissions a tool may require at runtime.

    CAP's policy engine decides whether each permission is granted or
    needs explicit approval; tools never grant themselves access.
    """

    READ = "read"
    WRITE = "write"
    MODIFY = "modify"
    DELETE = "delete"
    EXECUTE = "execute"
    NETWORK = "network"
    ADMIN = "admin"


class ToolPolicy(BaseModel):
    """Static execution policy declared by a tool."""

    permissions: tuple[ToolPermission, ...] = Field(default_factory=tuple)
    approval_required: bool = False
    default_timeout_s: float = 30.0
    max_retries: int = 0
    retry_backoff_s: float = 0.5
    rollback_supported: bool = False
    max_parallel_instances: int = 1
    description: str = ""

    def requires_permission(self, permission: ToolPermission) -> bool:
        return permission in self.permissions


class ToolContext(BaseModel):
    """Execution context supplied by the caller for a single invocation."""

    request_id: str = ""
    user_id: str = ""
    session_id: str = ""
    granted_permissions: tuple[ToolPermission, ...] = Field(default_factory=tuple)
    timeout_s: Optional[float] = None
    trace: bool = True

    def permits(self, permission: ToolPermission) -> bool:
        return permission in self.granted_permissions


class ToolExecutionReport(BaseModel):
    """Outcome of a single tool execution, used for observability."""

    tool_id: str
    capability: str = ""
    action: str = ""
    status: str = "ok"
    started_at: str = ""
    duration_ms: float = 0.0
    retries: int = 0
    error: Optional[str] = None
    output: Any = None
