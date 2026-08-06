from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ModuleExplorer:
    modules: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectSummarizer:
    summary: str = ""


@dataclass(slots=True)
class ProjectExplorer:
    root: str
    architecture: dict[str, list[str]]

