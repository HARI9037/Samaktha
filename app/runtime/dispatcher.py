from __future__ import annotations

from app.runtime.executor import Executor
from app.runtime.registry import RuntimeRegistry


class RuntimeDispatcher:
    """Selects a runtime executor for a task action type."""

    def __init__(
        self,
        registry: RuntimeRegistry,
        action_executor_map: dict[str, str] | None = None,
    ) -> None:
        self._registry = registry
        self._action_executor_map = {
            "text_generation": "provider",
            "provider": "provider",
            "tool_execution": "tool",
            "tool": "tool",
            # AI-OS tool routes — each maps to ToolExecutor
            "filesystem": "tool",
            "pdf": "tool",
            "memory": "tool",
            "windows": "tool",
            "internet": "tool",
            **(action_executor_map or {}),
        }

    def dispatch(self, action_type: str) -> Executor | None:
        normalized = self._normalize(action_type)
        executor_name = self._action_executor_map.get(normalized, normalized)
        return self._registry.get(executor_name)

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().lower().replace("-", "_").replace(" ", "_")
