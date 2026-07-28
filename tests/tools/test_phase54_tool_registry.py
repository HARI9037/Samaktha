"""Phase 5.4 tests — Tool Registry additions.

Validates:
- Tool registration
- Capability lookup alias validation
- Dependency validation (missing tools)
"""
import pytest
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry


class DummyTool(Tool):
    @property
    def name(self) -> str:
        return "dummy_tool"

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data={})


def test_registry_find_tools_by_capability():
    registry = ToolRegistry()
    tool = DummyTool()
    
    info1 = ToolInfo(tool_id="tool1", description="desc", capabilities=["sys.read", "sys.write"])
    info2 = ToolInfo(tool_id="tool2", description="desc", capabilities=["sys.read"])
    
    registry.register("tool1", tool, info1)
    registry.register("tool2", tool, info2)
    
    sys_read_tools = registry.find_tools_by_capability("sys.read")
    assert len(sys_read_tools) == 2
    
    sys_write_tools = registry.find_tools_by_capability("sys.write")
    assert len(sys_write_tools) == 1
    assert sys_write_tools[0].tool_id == "tool1"


def test_registry_validate_dependencies():
    registry = ToolRegistry()
    tool = DummyTool()
    info = ToolInfo(tool_id="dummy_tool", description="desc", capabilities=[])
    
    registry.register("dummy_tool", tool, info)
    
    # Validates existing tool
    assert registry.validate_dependencies(["dummy_tool"]) is True
    
    # Rejects missing tool
    assert registry.validate_dependencies(["dummy_tool", "missing_tool"]) is False
    assert registry.validate_dependencies(["missing_tool"]) is False
