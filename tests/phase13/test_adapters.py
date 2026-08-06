"""Phase 13.9 — external adapter architecture (interface-only)."""

from app.tools.adapters import ExternalTool, default_catalog
from app.tools.adapters.base import AdaptersCatalog, ExternalAdapter
from app.tools.framework.capabilities import ToolCapability, ToolCategory

from .conftest import run_async

EXPECTED_PROVIDERS = {
    "google_workspace",
    "microsoft_365",
    "github",
    "gitlab",
    "slack",
    "discord",
    "whatsapp",
    "telegram",
    "notion",
    "obsidian",
    "jira",
    "linear",
    "trello",
    "google_drive",
    "onedrive",
    "dropbox",
    "sqlite",
    "postgresql",
    "mongodb",
}


def test_catalog_has_all_required_providers():
    available = set(default_catalog().available())
    assert EXPECTED_PROVIDERS <= available


def test_catalog_exposes_tool_for_provider():
    tool = default_catalog().tool_for("github")
    assert isinstance(tool, ExternalTool)
    assert tool.name == "github"


def test_catalog_unknown_provider_returns_none():
    assert default_catalog().tool_for("definitely_not_real") is None


def test_adapters_are_interface_only_and_never_connect():
    tool = default_catalog().tool_for("github")
    assert run_async(tool.adapter.connect()) is False
    assert run_async(tool.adapter.health_check()) is False


def test_external_tool_not_connected_fails_gracefully():
    tool = default_catalog().tool_for("github")
    result = run_async(tool.run({"action": "create_issue"}))
    assert result.ok is False
    assert "not connected" in result.error


def test_github_adapter_declares_governing_policy():
    tool = default_catalog().tool_for("github")
    assert tool.policy.approval_required is True
    assert ToolCapability.GIT_PUSH in tool.adapter.capabilities
    assert tool.adapter.category == ToolCategory.DEVELOPER


def test_database_adapters_declare_query_capabilities():
    for provider in ("sqlite", "postgresql", "mongodb"):
        tool = default_catalog().tool_for(provider)
        assert tool.adapter.category == ToolCategory.DATABASE
        assert ToolCapability.DATABASE_QUERY in tool.adapter.capabilities


def test_custom_catalog_registration():
    catalog = AdaptersCatalog()

    class MyAdapter(ExternalAdapter):
        provider_id = "my_provider"
        provider_name = "My"
        capabilities = (ToolCapability.CUSTOM,)
        category = ToolCategory.CUSTOM
        operations = {"run": "do a thing"}

        async def connect(self):
            return False

        async def run_operation(self, operation, parameters):
            return {"provider": "my_provider"}

    catalog.register(MyAdapter)
    assert catalog.available() == ["my_provider"]
    tool = catalog.tool_for("my_provider")
    assert tool.name == "my_provider"


def test_concrete_adapter_executes_through_external_tool():
    from app.tools.adapters.base import AdaptersCatalog, ExternalAdapter
    from app.tools.framework import ToolCapability, ToolCategory

    class Concrete(ExternalAdapter):
        provider_id = "concrete"
        provider_name = "Concrete"
        capabilities = (ToolCapability.CUSTOM,)
        category = ToolCategory.CUSTOM

        async def connect(self):
            self.connected = True
            return True

        async def run_operation(self, operation, parameters):
            return {"echo": parameters.get("value")}

    catalog = AdaptersCatalog()
    catalog.register(Concrete)
    tool = catalog.tool_for("concrete")
    assert run_async(tool.adapter.connect()) is True
    result = run_async(tool.run({"action": "echo", "value": "hi"}))
    assert result.ok
    assert result.data["output"]["echo"] == "hi"
