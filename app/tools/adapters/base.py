"""External adapter architecture.

Every external capability (Google Workspace, GitHub, Slack, …) is
exposed to the ecosystem through an ``ExternalAdapter``, wrapped by
``ExternalTool`` so CAP governs it, GAMBIT selects it and the
dispatcher executes it — exactly like any built-in tool.

The adapters provided in this package are INTERFACE-ONLY: they declare
capabilities, categories, operations and health checks, but perform no
network I/O and hold no credentials. Real integrations subclass
``ExternalAdapter`` and supply a concrete ``run_operation``.

Adapter configuration and connections are owned by the adapter; the
ecosystem never stores or transmits tokens, passwords or secrets.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.errors import ToolUnavailableError
from app.tools.framework.models import ToolPolicy

logger = logging.getLogger(__name__)


class ExternalAdapter(ABC):
    """Base class for third-party integrations."""

    provider_id: ClassVar[str] = ""
    provider_name: ClassVar[str] = ""
    category: ClassVar[ToolCategory] = ToolCategory.CUSTOM
    capabilities: ClassVar[tuple[ToolCapability | str, ...]] = ()
    policy: ClassVar[ToolPolicy | None] = None
    operations: ClassVar[dict[str, str]] = {}

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.connected = False

    @abstractmethod
    async def connect(self) -> bool:
        """Establish the integration. Must not store secrets."""

    async def disconnect(self) -> None:
        self.connected = False

    @abstractmethod
    async def run_operation(self, operation: str, parameters: dict[str, Any]) -> Any:
        """Perform a single operation against the external service."""

    async def health_check(self) -> bool:
        return self.connected


class ExternalTool(Tool):
    """Adapter for an ExternalAdapter so it behaves like any tool."""

    name: ClassVar[str] = ""

    def __init__(self, adapter: ExternalAdapter) -> None:
        self.adapter = adapter
        self._name = adapter.provider_id or type(adapter).__name__.lower()

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> tuple[Any, ...]:
        return self.adapter.capabilities

    @property
    def category(self) -> ToolCategory:
        return self.adapter.category

    @property
    def policy(self) -> ToolPolicy:
        return self.adapter.policy or ToolPolicy()

    @property
    def operations(self) -> dict[str, str]:
        return self.adapter.operations

    async def health_check(self) -> bool:
        return await self.adapter.health_check()

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.adapter.connected:
            return ToolResult(
                ok=False,
                error=f"Adapter '{self._name}' is not connected; interface-only adapter",
            )
        operation = arguments.get("action") or arguments.get("operation") or "run"
        parameters = {
            key: value
            for key, value in arguments.items()
            if key not in ("action", "operation")
        }
        try:
            output = await self.adapter.run_operation(operation, parameters)
        except ToolUnavailableError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Adapter '%s' operation '%s' failed", self._name, operation)
            return ToolResult(ok=False, error=f"Adapter '{self._name}' failed: {exc}")
        return ToolResult(ok=True, data={"output": output})


class AdaptersCatalog:
    """Registry of available adapter classes (interfaces only).

    Adapters are never constructed without configuration; the catalog
    only knows how to build an ``ExternalTool`` from a provider id once
    a concrete, configured adapter class is provided.
    """

    def __init__(self, adapters: dict[str, type[ExternalAdapter]] | None = None) -> None:
        self._adapters: dict[str, type[ExternalAdapter]] = dict(adapters or {})

    def register(self, adapter_cls: type[ExternalAdapter]) -> None:
        self._adapters[adapter_cls.provider_id] = adapter_cls

    def available(self) -> list[str]:
        return sorted(self._adapters)

    def tool_for(
        self, provider_id: str, config: dict[str, Any] | None = None
    ) -> ExternalTool | None:
        adapter_cls = self._adapters.get(provider_id)
        if adapter_cls is None:
            return None
        return ExternalTool(adapter_cls(config))
