"""Dependency resolution for the Plugin Registry (P2.1).

Resolves declared ``plugin_id`` dependencies to concrete ``id@version``
records, honours version constraints, prefers already-loaded versions, and
topologically orders plugins so dependencies are always loaded first.
Cycles and unsatisfiable constraints are reported as errors.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from app.plugins.models import PluginRecord
from app.plugins.semver import SemanticVersion, VersionError


class DependencyResolutionError(RuntimeError):
    """Raised when plugin dependencies cannot be resolved."""

    def __init__(
        self,
        message: str,
        missing: Optional[Iterable[str]] = None,
        cycles: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__(message)
        self.missing = list(missing or [])
        self.cycles = list(cycles or [])


def _version_key(record: PluginRecord) -> tuple[int, int, int]:
    version = SemanticVersion.parse(record.manifest.version)
    return (version.major, version.minor, version.patch)


def _choose_candidate(
    records_by_id: dict[str, list[PluginRecord]],
    plugin_id: str,
    constraint: str,
    prefer_loaded: frozenset[str],
) -> Optional[PluginRecord]:
    """Pick the concrete record satisfying ``plugin_id@constraint``.

    Prefers an already-loaded version; otherwise the highest satisfying
    version. Ties break by key for determinism.
    """
    candidates = []
    for record in records_by_id.get(plugin_id, []):
        try:
            if SemanticVersion.parse(record.manifest.version).satisfies(constraint):
                candidates.append(record)
        except VersionError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda r: (_version_key(r), r.key), reverse=True)
    for record in candidates:
        if record.key in prefer_loaded:
            return record
    return candidates[0]


def _select_dependency_keys(
    records: list[PluginRecord],
    prefer_loaded: frozenset[str],
) -> dict[tuple[str, str], str]:
    """Map each record's dependency declaration to its concrete key.

    ``(plugin_id, record_key) -> dependency_key``. Raises
    ``DependencyResolutionError`` for missing or unsatisfied constraints.
    """
    records_by_id: dict[str, list[PluginRecord]] = defaultdict(list)
    for record in records:
        records_by_id[record.manifest.id].append(record)

    selected: dict[tuple[str, str], str] = {}
    missing: list[str] = []
    for record in records:
        for dependency in record.manifest.dependencies:
            pick = _choose_candidate(
                records_by_id, dependency.plugin_id, dependency.version, prefer_loaded
            )
            if pick is None:
                available = sorted(
                    {r.manifest.version for r in records_by_id.get(dependency.plugin_id, [])}
                )
                constraint = dependency.version if dependency.version != "*" else ""
                missing.append(
                    f"{record.key} requires {dependency.plugin_id}@{constraint or '*'} "
                    f"(available: {', '.join(available) or 'none'})"
                )
            else:
                selected[(record.manifest.id, record.key)] = pick.key
    if missing:
        raise DependencyResolutionError(
            "Unresolvable plugin dependencies: " + "; ".join(missing), missing=missing
        )
    return selected


def _toposort(
    records: list[PluginRecord],
    selected: dict[tuple[str, str], str],
    subset: Optional[set[str]] = None,
) -> list[str]:
    """Deterministic dependency-first ordering of plugin keys."""
    keys = sorted(r.key for r in records)
    if subset is not None:
        keys = [k for k in keys if k in subset]

    graph: dict[str, list[str]] = {key: [] for key in keys}
    key_to_record = {r.key: r for r in records}
    for key in keys:
        record = key_to_record[key]
        dep_key = selected.get((record.manifest.id, key))
        if dep_key is not None and dep_key in graph:
            graph[dep_key].append(key)

    indegree = {key: 0 for key in graph}
    for dependencies in graph.values():
        for dependent in dependencies:
            indegree[dependent] += 1

    order: list[str] = []
    ready = sorted(k for k, degree in indegree.items() if degree == 0)
    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependency in graph[node]:
            indegree[dependency] -= 1
        remaining = set(indegree) - set(order)
        ready = sorted(k for k in remaining if indegree[k] == 0)

    if len(order) != len(graph):
        cycle_nodes = sorted(set(graph) - set(order))
        raise DependencyResolutionError(
            "Circular plugin dependency detected involving: "
            + ", ".join(cycle_nodes),
            cycles=cycle_nodes,
        )
    return order


def resolve_load_order(
    records: Iterable[PluginRecord],
    prefer_loaded: Iterable[str] = (),
) -> list[str]:
    """All plugin keys in deterministic dependency order (deps first)."""
    records = list(records)
    selected = _select_dependency_keys(records, frozenset(prefer_loaded))
    return _toposort(records, selected)


def resolve_dependencies(
    records: Iterable[PluginRecord],
    target_key: str,
    prefer_loaded: Iterable[str] = (),
) -> list[str]:
    """Transitive dependencies of ``target_key`` in load order.

    The target itself is excluded from the result; every returned key must be
    loaded before the target.
    """
    records = list(records)
    selected = _select_dependency_keys(records, frozenset(prefer_loaded))
    key_to_record = {r.key: r for r in records}

    closure: set[str] = set()
    stack = [target_key]
    while stack:
        key = stack.pop()
        record = key_to_record.get(key)
        if record is None:
            continue
        dep_key = selected.get((record.manifest.id, key))
        if dep_key is not None and dep_key not in closure:
            closure.add(dep_key)
            stack.append(dep_key)

    order = _toposort(records, selected, subset=closure | {target_key})
    return [key for key in order if key != target_key]
