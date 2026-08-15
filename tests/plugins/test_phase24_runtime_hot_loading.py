"""P2.4 — Runtime Hot-Loading regression tests.

Covers loading plugins without a restart, safe unload with active-task
protection, transactional reload with rollback, dependency checks, state
migration across reloads, and plugin lifecycle events.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.plugins import (
    Plugin,
    PluginActivityTracker,
    PluginEventBus,
    PluginLifecycleEvent,
    PluginLoadError,
    PluginManager,
    PluginState,
    PluginUnloadError,
)
from app.tools.capability_registry import CapabilityRegistry
from app.tools.registry import ToolRegistry


def _tool_plugin_source(
    plugin_id: str,
    module: str,
    tool_name: str,
    capabilities: tuple[str, ...],
    permissions: tuple[str, ...],
    manifest_capabilities: tuple[str, ...],
    manifest_permissions: tuple[str, ...],
    deps: tuple[str, ...] = (),
) -> str:
    caps_decl = ", ".join(
        f'{{"name": "{c}", "description": "auto"}}' for c in manifest_capabilities
    )
    perms_decl = ", ".join(f'{{"scope": "{p}"}}' for p in manifest_permissions)
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
    id={plugin_id!r}, name={plugin_id + " plugin"!r}, version="1.0.0",
    kind="tool", entry={module!r},
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


def _tool_plugin_without_capabilities(
    plugin_id: str, module: str, tool_name: str
) -> str:
    """A plugin whose tool contributes no capability — used to break a reload
    after the manifest still declares one."""
    return f'''
from app.plugins import Plugin
from app.plugins.models import PluginManifest
from app.tools.base import Tool, ToolResult
from app.tools.framework.models import ToolPermission, ToolPolicy
from app.tools.framework.capabilities import ToolCategory

class {tool_name.upper()}Tool(Tool):
    name = {tool_name!r}
    category = ToolCategory.PRODUCTIVITY
    capabilities = []
    policy = ToolPolicy(permissions=(ToolPermission.READ,), description="plugin tool")

    async def run(self, arguments):
        return ToolResult(ok=True, data={{}})

MANIFEST = PluginManifest(
    id={plugin_id!r}, name={plugin_id + " plugin"!r}, version="1.0.0",
    kind="tool", entry={module!r},
    capabilities=[{{"name": "echo", "description": "auto"}}],
    permissions=[{{"scope": "read"}}],
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


def _write_tool_plugin(
    root: Path,
    plugin_id: str,
    *,
    module: str | None = None,
    tool_name: str | None = None,
    capabilities: tuple[str, ...] = ("echo",),
    permissions: tuple[str, ...] = ("read",),
    deps: tuple[str, ...] = (),
) -> Path:
    module = module or f"p24_{plugin_id}"
    tool_name = tool_name or f"tool_{plugin_id}"
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "id": plugin_id,
        "name": f"{plugin_id} plugin",
        "version": "1.0.0",
        "kind": "tool",
        "entry": module,
        "capabilities": [{"name": c, "description": "auto"} for c in capabilities],
        "permissions": [{"scope": p} for p in permissions],
        "dependencies": [{"plugin_id": d} for d in deps],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    source = _tool_plugin_source(
        plugin_id, module, tool_name, capabilities, permissions, capabilities, permissions, deps
    )
    (root / f"{module}.py").write_text(source, encoding="utf-8")
    return plugin_dir


_STATEFUL_SOURCE = '''
from app.plugins import Plugin
from app.plugins.models import PluginManifest

class StatefulPlugin(Plugin):
    def __init__(self):
        self.counter = 0
        self.snapshots = 0
        self.restores = 0

    @property
    def manifest(self):
        return MANIFEST

    def provide_tools(self):
        return []

    async def start(self, context):
        self.counter += 1

    def snapshot_state(self):
        self.snapshots += 1
        return {"counter": self.counter}

    def restore_state(self, state):
        self.restores += 1
        self.counter = state["counter"]

MANIFEST = PluginManifest(
    id="stateful", name="Stateful plugin", version="1.0.0",
    kind="tool", entry="p24_stateful",
)

def create_plugin():
    return StatefulPlugin()
'''


def _write_stateful_plugin(root: Path) -> Path:
    plugin_dir = root / "stateful"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "id": "stateful",
                "name": "Stateful plugin",
                "version": "1.0.0",
                "kind": "tool",
                "entry": "p24_stateful",
            }
        ),
        encoding="utf-8",
    )
    (root / "p24_stateful.py").write_text(_STATEFUL_SOURCE, encoding="utf-8")
    return plugin_dir


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """Plugin source directory on sys.path with module-cache cleanup."""
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for name in [n for n in sys.modules if n.startswith("p24_")]:
        del sys.modules[name]


def _make_manager(
    *,
    event_bus: PluginEventBus | None = None,
    activity: PluginActivityTracker | None = None,
) -> PluginManager:
    from app.communication.registry import CommunicationRegistry

    return PluginManager(
        tool_registry=ToolRegistry(),
        communication_registry=CommunicationRegistry(),
        capability_registry=CapabilityRegistry(),
        event_bus=event_bus,
        activity=activity,
    )


# ----------------------------------------------------------------------
# Event bus and activity tracker primitives
# ----------------------------------------------------------------------


def test_event_bus_semantics() -> None:
    bus = PluginEventBus()
    events: list[PluginLifecycleEvent] = []
    unsubscribe = bus.subscribe("active", events.append)
    bus.on("*", events.append)

    event = PluginLifecycleEvent(
        event="active", plugin_key="alpha@1.0.0", state=PluginState.ACTIVE,
        details={"contributions": ["tool:x"]},
    )
    bus.emit(event)
    assert len(events) == 2
    assert events[0] is event
    assert events[1] is event
    assert bus.listener_count("active") == 1

    unsubscribe()
    bus.emit(event)
    assert len(events) == 3
    assert bus.listener_count("active") == 0
    bus.clear()
    assert bus.listener_count("*") == 0


def test_lifecycle_event_defaults() -> None:
    event = PluginLifecycleEvent(event="loading", plugin_key="k@1", state=PluginState.LOADING)
    assert event.details == {}
    assert event.at is not None


def test_activity_tracker_semantics() -> None:
    tracker = PluginActivityTracker()
    assert not tracker.in_use("x")
    assert tracker.active_tool_ids() == set()

    tracker.begin("x")
    tracker.begin("x")
    assert tracker.in_use("x")
    assert tracker.active_tool_ids() == {"x"}

    tracker.end("x")
    assert tracker.in_use("x")
    tracker.end("x")
    assert not tracker.in_use("x")
    assert tracker.active_tool_ids() == set()

    tracker.end("never-begun")
    tracker.clear()
    assert tracker.active_tool_ids() == set()


# ----------------------------------------------------------------------
# Load plugin without restart (load_directory)
# ----------------------------------------------------------------------


async def test_load_directory_loads_new_plugins_without_restart(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha", capabilities=("alpha_op",))
    _write_tool_plugin(plugin_env, "beta", capabilities=("beta_op",))
    manager = _make_manager()

    first = await manager.load_directory(plugin_env)

    assert {r.key for r in first} == {"alpha@1.0.0", "beta@1.0.0"}
    assert manager._tool_registry.has_tool("tool_alpha")
    assert manager._tool_registry.has_tool("tool_beta")
    beta_plugin = manager.get("beta@1.0.0").plugin

    _write_tool_plugin(plugin_env, "gamma", capabilities=("gamma_op",))
    second = await manager.load_directory(plugin_env)

    assert {r.key for r in second} == {"gamma@1.0.0"}
    assert manager.get("alpha@1.0.0").state == PluginState.ACTIVE
    assert manager.get("beta@1.0.0").plugin is beta_plugin
    assert manager._tool_registry.has_tool("tool_gamma")


async def test_load_directory_skips_broken_plugins(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    broken = plugin_env / "broken"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "id": "broken",
                "name": "Broken plugin",
                "version": "1.0.0",
                "kind": "tool",
                "entry": "p24_broken",
            }
        ),
        encoding="utf-8",
    )
    (plugin_env / "p24_broken.py").write_text(
        "raise RuntimeError('boom')\n", encoding="utf-8"
    )
    manager = _make_manager()

    loaded = await manager.load_directory(plugin_env)

    assert {r.key for r in loaded} == {"alpha@1.0.0"}
    assert manager.get("broken@1.0.0").state == PluginState.FAILED
    assert manager.get("alpha@1.0.0").state == PluginState.ACTIVE


# ----------------------------------------------------------------------
# Safe unload with active-task protection
# ----------------------------------------------------------------------


async def test_unload_blocked_while_tool_in_use(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    activity = PluginActivityTracker()
    manager = _make_manager(activity=activity)
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    activity.begin("tool_alpha")
    with pytest.raises(PluginUnloadError) as excinfo:
        await manager.unload("alpha@1.0.0")
    assert "active tasks" in str(excinfo.value)
    assert manager.get("alpha@1.0.0").state == PluginState.ACTIVE
    assert manager._tool_registry.has_tool("tool_alpha")

    activity.end("tool_alpha")
    record = await manager.unload("alpha@1.0.0")
    assert record.state == PluginState.UNLOADED
    assert not manager._tool_registry.has_tool("tool_alpha")


async def test_unload_unaffected_without_activity(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    record = await manager.unload("alpha@1.0.0")

    assert record.state == PluginState.UNLOADED


async def test_reload_blocked_while_tool_in_use(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    activity = PluginActivityTracker()
    manager = _make_manager(activity=activity)
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    activity.begin("tool_alpha")
    with pytest.raises(PluginUnloadError) as excinfo:
        await manager.reload("alpha@1.0.0")
    assert "active tasks" in str(excinfo.value)
    assert manager.get("alpha@1.0.0").state == PluginState.ACTIVE
    assert manager._tool_registry.has_tool("tool_alpha")


# ----------------------------------------------------------------------
# Reload plugin
# ----------------------------------------------------------------------


async def test_reload_produces_fresh_instance(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    first = await manager.load("alpha@1.0.0")
    old_plugin = first.plugin

    record = await manager.reload("alpha@1.0.0")

    assert record.state == PluginState.ACTIVE
    assert record.plugin is not old_plugin
    assert record.contributions == ["tool:tool_alpha", "capability:echo"]
    assert manager._tool_registry.has_tool("tool_alpha")
    assert manager._capability_registry.is_installed("echo")


async def test_reload_blocked_by_loaded_dependent(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "base", capabilities=("base_op",))
    _write_tool_plugin(plugin_env, "consumer", deps=("base",), tool_name="consumer_tool")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("consumer@1.0.0")

    with pytest.raises(PluginUnloadError):
        await manager.reload("base@1.0.0")

    assert manager.is_loaded("base@1.0.0")
    assert manager.is_loaded("consumer@1.0.0")
    assert manager._tool_registry.has_tool("tool_base")


# ----------------------------------------------------------------------
# State migration
# ----------------------------------------------------------------------


async def test_state_migration_across_reload(plugin_env: Path) -> None:
    _write_stateful_plugin(plugin_env)
    manager = _make_manager()
    manager.discover(plugin_env)
    record = await manager.load("stateful@1.0.0")
    first = record.plugin
    assert first.counter == 1
    first.counter = 42

    record = await manager.reload("stateful@1.0.0")

    second = record.plugin
    assert second is not first
    assert second.counter == 42
    assert first.snapshots == 1
    assert second.restores == 1


# ----------------------------------------------------------------------
# Failure rollback
# ----------------------------------------------------------------------


async def test_failure_rollback_restores_previous_instance(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    record = await manager.load("alpha@1.0.0")
    old_plugin = record.plugin

    (plugin_env / "p24_alpha.py").write_text(
        "raise RuntimeError('boom')\n", encoding="utf-8"
    )
    sys.modules.pop("p24_alpha", None)

    with pytest.raises(PluginLoadError):
        await manager.reload("alpha@1.0.0")

    record = manager.get("alpha@1.0.0")
    assert record.state == PluginState.ACTIVE
    assert record.plugin is old_plugin
    assert record.contributions == ["tool:tool_alpha", "capability:echo"]
    assert manager._tool_registry.has_tool("tool_alpha")
    assert manager._capability_registry.is_installed("echo")


async def test_rollback_cleans_up_partial_registration(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    record = await manager.load("alpha@1.0.0")
    old_plugin = record.plugin

    (plugin_env / "p24_alpha.py").write_text(
        _tool_plugin_without_capabilities("alpha", "p24_alpha", "tool_alpha"),
        encoding="utf-8",
    )
    sys.modules.pop("p24_alpha", None)

    with pytest.raises(PluginLoadError):
        await manager.reload("alpha@1.0.0")

    record = manager.get("alpha@1.0.0")
    assert record.state == PluginState.ACTIVE
    assert record.plugin is old_plugin
    assert record.contributions == ["tool:tool_alpha", "capability:echo"]
    assert manager._tool_registry.has_tool("tool_alpha")
    assert manager._capability_registry.is_installed("echo")


async def test_rollback_failure_is_honest(plugin_env: Path, monkeypatch) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    def _poisoned(*args, **kwargs):
        raise PluginLoadError("registration exploded")

    monkeypatch.setattr(manager, "_register_contributions", _poisoned)

    with pytest.raises(PluginLoadError):
        await manager.reload("alpha@1.0.0")

    record = manager.get("alpha@1.0.0")
    assert record.state == PluginState.FAILED
    assert record.error is not None and "Rollback failed" in record.error


# ----------------------------------------------------------------------
# Plugin lifecycle events
# ----------------------------------------------------------------------


async def test_lifecycle_events_fired_in_order(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    bus = PluginEventBus()
    manager = _make_manager(event_bus=bus)
    seen: list[tuple[str, str, PluginState]] = []
    manager.on("*", lambda e: seen.append((e.event, e.plugin_key, e.state)))

    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")
    assert [e for e, _, _ in seen] == ["registered", "loading", "active"]

    seen.clear()
    await manager.deactivate("alpha@1.0.0")
    await manager.activate("alpha@1.0.0")
    assert [e for e, _, _ in seen] == ["deactivated", "activated"]

    seen.clear()
    await manager.unload("alpha@1.0.0")
    assert [e for e, _, _ in seen] == ["unloading", "unloaded"]

    seen.clear()
    await manager.load("alpha@1.0.0")
    await manager.reload("alpha@1.0.0")
    assert [e for e, _, _ in seen] == [
        "loading",
        "active",
        "reloading",
        "unloading",
        "unloaded",
        "loading",
        "active",
    ]


async def test_lifecycle_events_carry_state_and_details(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    bus = PluginEventBus()
    manager = _make_manager(event_bus=bus)
    active_events: list[PluginLifecycleEvent] = []
    bus.subscribe("active", active_events.append)

    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    assert len(active_events) == 1
    event = active_events[0]
    assert event.plugin_key == "alpha@1.0.0"
    assert event.state == PluginState.ACTIVE
    assert event.details["contributions"] == ["tool:tool_alpha", "capability:echo"]
    assert event.at is not None


async def test_reload_rollback_emits_events(plugin_env: Path) -> None:
    _write_tool_plugin(plugin_env, "alpha")
    manager = _make_manager()
    manager.discover(plugin_env)
    await manager.load("alpha@1.0.0")

    seen: list[str] = []
    manager.on("*", lambda e: seen.append(e.event))

    (plugin_env / "p24_alpha.py").write_text(
        "raise RuntimeError('boom')\n", encoding="utf-8"
    )
    sys.modules.pop("p24_alpha", None)

    with pytest.raises(PluginLoadError):
        await manager.reload("alpha@1.0.0")

    assert seen == ["reloading", "unloading", "unloaded", "loading", "failed", "rollback"]
