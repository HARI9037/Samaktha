"""PluginManager — orchestration of discovery, loading and unloading (P2.1/P2.4).

The host entry point for the Plugin Architecture. A ``PluginManager`` owns a
``PluginRegistry`` and may be pointed at the canonical ``ToolRegistry``,
``CommunicationRegistry`` and ``CapabilityRegistry``. Loading a plugin:

  1. resolves its dependencies (loading them first when requested);
  2. imports the manifest's entry module and instantiates the ``Plugin``;
  3. structurally validates the plugin and enforces isolation boundaries;
  4. registers contributed tools, providers and capability domains through
     the canonical registries (never bypassing CAP or the security layer);
  5. runs the plugin's ``start`` lifecycle hook.

Unloading removes every contribution in reverse order and marks the record
``unloaded``. Plugins cannot register runtime executors or mutate governance:
the ``PluginContext`` exposed at start time only carries registries.

P2.4 Runtime Hot-Loading adds: ``load_directory`` for loading newly installed
plugins without a restart, active-task protection (via an optional
``PluginActivityTracker``), a transactional ``reload`` that rolls back to the
previous instance on failure, state migration across reloads (``snapshot_state``
/ ``restore_state``), and lifecycle events emitted through a
``PluginEventBus``.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from app.plugins.activity import PluginActivityTracker
from app.plugins.dependencies import DependencyResolutionError, resolve_dependencies
from app.plugins.discovery import PluginDiscovery
from app.plugins.events import PluginEventBus, PluginLifecycleEvent
from app.plugins.isolation import (
    PluginIsolationError,
    enforce_capability_boundary,
    enforce_permission_boundary,
    enforce_provider_boundary,
    enforce_tool_boundary,
)
from app.plugins.models import PluginManifest, PluginRecord, PluginState
from app.plugins.plugin import Plugin, PluginContext
from app.plugins.registry import PluginRegistrationError, PluginRegistry
from app.plugins.validation import PluginValidationResult, validate_manifest, validate_plugin
from app.tools.capability_registry import CapabilityEntry, CapabilityRegistry
from app.tools.models import ToolInfo

log = logging.getLogger(__name__)


class PluginError(RuntimeError):
    """Base class for plugin manager failures."""


class PluginLoadError(PluginError):
    """Raised when a plugin cannot be loaded."""


class PluginUnloadError(PluginError):
    """Raised when a plugin cannot be unloaded."""


@dataclass
class _ReloadSnapshot:
    """Pre-reload capture used to roll back a failed reload (P2.4)."""

    plugin: Optional[Any]
    tools: list[Any]
    providers: list[Any]
    state: PluginState
    loaded_at: Optional[datetime]
    state_data: Any = None
    contributions: list[str] = field(default_factory=list)


class PluginManager:
    """Host-side manager for the Plugin Architecture."""

    def __init__(
        self,
        registry: Optional[PluginRegistry] = None,
        discovery: Optional[PluginDiscovery] = None,
        tool_registry: Any = None,
        communication_registry: Any = None,
        capability_registry: Optional[CapabilityRegistry] = None,
        data_dir: Optional[str] = None,
        *,
        event_bus: Optional[PluginEventBus] = None,
        activity: Optional[PluginActivityTracker] = None,
    ) -> None:
        self._registry = registry or PluginRegistry()
        self._discovery = discovery or PluginDiscovery()
        self._tool_registry = tool_registry
        self._communication_registry = communication_registry
        self._capability_registry = capability_registry
        self._data_dir = data_dir
        self._event_bus = event_bus or PluginEventBus()
        self._activity = activity

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    @property
    def event_bus(self) -> PluginEventBus:
        """The bus through which lifecycle events are emitted."""
        return self._event_bus

    @property
    def activity(self) -> Optional[PluginActivityTracker]:
        """Optional active-task tracker consulted before unload/reload."""
        return self._activity

    def on(
        self, event: str, callback: Callable[[PluginLifecycleEvent], None]
    ) -> Callable[[], None]:
        """Subscribe to a lifecycle event; returns an unsubscribe callable."""
        return self._event_bus.subscribe(event, callback)

    def list_plugins(self) -> list[PluginRecord]:
        return self._registry.list()

    def list_loaded(self) -> list[PluginRecord]:
        return self._registry.list_loaded()

    def get(self, plugin_key: str) -> Optional[PluginRecord]:
        return self._registry.get(plugin_key)

    def is_loaded(self, plugin_key: str) -> bool:
        record = self._registry.get(plugin_key)
        return record is not None and record.state in (
            PluginState.LOADED,
            PluginState.ACTIVE,
        )

    def _loaded_keys(self) -> set[str]:
        return {r.key for r in self._registry.list_loaded()}

    def dependent_keys(self, plugin_key: str) -> list[str]:
        """Keys of registered records that depend on ``plugin_key``."""
        return [
            r.key
            for r in self._registry.list()
            if r.key != plugin_key and _declares_dependency(r, plugin_key)
        ]

    def has_loaded_dependents(self, plugin_key: str) -> bool:
        """True when a loaded plugin still depends on ``plugin_key``."""
        return bool(self._loaded_dependents(plugin_key))

    def _loaded_dependents(self, plugin_key: str) -> list[str]:
        return [
            key for key in self.dependent_keys(plugin_key)
            if self.is_loaded(key)
        ]

    # ------------------------------------------------------------------
    # Lifecycle events
    # ------------------------------------------------------------------

    def _emit(
        self,
        event: str,
        plugin_key: str,
        state: PluginState,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self._event_bus.emit(
            PluginLifecycleEvent(
                event=event,
                plugin_key=plugin_key,
                state=state,
                details=details or {},
            )
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, directory: str) -> list[PluginRecord]:
        """Discover manifests and register the valid ones."""
        registered: list[PluginRecord] = []
        for manifest in self._discovery.discover(directory):
            validation = validate_manifest(manifest)
            if not validation.valid:
                log.warning(
                    "PluginManager: skipping invalid manifest %r: %s",
                    manifest.key,
                    "; ".join(validation.errors),
                )
                continue
            if self._registry.has(manifest.key):
                log.warning(
                    "PluginManager: skipping duplicate plugin %s", manifest.key
                )
                continue
            try:
                record = self._registry.register(manifest)
            except PluginRegistrationError:
                continue
            registered.append(record)
            self._emit("registered", record.key, record.state)
        return registered

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load_directory(
        self,
        directory: str,
        *,
        auto_load_dependencies: bool = True,
    ) -> list[PluginRecord]:
        """Hot-load plugins discovered under ``directory`` without a restart.

        Discovers and registers any new plugin manifests, then loads the
        newly registered plugins. Individual load failures are recorded on
        the affected records and skipped — one broken plugin never blocks
        the others.
        """
        discovered = self.discover(directory)
        loaded: list[PluginRecord] = []
        for record in discovered:
            try:
                loaded.append(
                    await self.load(record.key, auto_load_dependencies=auto_load_dependencies)
                )
            except PluginLoadError:
                continue
        return loaded

    async def load(
        self,
        plugin_key: str,
        *,
        auto_load_dependencies: bool = True,
    ) -> PluginRecord:
        """Load a registered plugin, resolving dependencies first."""
        record = self._registry.get(plugin_key)
        if record is None:
            raise PluginLoadError(f"Plugin is not registered: {plugin_key}")
        if record.state in (PluginState.LOADED, PluginState.ACTIVE, PluginState.LOADING):
            return record

        try:
            dependency_keys = resolve_dependencies(
                self._registry.list(), plugin_key, prefer_loaded=self._loaded_keys()
            )
        except DependencyResolutionError as exc:
            self._registry.record_error(plugin_key, str(exc))
            self._registry.update_state(plugin_key, PluginState.FAILED)
            self._emit("failed", plugin_key, PluginState.FAILED, {"error": str(exc)})
            raise PluginLoadError(str(exc)) from exc

        for dependency_key in dependency_keys:
            if not self.is_loaded(dependency_key):
                if auto_load_dependencies:
                    await self.load(dependency_key, auto_load_dependencies=True)
                else:
                    message = f"Plugin dependency is not loaded: {dependency_key}"
                    self._registry.record_error(plugin_key, message)
                    self._registry.update_state(plugin_key, PluginState.FAILED)
                    self._emit("failed", plugin_key, PluginState.FAILED, {"error": message})
                    raise PluginLoadError(message)
        return await self._load_single(plugin_key)

    async def _load_single(self, plugin_key: str) -> PluginRecord:
        record = self._registry.get(plugin_key)
        self._registry.update_state(plugin_key, PluginState.LOADING)
        self._emit("loading", plugin_key, PluginState.LOADING)
        try:
            module = importlib.import_module(record.manifest.entry)
            plugin = _instantiate_plugin(module, record.manifest)

            structural = validate_plugin(plugin, record.manifest)
            if not structural.valid:
                raise PluginLoadError("; ".join(structural.errors))

            tools = list(plugin.provide_tools())
            providers = list(plugin.provide_providers())

            declared_scopes = {p.scope for p in record.manifest.permissions}
            declared_capabilities = [c.name for c in record.manifest.capabilities]
            for tool in tools:
                enforce_tool_boundary(tool)
                enforce_permission_boundary(declared_scopes, [tool])
                enforce_capability_boundary(declared_capabilities, [tool])
            for provider in providers:
                enforce_provider_boundary(provider)

            contributions = self._register_contributions(
                plugin_key, record.manifest, tools, providers
            )

            context = PluginContext(
                plugin_id=record.manifest.id,
                data_dir=self._data_dir,
                tool_registry=self._tool_registry,
                communication_registry=self._communication_registry,
                capability_registry=self._capability_registry,
            )
            result = plugin.start(context)
            if inspect.isawaitable(result):
                await result

            record = self._registry.get(plugin_key)
            record.contributions = contributions
            record.plugin = plugin
            record.loaded_at = _utcnow()
            record.error = None
            self._registry.update_state(plugin_key, PluginState.ACTIVE)
            log.info(
                "PluginManager: loaded — key=%s contributions=%s",
                plugin_key,
                contributions,
            )
            self._emit(
                "active",
                plugin_key,
                PluginState.ACTIVE,
                {"contributions": list(contributions)},
            )
            return record
        except (PluginLoadError, PluginIsolationError, PluginRegistrationError):
            record = self._registry.get(plugin_key)
            if record.error is None:
                record.error = "Plugin failed to load."
            self._registry.update_state(plugin_key, PluginState.FAILED)
            self._emit("failed", plugin_key, PluginState.FAILED, {"error": record.error})
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as PluginLoadError
            self._registry.record_error(plugin_key, str(exc))
            self._registry.update_state(plugin_key, PluginState.FAILED)
            self._emit("failed", plugin_key, PluginState.FAILED, {"error": str(exc)})
            raise PluginLoadError(str(exc)) from exc

    def _register_contributions(
        self,
        plugin_key: str,
        manifest: PluginManifest,
        tools: list[Any],
        providers: list[Any],
    ) -> list[str]:
        contributions: list[str] = []

        if self._tool_registry is not None:
            for tool in tools:
                if self._tool_registry.has_tool(tool.name):
                    raise PluginLoadError(
                        f"Tool id already registered: {tool.name}"
                    )
                self._tool_registry.register(
                    tool.name, tool, build_tool_info(tool, manifest)
                )
                contributions.append(f"tool:{tool.name}")

        if self._communication_registry is not None:
            for provider in providers:
                name = _provider_name(provider)
                if self._communication_registry.has_provider(name):
                    raise PluginLoadError(
                        f"Communication provider already registered: {name}"
                    )
                self._communication_registry.register(name, provider)
                contributions.append(f"provider:{name}")

        if self._capability_registry is not None and manifest.capabilities:
            for capability in manifest.capabilities:
                provider = _tool_providing(tools, capability.name)
                if provider is None:
                    raise PluginLoadError(
                        f"Declared capability '{capability.name}' is not "
                        "provided by any contributed tool."
                    )
                if self._capability_registry.is_installed(capability.name):
                    raise PluginLoadError(
                        f"Capability domain already installed: {capability.name}"
                    )
                self._capability_registry.register(
                    CapabilityEntry(
                        domain=capability.name,
                        tool_id=provider.name,
                        description=capability.description,
                    )
                )
                contributions.append(f"capability:{capability.name}")
        return contributions

    # ------------------------------------------------------------------
    # Unloading
    # ------------------------------------------------------------------

    def _unregister_contributions(self, contributions: Iterable[str]) -> None:
        """Remove registered contributions (idempotent), reverse order."""
        for contribution in reversed(list(contributions)):
            kind, _, name = contribution.partition(":")
            if kind == "tool" and self._tool_registry is not None:
                self._tool_registry.unregister(name)
            elif kind == "provider" and self._communication_registry is not None:
                self._communication_registry.unregister(name)
            elif kind == "capability" and self._capability_registry is not None:
                self._capability_registry.unregister_domain(name)

    def _ensure_no_active_contributions(self, record: PluginRecord) -> None:
        """Raise when any of the record's tools is in active use (P2.4)."""
        if self._activity is None:
            return
        active = self._activity.active_tool_ids()
        if not active:
            return
        in_use = [
            name
            for contribution in record.contributions
            if contribution.startswith("tool:")
            and (name := contribution.partition(":")[2]) in active
        ]
        if in_use:
            raise PluginUnloadError(
                f"Cannot unload '{record.key}': active tasks still use "
                f"tools {sorted(in_use)}"
            )

    async def unload(self, plugin_key: str) -> PluginRecord:
        """Unload a plugin, removing all of its contributions."""
        record = self._registry.get(plugin_key)
        if record is None:
            raise PluginUnloadError(f"Plugin is not registered: {plugin_key}")
        if record.state == PluginState.UNLOADED:
            return record
        if record.state == PluginState.LOADING:
            raise PluginUnloadError(f"Cannot unload a plugin while loading: {plugin_key}")

        dependents = self._loaded_dependents(plugin_key)
        if dependents:
            raise PluginUnloadError(
                f"Cannot unload '{plugin_key}': loaded dependents "
                f"{sorted(dependents)} still depend on it."
            )

        self._ensure_no_active_contributions(record)

        self._registry.update_state(plugin_key, PluginState.UNLOADING)
        self._emit("unloading", plugin_key, PluginState.UNLOADING)
        try:
            plugin = record.plugin
            if plugin is not None:
                result = plugin.stop()
                if inspect.isawaitable(result):
                    await result

            self._unregister_contributions(record.contributions)

            record = self._registry.get(plugin_key)
            record.contributions = []
            record.plugin = None
            record.unloaded_at = _utcnow()
            record.error = None
            self._registry.update_state(plugin_key, PluginState.UNLOADED)
            log.info("PluginManager: unloaded — key=%s", plugin_key)
            self._emit("unloaded", plugin_key, PluginState.UNLOADED)
            return record
        except Exception as exc:  # noqa: BLE001 - surfaced as PluginUnloadError
            self._registry.record_error(plugin_key, str(exc))
            self._registry.update_state(plugin_key, PluginState.FAILED)
            self._emit("failed", plugin_key, PluginState.FAILED, {"error": str(exc)})
            raise PluginUnloadError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Reload (transactional, P2.4)
    # ------------------------------------------------------------------

    def _snapshot_for_reload(self, record: PluginRecord) -> _ReloadSnapshot:
        plugin = record.plugin
        tools = list(plugin.provide_tools()) if plugin is not None else []
        providers = list(plugin.provide_providers()) if plugin is not None else []
        state_data = plugin.snapshot_state() if plugin is not None else None
        return _ReloadSnapshot(
            plugin=plugin,
            tools=tools,
            providers=providers,
            state=record.state,
            loaded_at=record.loaded_at,
            state_data=state_data,
            contributions=list(record.contributions),
        )

    async def _rollback_reload(
        self, plugin_key: str, snapshot: _ReloadSnapshot
    ) -> None:
        """Restore the previous plugin instance after a failed reload."""
        record = self._registry.get(plugin_key)
        if record is None:
            return
        try:
            self._unregister_contributions(snapshot.contributions)
            contributions = self._register_contributions(
                plugin_key, record.manifest, snapshot.tools, snapshot.providers
            )
        except Exception as exc:  # noqa: BLE001 - rolled back to FAILED
            message = f"Rollback failed: {exc}"
            self._registry.record_error(plugin_key, message)
            self._registry.update_state(plugin_key, PluginState.FAILED)
            self._emit("failed", plugin_key, PluginState.FAILED, {"error": message})
            return
        record = self._registry.get(plugin_key)
        record.contributions = contributions
        record.plugin = snapshot.plugin
        record.loaded_at = snapshot.loaded_at
        record.error = None
        self._registry.update_state(plugin_key, snapshot.state)
        log.info("PluginManager: rollback — key=%s state=%s", plugin_key, snapshot.state)
        self._emit("rollback", plugin_key, snapshot.state)

    async def _restore_migrated_state(
        self, record: PluginRecord, state_data: Any
    ) -> None:
        """Migrate a previously snapshotted state onto a fresh instance (P2.4)."""
        if state_data is None:
            return
        plugin = record.plugin
        if plugin is None:
            return
        if getattr(type(plugin), "restore_state", None) is Plugin.restore_state:
            return
        result = plugin.restore_state(state_data)
        if inspect.isawaitable(result):
            await result

    async def reload(self, plugin_key: str) -> PluginRecord:
        """Unload then load a plugin, transactionally (P2.4).

        Active-task protection and dependency checks are enforced before the
        swap. If the reload fails, the previous plugin instance and its
        contributions are rolled back, leaving the plugin in its prior state.
        Runtime state snapshotted via ``snapshot_state`` is migrated to the
        new instance via ``restore_state``.
        """
        record = self.get(plugin_key)
        if record is None:
            raise PluginLoadError(f"Plugin is not registered: {plugin_key}")
        dependents = self._loaded_dependents(plugin_key)
        if dependents:
            raise PluginUnloadError(
                f"Cannot reload '{plugin_key}': loaded dependents "
                f"{sorted(dependents)} still depend on it."
            )
        if record.state in (PluginState.LOADED, PluginState.ACTIVE):
            self._ensure_no_active_contributions(record)

        snapshot = self._snapshot_for_reload(record)
        self._emit("reloading", plugin_key, snapshot.state)
        await self.unload(plugin_key)

        try:
            record = await self.load(plugin_key)
        except PluginLoadError:
            await self._rollback_reload(plugin_key, snapshot)
            raise

        await self._restore_migrated_state(record, snapshot.state_data)
        return record

    async def activate(self, plugin_key: str) -> PluginRecord:
        """Run a loaded plugin's ``start`` hook again (e.g. after deactivate)."""
        record = self.get(plugin_key)
        if record is None:
            raise PluginError(f"Plugin is not registered: {plugin_key}")
        if record.state == PluginState.ACTIVE:
            return record
        if record.state in (PluginState.UNLOADED, PluginState.FAILED):
            return await self.load(plugin_key)
        if record.state != PluginState.LOADED:
            raise PluginError(
                f"Cannot activate plugin in state {record.state}: {plugin_key}"
            )
        plugin = record.plugin
        if plugin is not None:
            result = plugin.start(self._make_context(record))
            if inspect.isawaitable(result):
                await result
        self._registry.update_state(plugin_key, PluginState.ACTIVE)
        self._emit("activated", plugin_key, PluginState.ACTIVE)
        return record

    async def deactivate(self, plugin_key: str) -> PluginRecord:
        """Stop a plugin's lifecycle hook while keeping contributions loaded."""
        record = self.get(plugin_key)
        if record is None:
            raise PluginError(f"Plugin is not registered: {plugin_key}")
        if record.state != PluginState.ACTIVE:
            return record
        plugin = record.plugin
        if plugin is not None:
            result = plugin.stop()
            if inspect.isawaitable(result):
                await result
        self._registry.update_state(plugin_key, PluginState.LOADED)
        self._emit("deactivated", plugin_key, PluginState.LOADED)
        return record

    def _make_context(self, record: PluginRecord) -> PluginContext:
        return PluginContext(
            plugin_id=record.manifest.id,
            data_dir=self._data_dir,
            tool_registry=self._tool_registry,
            communication_registry=self._communication_registry,
            capability_registry=self._capability_registry,
        )


