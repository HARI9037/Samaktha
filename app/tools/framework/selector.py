"""Capability- and category-based tool selection.

The selector is GAMBIT's bridge to the registry: given a requested
capability (and optionally a category), it returns the best available
tool id. Selection is data-driven — nothing here hardcodes a tool.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RegistryView(Protocol):
    def list_tools(self) -> list[Any]: ...


class ToolSelector:
    """Resolves a requested capability/category to a concrete tool id."""

    def __init__(self, registry: RegistryView | None = None) -> None:
        self._registry = registry
        self._preferred: dict[str, str] = {}

    def prefer(self, capability: str, tool_id: str) -> None:
        self._preferred[capability.lower()] = tool_id

    def _candidates(
        self, tools: list[Any], capability: str, category: str | None
    ) -> list[Any]:
        capability_l = capability.lower()
        matches: list[Any] = []
        for tool in tools:
            info = tool.info if hasattr(tool, "info") else tool
            declared = [c.lower() for c in (getattr(info, "capabilities", None) or [])]
            if capability_l in declared:
                if category is None or getattr(info, "category", None) == category:
                    matches.append(tool)
        return matches

    def select(
        self,
        capability: str,
        category: str | None = None,
        tool_id: str | None = None,
    ) -> str | None:
        """Return the best tool id for a capability, or None if unavailable.

        When ``tool_id`` is given, only that tool is considered (still
        subject to capability matching). ``prefer`` hints win first.
        """
        if tool_id is not None:
            return tool_id if self._capability_matches(tool_id, capability) else None

        preferred = self._preferred.get(capability.lower())
        if preferred is not None and self._capability_matches(preferred, capability):
            return preferred

        if self._registry is None:
            return None
        candidates = self._candidates(self._registry.list_tools(), capability, category)
        if not candidates:
            return None
        return getattr(candidates[0], "info", candidates[0]).tool_id

    def _capability_matches(self, candidate_id: str, capability: str) -> bool:
        if self._registry is None:
            return False
        for tool in self._registry.list_tools():
            info = tool.info if hasattr(tool, "info") else tool
            if getattr(info, "tool_id", None) != candidate_id:
                continue
            declared = [c.lower() for c in (getattr(info, "capabilities", None) or [])]
            return capability.lower() in declared
        return False
