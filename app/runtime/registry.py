from __future__ import annotations

from app.runtime.executor import Executor


class RuntimeRegistry:
    """In-memory registry for runtime executors."""

    def __init__(self) -> None:
        self._executors: dict[str, Executor] = {}

    def register(self, name: str, executor: Executor) -> None:
        self._executors[self._normalize(name)] = executor

    def get(self, name: str) -> Executor | None:
        return self._executors.get(self._normalize(name))

    @staticmethod
    def _normalize(name: str) -> str:
        return name.strip().lower().replace("-", "_").replace(" ", "_")