def _instantiate_plugin(module, manifest: PluginManifest) -> Plugin:
    """Instantiate a ``Plugin`` from a loaded entry module."""
    factory = getattr(module, "create_plugin", None)
    if callable(factory):
        plugin = factory()
        if isinstance(plugin, Plugin):
            return plugin
        raise PluginLoadError("create_plugin() must return a Plugin instance.")

    candidate = getattr(module, "plugin", None)
    if isinstance(candidate, Plugin):
        return candidate

    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, Plugin)
            and value is not Plugin
        ):
            try:
                instance = value()
            except TypeError:
                continue
            if isinstance(instance, Plugin):
                return instance

    raise PluginLoadError(
        f"Plugin entry '{manifest.entry}' must expose a 'create_plugin' "
        "factory, a 'plugin' instance, or a Plugin subclass."
    )


def build_tool_info(tool, manifest: PluginManifest) -> ToolInfo:
    """Derive canonical ``ToolInfo`` from a contributed ``Tool``."""
    def _as_str(value) -> str:
        return value.value if hasattr(value, "value") else str(value)

    capabilities = [_as_str(c) for c in (getattr(tool, "capabilities", None) or ())]
    policy = getattr(tool, "policy", None)
    raw_permissions = (
        getattr(tool, "permissions", None)
        or (getattr(policy, "permissions", None) if policy else None)
        or ()
    )
    permissions = [_as_str(p) for p in raw_permissions]
    category = getattr(tool, "category", None)
    category = category.value if hasattr(category, "value") else category
    description = (
        getattr(tool, "description", None)
        or (getattr(policy, "description", "") if policy else "")
        or ""
    )
    approval_required = bool(
        getattr(tool, "approval_required", False)
        or (getattr(policy, "approval_required", False) if policy else False)
    )
    return ToolInfo(
        tool_id=tool.name,
        description=description,
        capabilities=capabilities,
        input_schema=dict(getattr(tool, "input_schema", {}) or {}),
        metadata={
            "source": "plugin",
            "plugin_id": manifest.id,
            "plugin_version": manifest.version,
        },
        category=category,
        permissions=permissions,
        approval_required=approval_required,
        supported_actions=[_as_str(a) for a in (getattr(tool, "supported_actions", None) or ())],
        policy=policy,
    )


def _provider_name(provider) -> str:
    name = getattr(provider, "provider_id", None)
    if name is None:
        name = type(provider).__name__.lower()
    return str(name).lower()


def _tool_providing(tools: Iterable[Any], capability_name: str):
    for tool in tools:
        provided = {
            c.value if hasattr(c, "value") else str(c)
            for c in (getattr(tool, "capabilities", None) or ())
        }
        if capability_name in provided:
            return tool
    return None


def _declares_dependency(record: PluginRecord, target_key: str) -> bool:
    target_id = target_key.split("@", 1)[0]
    return any(dep.plugin_id == target_id for dep in record.manifest.dependencies)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
