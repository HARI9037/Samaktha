from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class CodeIndex:
    symbols: dict[str, list[str]] = field(default_factory=dict)
    references: dict[str, list[str]] = field(default_factory=dict)
    imports: dict[str, list[str]] = field(default_factory=dict)


class SymbolResolver:
    def resolve(self, index: CodeIndex, name: str) -> list[str]:
        return sorted(
            file for file, symbols in index.symbols.items() if name in symbols
        )


class ReferenceFinder:
    def find(self, index: CodeIndex, name: str) -> list[str]:
        return sorted(
            file for file, refs in index.references.items() if name in refs
        )


class CallGraphBuilder:
    def build(self, root: str | Path) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for path in Path(root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            calls: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
            graph[str(path)] = sorted(set(calls))
        return graph


class DependencyGraph:
    def build(self, root: str | Path) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for path in Path(root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            deps: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    deps.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    deps.append(node.module)
            graph[str(path)] = sorted(set(deps))
        return graph


class DuplicateDetector:
    def find(self, root: str | Path) -> list[list[str]]:
        buckets: dict[str, list[str]] = {}
        for path in Path(root).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            buckets.setdefault(text, []).append(str(path))
        return [paths for paths in buckets.values() if len(paths) > 1]


class DeadCodeAnalyzer:
    def find(self, index: CodeIndex) -> list[str]:
        referenced = {ref for refs in index.references.values() for ref in refs}
        declared = {name for symbols in index.symbols.values() for name in symbols}
        return sorted(declared - referenced)


class RenamePlanner:
    def plan(self, index: CodeIndex, old_name: str, new_name: str) -> dict[str, list[str]]:
        return {"rename": index.symbols.get(old_name, []), "from": [old_name], "to": [new_name]}


class CodeExplorer:
    def index(self, root: str | Path) -> CodeIndex:
        symbols: dict[str, list[str]] = {}
        references: dict[str, list[str]] = {}
        imports: dict[str, list[str]] = {}
        for path in Path(root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            names: list[str] = []
            refs: list[str] = []
            imps: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, ast.Name):
                    refs.append(node.id)
                elif isinstance(node, ast.Import):
                    imps.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imps.append(node.module)
            symbols[str(path)] = sorted(set(names))
            references[str(path)] = sorted(set(refs))
            imports[str(path)] = sorted(set(imps))
        return CodeIndex(symbols=symbols, references=references, imports=imports)
