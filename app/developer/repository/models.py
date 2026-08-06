from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RepositoryHealth:
    is_repository: bool
    has_git_directory: bool
    missing_git: bool
    nested_repositories: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepositorySummary:
    root: str
    branch: str | None
    branches: list[str]
    commits: list[str]
    changed_files: list[str]
    diff_summary: list[str]
    languages: list[str]
    frameworks: list[str]
    readme_summary: str
    health: RepositoryHealth


@dataclass(slots=True)
class RepositoryIndex:
    root: str
    files: tuple[str, ...]
    directories: tuple[str, ...]
    fingerprints: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ArchitectureModel:
    root: str
    modules: dict[str, list[str]]
    dependencies: dict[str, list[str]]
    folders: dict[str, list[str]]


@dataclass(slots=True)
class DependencyAnalyzer:
    dependencies: dict[str, list[str]]


@dataclass(slots=True)
class GitHistoryAnalyzer:
    branch: str | None
    branches: list[str]
    commits: list[str]
    changed_files: list[str]
    diff_summary: list[str]


@dataclass(slots=True)
class FrameworkDetector:
    frameworks: list[str]


@dataclass(slots=True)
class RepositoryInspector:
    root: Path
    index: RepositoryIndex
    health: RepositoryHealth
    summary: RepositorySummary
    architecture: ArchitectureModel
    dependency_analyzer: DependencyAnalyzer
    git_history: GitHistoryAnalyzer
    framework_detector: FrameworkDetector

