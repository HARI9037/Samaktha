"""P2.1 — Plugin Architecture regression tests.

Covers the Plugin specification: manifest, identity, metadata, lifecycle,
discovery, registry, loading/unloading, dependency resolution, capability
and permission declarations, isolation boundaries and validation.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from app.plugins import (
    DependencyResolutionError,
    Plugin,
    PluginIsolationError,
    PluginKind,
    PluginLoadError,
    PluginManager,
    PluginManifest,
    PluginRegistrationError,
    PluginState,
    PluginUnloadError,
    SemanticVersion,
    VersionError,
    resolve_dependencies,
    resolve_load_order,
    validate_manifest,
)
from app.plugins.discovery import DiscoveryError, PluginDiscovery
from app.plugins.registry import PluginRegistry
from app.plugins.validation import validate_plugin
from app.tools.capability_registry import CapabilityEntry, CapabilityRegistry
from app.tools.registry import ToolRegistry


def _tool_plugin_source(
    plugin_id: str,
    module: str,
    tool_name: str,
    capabilities: tuple[str, ...],
    permissions: tuple[str, ...],
    manifest_capabilities: tuple[str, ...],
    manifest_permissions: tuple[str, ...],
    manifest_id: str | None = None,
    version: str = "1.0.0",
    deps: tuple[str, ...] = (),
) -> str:
    caps_decl = ", ".join(
        f'{{"name": "{c}", "description": "auto"}}' for c in manifest_capabilities
    )
    perms_decl = ", ".join(
        f'{{"scope": "{p}"}}' for p in manifest_permissions
    )
    caps_expr = ", ".join(f'"{c}"' for c in capabilities)
    perms_expr = ", ".join(f"ToolPermission.{p.upper()}" for p in permissions)
    deps_decl = ", ".join(
        f"PluginDependency(plugin_id={d!r})" for d in deps
    )
    return f'''
from app.plugins import Plugin
from app.plugins.models import PluginManifest, PluginDependency
from app.tools.base import Tool, ToolResult
from app.tools.framework.models import ToolPermission, ToolPolicy
from app.tools.framework.capabilities import ToolCategory

class {tool_name.upper()}Tool(Tool):
    name = {tool_name!r}
    category = ToolCategory.PRODUCTIVITY
    capabilities = [{caps_expr}]
    policy = ToolPolicy(permissions=({perms_expr},), description="plugin tool")

    async def run(self, arguments):
        return ToolResult(ok=True, data={{"value": arguments.get("value", "")}})

MANIFEST = PluginManifest(
    id={manifest_id or plugin_id!r}, name={plugin_id + " plugin"!r},
    version={version!r}, kind="tool", entry={module!r},
    capabilities=[{caps_decl}],
    permissions=[{perms_decl}],
    dependencies=[{deps_decl}],
)

class SamplePlugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_tools(self):
        return [{tool_name.upper()}Tool()]

def create_plugin():
    return SamplePlugin()
'''


def _provider_plugin_source(
    plugin_id: str, module: str, provider_name: str
) -> str:
    return f'''
from app.plugins import Plugin
from app.plugins.models import PluginManifest
from app.communication.models import (
    CommunicationProvider as CommunicationProviderEnum,
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)
from app.communication.provider import CommunicationProvider

class {provider_name.upper()}Provider(CommunicationProvider):
    provider_id = {provider_name!r}

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def send(self, request):
        return CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProviderEnum.TEST,
        )

    async def receive(self, limit=10):
        return []

    async def health(self):
        return True

    async def validate(self, request):
        return []

MANIFEST = PluginManifest(
    id={plugin_id!r}, name={plugin_id + " plugin"!r}, version="1.0.0",
    kind="provider", entry={module!r},
)

class SamplePlugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_providers(self):
        return [{provider_name.upper()}Provider()]

def create_plugin():
    return SamplePlugin()
'''


def _write_tool_plugin(
    root: Path,
    plugin_id: str,
    *,
    module: str | None = None,
    tool_name: str | None = None,
    capabilities: tuple[str, ...] = ("echo",),
    permissions: tuple[str, ...] = ("read",),
    manifest_capabilities: tuple[str, ...] | None = None,
    manifest_permissions: tuple[str, ...] | None = None,
    deps: tuple[str, ...] = (),
    version: str = "1.0.0",
    manifest_id: str | None = None,
) -> Path:
    module = module or f"p20_{plugin_id}"
    tool_name = tool_name or f"tool_{plugin_id}"
    manifest_capabilities = (
        capabilities if manifest_capabilities is None else manifest_capabilities
    )
    manifest_permissions = (
        permissions if manifest_permissions is None else manifest_permissions
    )
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "id": manifest_id or plugin_id,
        "name": f"{plugin_id} plugin",
        "version": version,
        "kind": "tool",
        "entry": module,
        "capabilities": [{"name": c, "description": "auto"} for c in manifest_capabilities],
        "permissions": [{"scope": p} for p in manifest_permissions],
        "dependencies": [{"plugin_id": d} for d in deps],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    source = _tool_plugin_source(
        plugin_id, module, tool_name, capabilities, permissions,
        manifest_capabilities, manifest_permissions, manifest_id, version, deps,
    )
    (root / f"{module}.py").write_text(source, encoding="utf-8")
    return plugin_dir


def _write_provider_plugin(
    root: Path, plugin_id: str, *, provider_name: str | None = None
) -> Path:
    module = f"p20_{plugin_id}"
    provider_name = provider_name or f"probe_{plugin_id}"
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "id": plugin_id,
        "name": f"{plugin_id} plugin",
        "version": "1.0.0",
        "kind": "provider",
        "entry": module,
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / f"{module}.py").write_text(
        _provider_plugin_source(plugin_id, module, provider_name), encoding="utf-8"
    )
    return plugin_dir


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """Plugin source directory on sys.path with module-cache cleanup."""
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for name in [n for n in sys.modules if n.startswith("p20_")]:
        del sys.modules[name]


def _make_manager() -> PluginManager:
    from app.communication.registry import CommunicationRegistry

    return PluginManager(
        tool_registry=ToolRegistry(),
        communication_registry=CommunicationRegistry(),
        capability_registry=CapabilityRegistry(),
    )


# ----------------------------------------------------------------------
# Models: identity, metadata, manifest
# ----------------------------------------------------------------------


def test_manifest_key_and_identity() -> None:
    from app.plugins.models import PluginIdentity

    manifest = PluginManifest(id="alpha", name="Alpha", version="1.2.3", entry="p20_alpha")
    assert manifest.key == "alpha@1.2.3"
    identity = manifest.identity
    assert identity.key == "alpha@1.2.3"
    assert identity.plugin_id == "alpha"
    assert PluginIdentity.from_manifest(manifest).key == "alpha@1.2.3"


def test_metadata_snapshot() -> None:
    from app.plugins.models import PluginRecord

    manifest = PluginManifest(
        id="alpha",
        name="Alpha",
        version="1.0.0",
        entry="p20_alpha",
        capabilities=[{"name": "echo"}],
        permissions=[{"scope": "read"}],
        dependencies=[{"plugin_id": "base"}],
    )
    record = PluginRecord(manifest=manifest, state=PluginState.LOADED)
    snapshot = record.metadata_snapshot
    assert snapshot.state == PluginState.LOADED
    assert snapshot.capabilities == ["echo"]
    assert snapshot.permissions == ["read"]
    assert snapshot.dependencies == ["base@*"]
    assert snapshot.entry == "p20_alpha"


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


def test_valid_manifest_passes() -> None:
    manifest = PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha")
    result = validate_manifest(manifest)
    assert result.valid
    assert not result.errors


def test_invalid_id_format_fails() -> None:
    manifest = PluginManifest(id="Not Valid!", name="Alpha", version="1.0.0", entry="p20_alpha")
    assert not validate_manifest(manifest).valid


def test_invalid_version_fails() -> None:
    manifest = PluginManifest(id="alpha", name="Alpha", version="v1", entry="p20_alpha")
    assert not validate_manifest(manifest).valid


def test_unknown_permission_scope_fails() -> None:
    manifest = PluginManifest(
        id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha",
        permissions=[{"scope": "root"}],
    )
    result = validate_manifest(manifest)
    assert not result.valid
    assert any("Unknown permission scope" in e for e in result.errors)


def test_duplicate_capabilities_fail() -> None:
    manifest = PluginManifest(
        id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha",
        capabilities=[{"name": "echo"}, {"name": "echo"}],
    )
    assert not validate_manifest(manifest).valid


def test_duplicate_dependency_fails() -> None:
    manifest = PluginManifest(
        id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha",
        dependencies=[{"plugin_id": "base"}, {"plugin_id": "base"}],
    )
    assert not validate_manifest(manifest).valid


def test_invalid_entry_module_path_fails() -> None:
    manifest = PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20 alpha.main")
    assert not validate_manifest(manifest).valid


def test_invalid_dependency_constraint_fails() -> None:
    manifest = PluginManifest(
        id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha",
        dependencies=[{"plugin_id": "base", "version": "banana"}],
    )
    assert not validate_manifest(manifest).valid


# ----------------------------------------------------------------------
# Semantic versioning
# ----------------------------------------------------------------------


def test_semver_parse_and_ordering() -> None:
    v = SemanticVersion.parse("1.2.3")
    assert (v.major, v.minor, v.patch) == (1, 2, 3)
    assert SemanticVersion.parse("2.0.0") > v
    assert SemanticVersion.parse("1.2.3+build") == v
    with pytest.raises(VersionError):
        SemanticVersion.parse("1.2")


@pytest.mark.parametrize(
    ("constraint", "expected"),
    [
        ("*", True),
        ("", True),
        ("1.2.3", True),
        ("1.2.4", False),
        (">=1.2.0", True),
        (">=2.0.0", False),
        ("^1.2.0", True),
        ("^2.0.0", False),
        ("~1.2.0", True),
        ("~1.3.0", False),
        ("<=1.2.3", True),
        ("<1.2.3", False),
    ],
)
def test_semver_constraints(constraint: str, expected: bool) -> None:
    version = SemanticVersion.parse("1.2.3")
    assert version.satisfies(constraint) is expected


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def test_discover_root_and_subdir_manifests(plugin_env: Path) -> None:
    (plugin_env / "one.plugin.json").write_text(
        json.dumps({"id": "one", "name": "One", "version": "1.0.0", "entry": "p20_one"}),
        encoding="utf-8",
    )
    _write_tool_plugin(plugin_env, "two")
    discovered = PluginDiscovery().discover(plugin_env)
    keys = {m.key for m in discovered}
    assert {"one@1.0.0", "two@1.0.0"} <= keys


def test_discover_skips_invalid_and_deduplicates(plugin_env: Path) -> None:
    (plugin_env / "bad.plugin.json").write_text("{not json", encoding="utf-8")
    _write_tool_plugin(plugin_env, "dup", version="1.0.0")
    _write_tool_plugin(plugin_env, "dup_again", version="1.0.0", manifest_id="dup")
    discovered = PluginDiscovery().discover(plugin_env)
    keys = [m.key for m in discovered]
    assert keys.count("dup@1.0.0") == 1


def test_discover_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryError):
        PluginDiscovery().discover(tmp_path / "nope")


def test_discover_deterministic_order(plugin_env: Path) -> None:
    for name in ("beta", "alpha", "gamma"):
        _write_tool_plugin(plugin_env, name)
    discovered = PluginDiscovery().discover(plugin_env)
    assert [m.id for m in discovered] == ["alpha", "beta", "gamma"]


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


def test_register_and_duplicate_rejection() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha")
    registry.register(manifest)
    assert registry.has("alpha@1.0.0")
    with pytest.raises(PluginRegistrationError):
        registry.register(manifest)


def test_registry_get_by_id_prefers_highest_version() -> None:
    registry = PluginRegistry()
    registry.register(PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20_a1"))
    registry.register(PluginManifest(id="alpha", name="Alpha", version="2.0.0", entry="p20_a2"))
    assert registry.get_by_id("alpha").key == "alpha@2.0.0"
    assert len(registry.list()) == 2


def test_registry_state_updates() -> None:
    registry = PluginRegistry()
    registry.register(PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha"))
    registry.update_state("alpha@1.0.0", PluginState.LOADING)
    registry.record_error("alpha@1.0.0", "boom")
    record = registry.get("alpha@1.0.0")
    assert record.state == PluginState.LOADING
    assert record.error == "boom"
    assert registry.list_by_kind(PluginKind.TOOL)[0].key == "alpha@1.0.0"


# ----------------------------------------------------------------------
# Dependency resolution
# ----------------------------------------------------------------------


def _records(*ids: str) -> list:
    registry = PluginRegistry()
    for item in ids:
        if isinstance(item, tuple):
            plugin_id, version, deps = item
        else:
            plugin_id, version, deps = item, "1.0.0", ()
        registry.register(
            PluginManifest(
                id=plugin_id,
                name=plugin_id,
                version=version,
                entry=f"p20_{plugin_id}",
                dependencies=[{"plugin_id": d} for d in deps],
            )
        )
    return registry.list()


def test_resolve_load_order_dependencies_first() -> None:
    records = _records("a", ("b", "1.0.0", ("a",)), ("c", "1.0.0", ("b",)))
    order = resolve_load_order(records)
    assert order.index("a@1.0.0") < order.index("b@1.0.0") < order.index("c@1.0.0")
    assert order == ["a@1.0.0", "b@1.0.0", "c@1.0.0"]


def test_missing_dependency_error() -> None:
    records = _records(("b", "1.0.0", ("a",)))
    with pytest.raises(DependencyResolutionError) as excinfo:
        resolve_load_order(records)
    assert "a" in str(excinfo.value)


def test_version_constraint_satisfaction_and_mismatch() -> None:
    records = _records(("a", "1.2.3", ()))
    satisfying = [
        ("b1", "1.0.0", ("a",)),
        ("b2", "1.0.0", ("a",)),
    ]
    b1 = PluginManifest(
        id="b1", name="b1", version="1.0.0", entry="p20_b1",
        dependencies=[{"plugin_id": "a", "version": "^1.0.0"}],
    )
    b2 = PluginManifest(
        id="b2", name="b2", version="1.0.0", entry="p20_b2",
        dependencies=[{"plugin_id": "a", "version": ">=2.0.0"}],
    )
    registry = PluginRegistry()
    registry.register(records[0].manifest)
    registry.register(b1)
    registry.register(b2)
    with pytest.raises(DependencyResolutionError) as excinfo:
        resolve_load_order(registry.list())
    assert "b2" in str(excinfo.value)


def test_circular_dependency_error() -> None:
    records = _records(("a", "1.0.0", ("b",)), ("b", "1.0.0", ("a",)))
    with pytest.raises(DependencyResolutionError) as excinfo:
        resolve_load_order(records)
    assert "Circular" in str(excinfo.value)


def test_prefer_loaded_version() -> None:
    registry = PluginRegistry()
    registry.register(PluginManifest(id="a", name="a", version="1.0.0", entry="p20_a1"))
    registry.register(PluginManifest(id="a", name="a", version="2.0.0", entry="p20_a2"))
    registry.register(
        PluginManifest(
            id="b", name="b", version="1.0.0", entry="p20_b",
            dependencies=[{"plugin_id": "a"}],
        )
    )
    loaded = resolve_dependencies(registry.list(), "b@1.0.0", prefer_loaded=["a@1.0.0"])
    assert loaded == ["a@1.0.0"]


def test_resolve_dependencies_transitive_closure() -> None:
    records = _records("a", ("b", "1.0.0", ("a",)), ("c", "1.0.0", ("b",)), "orphan")
    loaded = resolve_dependencies(records, "c@1.0.0")
    assert loaded == ["a@1.0.0", "b@1.0.0"]
    assert "orphan@1.0.0" not in loaded


# ----------------------------------------------------------------------
# PluginManager: loading
# ----------------------------------------------------------------------


async def test_manager_load_registers_contributions(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)

    record = await manager.load("alpha@1.0.0")

    assert record.state == PluginState.ACTIVE
    assert manager.get("alpha@1.0.0").state == PluginState.ACTIVE
    assert "tool:tool_alpha" in record.contributions
    assert "capability:echo" in record.contributions
    assert manager._tool_registry.has_tool("tool_alpha")
    assert manager._capability_registry.is_installed("echo")
    info = manager._tool_registry.info_for("tool_alpha")
    assert info.metadata["plugin_id"] == "alpha"
    assert info.capabilities == ["echo"]
    assert info.permissions == ["read"]


async def test_manager_auto_loads_dependencies(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "base", capabilities=("base_op",))
    _write_tool_plugin(plugin_env, "consumer", deps=("base",), tool_name="consumer_tool")
    manager = _make_manager()
    manager.discover(plugin_env)

    await manager.load("consumer@1.0.0")

    assert manager.get("base@1.0.0").state == PluginState.ACTIVE
    assert manager.get("consumer@1.0.0").state == PluginState.ACTIVE
    assert manager.is_loaded("base@1.0.0")


async def test_manager_load_fails_when_dependency_missing(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "consumer", deps=("missing",), tool_name="consumer_tool")
    manager = _make_manager()
    manager.discover(plugin_env)
    with pytest.raises(PluginLoadError):
        await manager.load("consumer@1.0.0")
    assert manager.get("consumer@1.0.0").state == PluginState.FAILED


async def test_manager_load_fails_without_plugin_symbol(plugin_env: Path) -> None:
    plugin_dir = plugin_env / "empty"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"id": "empty", "name": "Empty", "version": "1.0.0", "entry": "p20_empty"}),
        encoding="utf-8",
    )
    (plugin_env / "p20_empty.py").write_text("VALUE = 42\n", encoding="utf-8")
    manager = _make_manager()
    manager.discover(plugin_env)
    with pytest.raises(PluginLoadError) as excinfo:
        await manager.load("empty@1.0.0")
    assert "create_plugin" in str(excinfo.value)


async def test_manager_load_fails_on_identity_mismatch(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha", manifest_id="impostor")
    manager = _make_manager()
    manager.discover(plugin_env)
    with pytest.raises(PluginLoadError):
        await manager.load("alpha@1.0.0")


async def test_manager_refuses_undeclared_permission(plugin_env: Path) -> None:
    _write_tool_plugin(
        plugin_env, "alpha",
        permissions=("write",),
        manifest_permissions=("read",),
    )
    manager = _make_manager()
    manager.discover(plugin_env)
    with pytest.raises(PluginIsolationError) as excinfo:
        await manager.load("alpha@1.0.0")
    assert "undeclared permission" in str(excinfo.value)


async def test_manager_refuses_undeclared_capability(plugin_env: Path) -> None:
    _write_tool_plugin(
        plugin_env, "alpha",
        capabilities=("echo", "secret_op"),
        manifest_capabilities=("echo",),
    )
    manager = _make_manager()
    manager.discover(plugin_env)
    with pytest.raises(PluginIsolationError) as excinfo:
        await manager.load("alpha@1.0.0")
    assert "undeclared capability" in str(excinfo.value)


async def test_manager_refuses_tool_id_collision(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "one", tool_name="clash")
    _write_tool_plugin(plugin_env, "two", tool_name="clash")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("one@1.0.0")
    with pytest.raises(PluginLoadError) as excinfo:
        await manager.load("two@1.0.0")
    assert "already registered" in str(excinfo.value)


async def test_manager_provider_plugin_registers_provider(plugin_env: Path) -> None:
    _write_provider_plugin(plugin_env, "probe", provider_name="probe_chan")
    manager = _make_manager()
    manager.discover(plugin_env)
    record = await manager.load("probe@1.0.0")
    assert "provider:probe_chan" in record.contributions
    assert manager._communication_registry.has_provider("probe_chan")


# ----------------------------------------------------------------------
# PluginManager: unloading, reload, lifecycle
# ----------------------------------------------------------------------


async def test_manager_unload_removes_contributions(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    record = await manager.unload("alpha@1.0.0")

    assert record.state == PluginState.UNLOADED
    assert not manager._tool_registry.has_tool("tool_alpha")
    assert not manager._capability_registry.is_installed("echo")
    assert record.plugin is None


async def test_manager_unload_blocked_by_loaded_dependent(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "base", capabilities=("base_op",))
    _write_tool_plugin(plugin_env, "consumer", deps=("base",), tool_name="consumer_tool")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("consumer@1.0.0")

    with pytest.raises(PluginUnloadError):
        await manager.unload("base@1.0.0")

    await manager.unload("consumer@1.0.0")
    record = await manager.unload("base@1.0.0")
    assert record.state == PluginState.UNLOADED


async def test_manager_reload(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    record = await manager.reload("alpha@1.0.0")

    assert record.state == PluginState.ACTIVE
    assert manager._tool_registry.has_tool("tool_alpha")


async def test_manager_deactivate_activate(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    deactivated = await manager.deactivate("alpha@1.0.0")
    assert deactivated.state == PluginState.LOADED
    assert manager._tool_registry.has_tool("tool_alpha")

    activated = await manager.activate("alpha@1.0.0")
    assert activated.state == PluginState.ACTIVE


# ----------------------------------------------------------------------
# End-to-end and capability registry additions
# ----------------------------------------------------------------------


async def test_manager_end_to_end_discover_register_load(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "base", capabilities=("base_op",))
    _write_tool_plugin(plugin_env, "consumer", deps=("base",), tool_name="consumer_tool")
    (plugin_env / "invalid").mkdir()
    (plugin_env / "invalid" / "manifest.json").write_text(
        json.dumps({"id": "Bad!", "name": "Bad", "version": "1.0.0", "entry": "p20_bad"}),
        encoding="utf-8",
    )
    manager = _make_manager()
    discovered = manager.discover(plugin_env)
    assert len(discovered) == 2
    assert not manager.get("bad@1.0.0")

    await manager.load("consumer@1.0.0")
    assert manager._tool_registry.has_tool("consumer_tool")
    assert manager._tool_registry.has_tool("tool_base")


def test_capability_registry_register_api() -> None:
    registry = CapabilityRegistry()
    registry.register(CapabilityEntry(domain="custom_domain", tool_id="plugin_tool"))
    assert registry.is_installed("custom_domain")
    assert registry.tool_for("custom_domain") == "plugin_tool"
    with pytest.raises(ValueError):
        registry.register(CapabilityEntry(domain="custom_domain", tool_id="other"))
    assert registry.unregister_domain("custom_domain") is True
    assert registry.unregister_domain("custom_domain") is False
    assert not registry.is_installed("custom_domain")


# ----------------------------------------------------------------------
# Structural plugin validation
# ----------------------------------------------------------------------


def test_validate_plugin_rejects_non_tool_contribution() -> None:
    manifest = PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha")

    class BadPlugin(Plugin):
        @property
        def manifest(self):
            return manifest

        def provide_tools(self):
            return ["not-a-tool"]

    result = validate_plugin(BadPlugin(), manifest)
    assert not result.valid
    assert any("Tool instance" in e for e in result.errors)


def test_validate_plugin_rejects_duplicate_tool_names() -> None:
    from app.tools.base import Tool, ToolResult

    class DupTool(Tool):
        name = "dup"

        async def run(self, arguments):
            return ToolResult(ok=True)

    manifest = PluginManifest(id="alpha", name="Alpha", version="1.0.0", entry="p20_alpha")

    class DupPlugin(Plugin):
        @property
        def manifest(self):
            return manifest

        def provide_tools(self):
            return [DupTool(), DupTool()]

    result = validate_plugin(DupPlugin(), manifest)
    assert not result.valid
    assert any("unique" in e for e in result.errors)
