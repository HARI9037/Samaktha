"""P1.7 — Structured code review engine.

Real AST-based analyzers producing structured findings with severity,
location, message, and source evidence. Replaces the earlier keyword
heuristics. Every analyzer inspects actual Python syntax (AST), and the
engine degrades deterministically on unparseable or unreadable files.
"""

from __future__ import annotations

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

_SECRET_NAME_RE = re.compile(
    r"(password|passwd|pass|token|secret|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?token)",
    re.IGNORECASE,
)
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK)\b")

_DEFAULT_LONG_FUNCTION_LINES = 50


class Severity(str, Enum):
    """Severity classification for review findings."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"info": 0, "low": 1, "medium": 2, "high": 3}[self.value]


@dataclass(slots=True)
class Finding:
    """A single structured review finding with attached evidence."""

    rule: str
    severity: Severity
    message: str
    category: str = "general"
    file: str = ""
    line: int | None = None
    evidence: str = ""


@dataclass(slots=True)
class ReviewResult:
    """Aggregated outcome of a review run."""

    findings: list[Finding] = field(default_factory=list)
    files_scanned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def count(self) -> int:
        return len(self.findings)

    def by_severity(self) -> dict[str, int]:
        counts = {level.value: 0 for level in Severity}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (-f.severity.rank, f.file, f.line or 0, f.rule),
        )


class BaseAnalyzer(ABC):
    """Base class for AST-based code analyzers."""

    rule: str = "analyzer"
    severity: Severity = Severity.INFO
    category: str = "general"

    @abstractmethod
    def analyze(
        self, path: Path, tree: ast.AST, source_lines: list[str]
    ) -> list[Finding]:
        """Analyze one parsed module and return its findings."""


class HardcodedSecretAnalyzer(BaseAnalyzer):
    """Detect literal secrets assigned to secret-looking names."""

    rule = "hardcoded-secret"
    severity = Severity.HIGH
    category = "security"

    def analyze(
        self, path: Path, tree: ast.AST, source_lines: list[str]
    ) -> list[Finding]:
        findings: list[Finding] = []
        for node in ast.walk(tree):
            targets: list[str] = []
            value: ast.AST | None = None
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = [t for t in node.targets] if isinstance(node, ast.Assign) else [node.target]
                value = node.value
            elif isinstance(node, ast.Dict):
                for key, val in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and _SECRET_NAME_RE.search(key.value)
                        and isinstance(val, (ast.Constant, ast.JoinedStr))
                    ):
                        findings.append(self._finding(path, source_lines, val, key.value))
                continue
            else:
                continue
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and _SECRET_NAME_RE.search(target.id):
                    findings.append(self._finding(path, source_lines, value, target.id))
        return findings

    def _finding(
        self, path: Path, source_lines: list[str], value: ast.AST, name: str
    ) -> Finding:
        return Finding(
            rule=self.rule,
            severity=self.severity,
            message=f"Potential hardcoded secret in '{name}'",
            category=self.category,
            file=str(path),
            line=getattr(value, "lineno", None),
            evidence=_line_at(source_lines, value),
        )


class NestedLoopAnalyzer(BaseAnalyzer):
    """Report loops nested inside another loop (depth >= 2)."""

    rule = "nested-loop"
    severity = Severity.LOW
    category = "performance"

    def analyze(
        self, path: Path, tree: ast.AST, source_lines: list[str]
    ) -> list[Finding]:
        findings: list[Finding] = []

        def visit(node: ast.AST, depth: int) -> None:
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                if depth >= 1:
                    findings.append(
                        Finding(
                            rule=self.rule,
                            severity=self.severity,
                            message=f"Loop nested {depth + 1} levels deep",
                            category=self.category,
                            file=str(path),
                            line=node.lineno,
                            evidence=_line_at(source_lines, node),
                        )
                    )
                for child in _child_stmts(node):
                    visit(child, depth + 1)
                return
            for child in _child_stmts(node):
                visit(child, depth)

        for node in tree.body:
            visit(node, 0)
        return findings


class UnusedImportAnalyzer(BaseAnalyzer):
    """Report imported names that are never referenced as loads."""

    rule = "unused-import"
    severity = Severity.LOW
    category = "correctness"

    def analyze(
        self, path: Path, tree: ast.AST, source_lines: list[str]
    ) -> list[Finding]:
        imports: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        imports[alias.asname] = node.lineno
                    else:
                        imports[alias.name.split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imports[alias.asname or alias.name] = node.lineno
        refs = {
            n.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        }
        defined = {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        findings: list[Finding] = []
        for name, line in sorted(imports.items()):
            if name in refs or name in defined:
                continue
            findings.append(
                Finding(
                    rule=self.rule,
                    severity=self.severity,
                    message=f"Imported name '{name}' is never used",
                    category=self.category,
                    file=str(path),
                    line=line,
                    evidence=_line_at_index(source_lines, line),
                )
            )
        return findings


class LongFunctionAnalyzer(BaseAnalyzer):
    """Flag functions whose body spans more than ``threshold`` lines."""

    rule = "long-function"
    severity = Severity.MEDIUM
    category = "maintainability"

    def __init__(self, threshold: int = _DEFAULT_LONG_FUNCTION_LINES) -> None:
        self.threshold = threshold

    def analyze(
        self, path: Path, tree: ast.AST, source_lines: list[str]
    ) -> list[Finding]:
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start) or start
            span = end - start
            if span > self.threshold:
                findings.append(
                    Finding(
                        rule=self.rule,
                        severity=self.severity,
                        message=f"Function '{node.name}' spans {span} lines",
                        category=self.category,
                        file=str(path),
                        line=node.lineno,
                        evidence=_line_at(source_lines, node),
                    )
                )
        return findings


class TodoFIXMEAnalyzer(BaseAnalyzer):
    """Flag TODO/FIXME/HACK markers in the source."""

    rule = "todo-fixme"
    severity = Severity.INFO
    category = "maintainability"

    def analyze(
        self, path: Path, tree: ast.AST, source_lines: list[str]
    ) -> list[Finding]:
        findings: list[Finding] = []
        for index, line in enumerate(source_lines, start=1):
            if _TODO_RE.search(line):
                findings.append(
                    Finding(
                        rule=self.rule,
                        severity=self.severity,
                        message=f"Code marker found: {_TODO_RE.search(line).group(0)}",
                        category=self.category,
                        file=str(path),
                        line=index,
                        evidence=line.strip(),
                    )
                )
        return findings


DEFAULT_ANALYZERS: list[BaseAnalyzer] = [
    HardcodedSecretAnalyzer(),
    UnusedImportAnalyzer(),
    LongFunctionAnalyzer(),
    NestedLoopAnalyzer(),
    TodoFIXMEAnalyzer(),
]


class ReviewEngine:
    """Runs the configured analyzers over files or a whole repository.

    Failure behavior: unreadable paths are reported in ``errors``; files that
    fail to parse produce a structured ``parse-error`` finding (severity
    HIGH); a raised analyzer never aborts the run — it is recorded as an
    error and scanning continues.
    """

    def __init__(
        self,
        analyzers: list[BaseAnalyzer] | None = None,
        include_patterns: tuple[str, ...] = ("*.py",),
    ) -> None:
        self._analyzers = analyzers if analyzers is not None else list(DEFAULT_ANALYZERS)
        self._include_patterns = include_patterns

    def review(self, path: str | Path) -> ReviewResult:
        path = Path(path)
        if path.is_file():
            return self.review_files([path])
        if path.is_dir():
            return self.review_repository(path)
        return ReviewResult(errors=[f"Path not found: {path}"])

    def review_files(self, paths: Iterable[str | Path]) -> ReviewResult:
        result = ReviewResult()
        for raw in paths:
            path = Path(raw)
            if not path.is_file():
                result.errors.append(f"Not a file: {path}")
                continue
            self._scan_file(path, result)
        return result

    def review_repository(self, root: str | Path) -> ReviewResult:
        root = Path(root)
        if not root.is_dir():
            return ReviewResult(errors=[f"Not a directory: {root}"])
        result = ReviewResult()
        for pattern in self._include_patterns:
            for path in sorted(root.rglob(pattern)):
                if _is_ignored(path):
                    continue
                self._scan_file(path, result)
        return result

    def _scan_file(self, path: Path, result: ReviewResult) -> None:
        result.files_scanned.append(str(path))
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            result.errors.append(f"Could not read {path}: {exc}")
            return
        source_lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            result.findings.append(
                Finding(
                    rule="parse-error",
                    severity=Severity.HIGH,
                    message=f"File could not be parsed: {exc.msg}",
                    category="correctness",
                    file=str(path),
                    line=exc.lineno,
                    evidence=(exc.text or "").strip() or str(exc),
                )
            )
            return
        for analyzer in self._analyzers:
            try:
                findings = analyzer.analyze(path, tree, source_lines)
            except Exception as exc:
                result.errors.append(
                    f"{analyzer.rule} failed on {path}: {exc}"
                )
                continue
            result.findings.extend(findings)

    def list_rules(self) -> list[str]:
        return [analyzer.rule for analyzer in self._analyzers]


def _line_at(source_lines: list[str], node: ast.AST) -> str:
    line = getattr(node, "lineno", None)
    if line is None or not (1 <= line <= len(source_lines)):
        return ""
    return source_lines[line - 1].strip()


def _line_at_index(source_lines: list[str], line: int) -> str:
    if not (1 <= line <= len(source_lines)):
        return ""
    return source_lines[line - 1].strip()


def _child_stmts(node: ast.AST) -> list[ast.stmt]:
    stmts: list[ast.stmt] = []
    for field_name in ("body", "orelse", "finalbody"):
        value = getattr(node, field_name, None)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, ast.stmt):
                    stmts.append(item)
    return stmts


def _is_ignored(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {".venv", "node_modules", "__pycache__", "site-packages", ".git"})
