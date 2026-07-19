from app.tools import ToolInfo, ToolManager, ToolRegistry


def test_tool_capability_discovery_and_validation():
    registry = ToolRegistry()
    registry.register(
        "search", object(),
        ToolInfo(tool_id="search", description="Search", capabilities=["read", "search"]),
    )
    manager = ToolManager(registry)

    assert [item.tool_id for item in manager.list_tools_by_capability("search")] == ["search"]
    assert manager.validate_tool_capabilities("search", ["read"])
    assert not manager.validate_tool_capabilities("search", ["write"])
