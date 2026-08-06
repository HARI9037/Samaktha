"""Tool framework for Samaktha.

Provides the shared contracts used across the tool ecosystem:
categories, permissions, capabilities, policies, contexts, health,
discovery, validation, dispatching, memory and diagnostics.

Nothing in this package depends on app-specific orchestration logic;
CAP governs policy, GAMBIT performs selection, and the dispatcher
executes tools obtained from the registry.
"""

from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.diagnostics import ToolDiagnostics
from app.tools.framework.dispatcher import ToolCall, ToolDispatcher
from app.tools.framework.errors import (
    ToolCancelledError,
    ToolDependencyError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolUnavailableError,
    ToolValidationError,
)
from app.tools.framework.health import ToolHealth, ToolHealthMonitor, ToolStatus
from app.tools.framework.memory import ToolMemoryStore, ToolUsageRecord
from app.tools.framework.models import (
    ToolContext,
    ToolExecutionReport,
    ToolPermission,
    ToolPolicy,
)
from app.tools.framework.selector import ToolSelector
from app.tools.framework.validator import ToolValidator

__all__ = [
    "ToolCapability",
    "ToolCategory",
    "ToolCall",
    "ToolContext",
    "ToolDependencyError",
    "ToolDiagnostics",
    "ToolDispatcher",
    "ToolError",
    "ToolExecutionError",
    "ToolExecutionReport",
    "ToolHealth",
    "ToolHealthMonitor",
    "ToolMemoryStore",
    "ToolNotFoundError",
    "ToolPermission",
    "ToolPermissionError",
    "ToolPolicy",
    "ToolSelector",
    "ToolStatus",
    "ToolTimeoutError",
    "ToolUnavailableError",
    "ToolUsageRecord",
    "ToolValidationError",
    "ToolValidator",
    "ToolCancelledError",
]
