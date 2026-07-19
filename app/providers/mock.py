from __future__ import annotations

from typing import Any

from app.providers.base import Provider


class MockProvider(Provider):
    """Test provider that returns a deterministic response."""

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"response": "Mock provider response"}
