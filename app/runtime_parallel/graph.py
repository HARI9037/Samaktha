from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionGraph:
    task_ids: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    parent: dict[str, str | None] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)
    ready: set[str] = field(default_factory=set)

