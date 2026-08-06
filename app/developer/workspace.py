from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WorkspaceIndex:
    repositories: list[str] = field(default_factory=list)


class WorkspaceGraph:
    def build(self, roots: list[str | Path]) -> dict[str, list[str]]:
        return {str(root): [] for root in roots}


class WorkspaceSearcher:
    def search(self, index: WorkspaceIndex, query: str) -> list[str]:
        return [repo for repo in index.repositories if query.lower() in repo.lower()]


class WorkspaceManager:
    def __init__(self, roots: list[str | Path]) -> None:
        self.roots = [str(Path(root).resolve()) for root in roots]

