from __future__ import annotations

import ast
import hashlib
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.developer.repository.models import (
    ArchitectureModel,
    DependencyAnalyzer,
    FrameworkDetector,
    GitHistoryAnalyzer,
    RepositoryHealth,
    RepositoryIndex,
    RepositorySummary,
)

_LANG_BY_SUFFIX = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
}


class RepositoryInspector:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._index: RepositoryIndex | None = None
        self._summary: RepositorySummary | None = None

    def inspect(self) -> RepositorySummary:
        self._ensure_index()
        assert self._summary is not None
        return self._summary

    def index(self) -> RepositoryIndex:
        return self._ensure_index()

    def analyze_architecture(self) -> ArchitectureModel:
        index = self._ensure_index()
        dependencies = _scan_dependencies(self.root, index.files)
        folders = _folder_map(index.files)
        modules = _module_map(index.files)
        return ArchitectureModel(str(self.root), modules, dependencies, folders)

    def health(self) -> RepositoryHealth:
        return self._ensure_health()

    def _ensure_index(self) -> RepositoryIndex:
        if self._index is not None:
            return self._index
        files, directories = _walk_repository(self.root)
        fingerprints = {str(path): _fingerprint(path) for path in files}
        languages = _detect_languages(files)
        frameworks = _detect_frameworks(self.root, files)
        branch, branches, commits, changed_files, diff_summary = _read_git_metadata(self.root)
        readme_summary = _read_readme_summary(self.root)
        health = _build_health(self.root, directories)
        metadata = {
            "languages": languages,
            "frameworks": frameworks,
            "readme_summary": readme_summary,
        }
        self._index = RepositoryIndex(
            root=str(self.root),
            files=tuple(str(p) for p in files),
            directories=tuple(str(p) for p in directories),
            fingerprints=fingerprints,
            metadata=metadata,
        )
        self._summary = RepositorySummary(
            root=str(self.root),
            branch=branch,
            branches=branches,
            commits=commits,
            changed_files=changed_files,
            diff_summary=diff_summary,
            languages=languages,
            frameworks=frameworks,
            readme_summary=readme_summary,
            health=health,
        )
        return self._index

    def _ensure_health(self) -> RepositoryHealth:
        if self._summary is None:
            self._ensure_index()
        assert self._summary is not None
        return self._summary.health


def _walk_repository(root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    dirs: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        dirs.append(current_path)
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".venv", "node_modules"}]
        for name in filenames:
            path = current_path / name
            if path.is_file():
                files.append(path)
    return files, dirs


def _fingerprint(path: Path) -> float:
    try:
        stat = path.stat()
        return float(stat.st_size ^ int(stat.st_mtime))
    except OSError:
        return 0.0


def _detect_languages(files: list[Path]) -> list[str]:
    langs = []
    for path in files:
        lang = _LANG_BY_SUFFIX.get(path.suffix.lower())
        if lang:
            langs.append(lang)
    return sorted(set(langs))


def _detect_frameworks(root: Path, files: list[Path]) -> list[str]:
    names = {path.name.lower() for path in files}
    frameworks = []
    if "pyproject.toml" in names or any(path.suffix == ".py" for path in files):
        frameworks.append("Python")
    if "package.json" in names:
        frameworks.append("Node")
    if any(path.name.startswith("vite.config") for path in files):
        frameworks.append("Vite")
    if "requirements.txt" in names:
        frameworks.append("Python Packaging")
    return frameworks


def _read_git_metadata(root: Path) -> tuple[str | None, list[str], list[str], list[str], list[str]]:
    git_dir = root / ".git"
    if not git_dir.exists():
        return None, [], [], [], []
    branch = _read_head_branch(git_dir)
    branches = _read_branches(git_dir)
    commits = _read_commits(git_dir)
    changed_files = _read_changed_files(git_dir)
    diff_summary = [f"{len(changed_files)} changed files"] if changed_files else []
    return branch, branches, commits, changed_files, diff_summary


def _read_head_branch(git_dir: Path) -> str | None:
    head = git_dir / "HEAD"
    if not head.exists():
        return None
    text = head.read_text(encoding="utf-8", errors="ignore").strip()
    if text.startswith("ref:"):
        return text.split("/")[-1]
    return "detached"


def _read_branches(git_dir: Path) -> list[str]:
    refs = git_dir / "refs" / "heads"
    if not refs.exists():
        return []
    return sorted(str(p.relative_to(refs)).replace("\\", "/") for p in refs.rglob("*") if p.is_file())


def _read_commits(git_dir: Path) -> list[str]:
    logs = git_dir / "logs" / "HEAD"
    if not logs.exists():
        return []
    lines = logs.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [line[-40:] for line in lines[-10:] if len(line) >= 40]


def _read_changed_files(git_dir: Path) -> list[str]:
    index = git_dir / "index"
    if not index.exists():
        return []
    return ["tracked-or-staged"]


def _read_readme_summary(root: Path) -> str:
    for name in ("README.md", "readme.md", "README.txt"):
        path = root / name
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            return next((line.strip() for line in text if line.strip()), "")
    return ""


def _build_health(root: Path, directories: list[Path]) -> RepositoryHealth:
    is_repo = (root / ".git").exists()
    nested = [str(path) for path in directories if path != root and (path / ".git").exists()]
    warnings = []
    if not is_repo:
        warnings.append("Missing .git directory")
    if nested:
        warnings.append("Nested repositories detected")
    return RepositoryHealth(is_repository=is_repo, has_git_directory=is_repo, missing_git=not is_repo, nested_repositories=nested, warnings=warnings)


def _scan_dependencies(root: Path, files: tuple[str, ...]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = defaultdict(list)
    for file in files:
        path = Path(file)
        if path.suffix == ".py":
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            deps[str(path)] = sorted(set(imports))
    return dict(deps)


def _folder_map(files: tuple[str, ...]) -> dict[str, list[str]]:
    folders: dict[str, list[str]] = defaultdict(list)
    for file in files:
        p = Path(file)
        folders[str(p.parent)].append(p.name)
    return dict(folders)


def _module_map(files: tuple[str, ...]) -> dict[str, list[str]]:
    modules: dict[str, list[str]] = {}
    for file in files:
        p = Path(file)
        if p.suffix == ".py":
            modules[str(p)] = [p.stem]
    return modules
