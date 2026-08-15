"""P2.4 — Runtime Hot-Loading: active-task protection.

``PluginActivityTracker`` tracks in-flight tool invocations contributed by
plugins. The ``PluginManager`` consults it before unloading or reloading a
plugin and refuses the operation while any of the plugin's tools are in use,
so active tasks are never broken by a hot swap.
"""

from __future__ import annotations


class PluginActivityTracker:
    """Reference-counted tracker of in-use tool ids (P2.4).

    The host wraps a plugin tool invocation with ``begin(tool_id)`` /
    ``end(tool_id)``. A tool is "in use" while its count is greater than
    zero. The manager checks ``active_tool_ids()`` before unloading or
    reloading.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def begin(self, tool_id: str) -> None:
        """Mark a tool invocation as started."""
        self._counts[tool_id] = self._counts.get(tool_id, 0) + 1

    def end(self, tool_id: str) -> None:
        """Mark a tool invocation as finished (idempotent)."""
        current = self._counts.get(tool_id, 0)
        if current <= 1:
            self._counts.pop(tool_id, None)
        else:
            self._counts[tool_id] = current - 1

    def in_use(self, tool_id: str) -> bool:
        """True while at least one invocation of ``tool_id`` is active."""
        return self._counts.get(tool_id, 0) > 0

    def active_tool_ids(self) -> set[str]:
        """All tool ids with at least one active invocation."""
        return set(self._counts)

    def clear(self) -> None:
        self._counts.clear()
