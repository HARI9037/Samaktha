from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from app.core.contracts.streaming import StreamChunk, StreamRequest

from app.core.contracts.policy import ExecutionConstraints


class ProviderLike(Protocol):
    """Provider shape required by Runtime without importing provider modules."""

    @property
    def name(self) -> str:
        ...

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class ProviderManagerLike(Protocol):
    """Provider manager shape required by Runtime."""

    def resolve_provider(self, provider_id: str) -> ProviderLike | None:
        ...

    async def execute_provider(
        self,
        provider_id: str,
        payload: dict[str, Any],
        model_id: str | None = None,
        required_capabilities: list[str] | None = None,
        execution_constraints: ExecutionConstraints | None = None,
    ) -> dict[str, Any]:
        ...

    def stream_provider(
        self,
        request: StreamRequest,
    ) -> AsyncIterator[StreamChunk]:
        ...


class ToolLike(Protocol):
    """Tool shape required by Runtime without importing tool modules."""

    @property
    def name(self) -> str:
        ...

    async def run(self, arguments: dict[str, Any]) -> Any:
        ...


class ToolResultLike(Protocol):
    @property
    def ok(self) -> bool:
        ...

    @property
    def data(self) -> dict[str, Any]:
        ...

    @property
    def error(self) -> str | None:
        ...


class ToolManagerLike(Protocol):
    """Tool manager shape required by Runtime."""

    def resolve_tool(self, tool_id: str) -> ToolLike | None:
        ...

    async def execute_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> ToolResultLike:
        ...
