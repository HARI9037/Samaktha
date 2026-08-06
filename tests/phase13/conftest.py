"""Shared fixtures for Phase 13 tool ecosystem tests."""

import asyncio

import pytest

from app.tools.base import Tool, ToolResult
from app.tools.framework import (
    ToolCapability,
    ToolCategory,
    ToolPermission,
    ToolPolicy,
)


def run_async(coro):
    """Run a coroutine synchronously (no pytest-asyncio dependency)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class EchoTool(Tool):
    name = "echo"

    input_schema = {"message": {"type": "string", "required": True, "max_length": 100}}

    policy = ToolPolicy(
        permissions=(ToolPermission.READ,),
        default_timeout_s=5.0,
        description="Echo a message.",
    )

    capabilities = (ToolCapability.CUSTOM, "echo")

    category = ToolCategory.CUSTOM

    async def run(self, arguments):
        return ToolResult(ok=True, data={"echo": arguments.get("message")})


class FailingTool(Tool):
    name = "failing"

    async def run(self, arguments):
        return ToolResult(ok=False, error="boom")


class SlowTool(Tool):
    name = "slow"

    policy = ToolPolicy(
        permissions=(ToolPermission.EXECUTE,),
        default_timeout_s=0.1,
        max_retries=2,
        retry_backoff_s=0.01,
        description="Always times out.",
    )

    async def run(self, arguments):
        await asyncio.sleep(5)
        return ToolResult(ok=True)


class UnavailableTool(Tool):
    name = "unavailable"

    async def health_check(self) -> bool:
        return False

    async def run(self, arguments):
        return ToolResult(ok=True, data={"unavailable": True})


class TrackingTool(Tool):
    """Echo tool that records every invocation order via a shared list."""

    name = "tracking"

    def __init__(self, order_log):
        self._order_log = order_log

    async def run(self, arguments):
        self._order_log.append(arguments.get("tag"))
        return ToolResult(ok=True, data={"tag": arguments.get("tag")})


def make_registry(registry):
    """Register the standard fake tools into a ToolRegistry."""
    from app.tools.models import ToolInfo

    registry.register(
        "echo",
        EchoTool(),
        ToolInfo(
            tool_id="echo",
            description="Echo a message",
            capabilities=["echo", "custom"],
            input_schema=EchoTool.input_schema,
            category="custom",
            permissions=["read"],
            policy=EchoTool.policy,
        ),
    )
    registry.register(
        "failing",
        FailingTool(),
        ToolInfo(tool_id="failing", description="Always fails", capabilities=["fail"]),
    )
    registry.register(
        "slow",
        SlowTool(),
        ToolInfo(
            tool_id="slow",
            description="Times out",
            capabilities=["slow"],
            policy=SlowTool.policy,
            permissions=["execute"],
        ),
    )
    registry.register(
        "unavailable",
        UnavailableTool(),
        ToolInfo(tool_id="unavailable", description="Unavailable", capabilities=["unavailable"]),
    )
    return registry


@pytest.fixture
def tool_registry():
    from app.tools.registry import ToolRegistry

    return make_registry(ToolRegistry())
