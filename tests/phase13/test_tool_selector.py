"""Phase 13.4/13.5 — ToolSelector: data-driven capability/category selection."""

from app.tools.framework import ToolSelector
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry

from .conftest import EchoTool


def _info(tool_id, capabilities, category=None):
    return ToolInfo(
        tool_id=tool_id,
        description=tool_id,
        capabilities=capabilities,
        category=category,
    )


def _registry_with_tools():
    registry = ToolRegistry()
    registry.register("a", EchoTool(), _info("a", ["file_read", "read"], "filesystem"))
    registry.register("b", EchoTool(), _info("b", ["shell_exec", "run"], "system"))
    registry.register("c", EchoTool(), _info("c", ["notify"], "system"))
    return registry


def test_select_by_capability():
    selector = ToolSelector(_registry_with_tools())
    assert selector.select("file_read") == "a"
    assert selector.select("shell_exec") == "b"
    assert selector.select("notify") == "c"


def test_select_case_insensitive():
    selector = ToolSelector(_registry_with_tools())
    assert selector.select("FILE_READ") == "a"


def test_select_with_category_filter():
    selector = ToolSelector(_registry_with_tools())
    assert selector.select("shell_exec", category="system") == "b"
    assert selector.select("shell_exec", category="filesystem") is None


def test_select_no_match_returns_none():
    selector = ToolSelector(_registry_with_tools())
    assert selector.select("missing_capability") is None


def test_select_none_registry_returns_none():
    assert ToolSelector().select("anything") is None


def test_select_tool_id_override():
    selector = ToolSelector(_registry_with_tools())
    # Explicit tool id only counts if it declares the capability.
    assert selector.select("read", tool_id="a") == "a"
    assert selector.select("read", tool_id="b") is None


def test_prefer_hint_wins():
    """A prefer hint for a tool that declares the capability wins over the
    default first match."""
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register("a", EchoTool(), _info("a", ["file_read", "read"], "filesystem"))
    registry.register("d", EchoTool(), _info("d", ["file_read"], "filesystem"))
    selector = ToolSelector(registry)
    assert selector.select("file_read") == "a"
    selector.prefer("file_read", "d")
    assert selector.select("file_read") == "d"


def test_discovery_uses_registered_metadata_only():
    registry = ToolRegistry()
    selector = ToolSelector(registry)
    assert selector.select("anything") is None
    registry.register("x", EchoTool(), _info("x", ["magic"]))
    assert selector.select("magic") == "x"
