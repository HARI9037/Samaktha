"""Phase 13.4 — registry discovery: dynamic registration, capability /
category / version lookups, availability and health surfacing."""

from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry

from .conftest import EchoTool


def _base_info(tool_id="echo", category="custom", version="1.0.0"):
    return ToolInfo(
        tool_id=tool_id,
        description=tool_id,
        capabilities=[tool_id, "custom"],
        version=version,
        category=category,
    )


def test_register_and_get():
    registry = ToolRegistry()
    registry.register("echo", EchoTool(), _base_info())
    assert registry.has_tool("echo")
    assert registry.get_tool("echo") is not None
    assert registry.info_for("echo").tool_id == "echo"
    assert registry.get_tool_and_info("echo")[0] is not None
    assert registry.get_tool_and_info("echo")[1].tool_id == "echo"
    assert registry.get_tool("missing") is None
    assert registry.info_for("missing") is None


def test_unregister_is_idempotent():
    registry = ToolRegistry()
    registry.register("echo", EchoTool(), _base_info())
    assert registry.unregister("echo") is True
    assert registry.unregister("echo") is False
    assert not registry.has_tool("echo")


def test_find_by_capability_case_insensitive():
    registry = ToolRegistry()
    registry.register(
        "echo",
        EchoTool(),
        ToolInfo(
            tool_id="echo",
            description="echo",
            capabilities=["ECHO", "Custom"],
        ),
    )
    assert len(registry.find_tools_by_capability("echo")) == 1
    assert len(registry.find_tools_by_capability("ECHO")) == 1
    assert registry.list_by_capability("custom") == registry.find_tools_by_capability("custom")
    assert registry.find_tools_by_capability("nope") == []


def test_find_by_category():
    registry = ToolRegistry()
    registry.register("a", EchoTool(), _base_info("a", category="filesystem"))
    registry.register("b", EchoTool(), _base_info("b", category="system"))
    registry.register("c", EchoTool(), _base_info("c", category="filesystem"))
    assert {i.tool_id for i in registry.find_tools_by_category("filesystem")} == {"a", "c"}
    assert {i.tool_id for i in registry.find_tools_by_category("system")} == {"b"}


def test_find_by_version():
    registry = ToolRegistry()
    registry.register("a", EchoTool(), _base_info("a", version="1.0.0"))
    registry.register("b", EchoTool(), _base_info("b", version="2.1.0"))
    assert {i.tool_id for i in registry.find_tools_by_version("1.0.0")} == {"a"}
    assert {i.tool_id for i in registry.find_tools_by_version("2.1.0")} == {"b"}
    assert registry.find_tools_by_version("9.9.9") == []


def test_availability_filtering():
    registry = ToolRegistry()
    registry.register("a", EchoTool(), _base_info("a"))
    registry.register("b", EchoTool(), _base_info("b"))
    assert {i.tool_id for i in registry.find_available_tools()} == {"a", "b"}
    assert registry.set_availability("a", False) is True
    assert {i.tool_id for i in registry.find_available_tools()} == {"b"}
    assert registry.info_for("a").available is False
    assert registry.set_availability("missing", False) is False


def test_validate_dependencies():
    registry = ToolRegistry()
    registry.register("a", EchoTool(), _base_info("a"))
    assert registry.validate_dependencies(["a"]) is True
    assert registry.validate_dependencies(["a", "missing"]) is False
