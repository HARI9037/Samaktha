"""Freeze DDGS at the canonical SearchProvider adapter boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from app.config.settings import Settings
from app.internet.ddgs import DDGSSearchProvider


APP_ROOT = Path(__file__).resolve().parents[2] / "app"
DDGS_ADAPTER = (APP_ROOT / "internet" / "ddgs.py").resolve()
CANONICAL_TOOL_COMPOSITION = (APP_ROOT / "core" / "app.py").resolve()


def _third_party_ddgs_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names if alias.name == "ddgs" or alias.name.startswith("ddgs."))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "ddgs" or module.startswith("ddgs."):
                imports.append(module)
    return imports


def _internet_tool_constructors(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "InternetTool"
    )


def test_only_search_provider_adapter_imports_third_party_ddgs() -> None:
    callers = {
        path.resolve(): _third_party_ddgs_imports(path)
        for path in APP_ROOT.rglob("*.py")
        if _third_party_ddgs_imports(path)
    }
    assert callers == {
        DDGS_ADAPTER: ["ddgs"],
    }


def test_only_canonical_composition_constructs_production_internet_tool() -> None:
    constructors = {
        path.resolve(): _internet_tool_constructors(path)
        for path in APP_ROOT.rglob("*.py")
        if _internet_tool_constructors(path)
    }
    assert constructors == {CANONICAL_TOOL_COMPOSITION: 1}


def test_default_settings_select_ddgs_without_endpoint_or_key() -> None:
    settings = Settings(_env_file=None)
    assert settings.search_provider == "ddgs"
    assert not hasattr(settings, "ddgs_api_key")
    assert not hasattr(settings, "ddgs_url")


def test_ddgs_adapter_remains_a_search_provider() -> None:
    from app.internet.provider import SearchProvider

    assert issubclass(DDGSSearchProvider, SearchProvider)


def test_packaging_collects_lazy_ddgs_modules_without_api_server_extras() -> None:
    spec = (APP_ROOT.parent / "samaktha.spec").read_text(encoding="utf-8")
    tree = ast.parse(spec, filename="samaktha.spec")
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "collect_submodules"
    ]
    assert len(calls) == 1
    assert calls[0].args and isinstance(calls[0].args[0], ast.Constant)
    assert calls[0].args[0].value == "ddgs"
    assert "ddgs.api_server" in spec
    assert "ddgs.cli" in spec
