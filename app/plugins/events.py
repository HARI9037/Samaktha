"""P2.4 — Runtime Hot-Loading: plugin lifecycle events.

A small, synchronous event bus for plugin lifecycle transitions. The host
(``PluginManager``) emits a ``PluginLifecycleEvent`` at every state change —
registered, loading, active, unloading, unloaded, failed, reloading and
rollback — and listeners subscribe per event or via the ``*`` wildcard.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from app.plugins.models import PluginState


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PluginLifecycleEvent:
    """An immutable record of a single plugin lifecycle transition."""

    event: str
    """Event name: registered/loading/active/unloading/unloaded/failed/
    reloading/rollback/activated/deactivated."""

    plugin_key: str
    """The affected plugin's ``id@version`` key."""

    state: PluginState
    """The plugin's state at the time the event was emitted."""

    details: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=_utcnow)


class PluginEventBus:
    """Publish/subscribe for ``PluginLifecycleEvent``s."""

    WILDCARD = "*"

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[PluginLifecycleEvent], None]]] = defaultdict(list)

    def subscribe(
        self,
        event: str,
        callback: Callable[[PluginLifecycleEvent], None],
    ) -> Callable[[], None]:
        """Register ``callback`` for ``event``; returns an unsubscribe callable."""
        self._listeners[event].append(callback)

        def _unsubscribe() -> None:
            try:
                self._listeners[event].remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def on(
        self,
        event: str,
        callback: Callable[[PluginLifecycleEvent], None],
    ) -> Callable[[], None]:
        """Alias for :meth:`subscribe`."""
        return self.subscribe(event, callback)

    def emit(self, event: PluginLifecycleEvent) -> None:
        """Deliver ``event`` to event-specific and wildcard listeners."""
        listeners = list(self._listeners.get(event.event, ()))
        listeners += list(self._listeners.get(self.WILDCARD, ()))
        for callback in listeners:
            callback(event)

    def listener_count(self, event: str) -> int:
        """Number of registered listeners for ``event`` (excluding wildcard)."""
        return len(self._listeners.get(event, ()))

    def clear(self) -> None:
        self._listeners.clear()
