"""P2.2 — Plugin SDK regression tests.

Covers the ``samaktha-plugin`` CLI, scaffolding/templates, local
installation, the ``PluginHarness`` testing utilities and the shipped
example plugins. The SDK builds on the P2.1 architecture, so these tests
exercise the full path: scaffold -> validate -> load -> install -> test.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.plugins.sdk import (
    InstallError,
    PluginHarness,
    ScaffoldError,
    install_plugin,
    list_installed,
    resolve_plugins_dir,
    scaffold_plugin,
    template_module_name,
    template_plugin_id,
    uninstall_plugin,
    validate_plugin_directory,
)
from app.plugins.sdk.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "plugins"


# --------------------------------------------------------------------------- #
# Scaffold
# --------------------------------------------------------------------------- #


def test_template_plugin_id_derivation():
    assert template_plugin_id("My Cool Plugin") == "my-cool-plugin"
    assert template_plugin_id("  Foo.Bar_2  ") == "foo.bar_2"
    assert template_plugin_id("!!!") == ""
    assert template_plugin_id("") == ""


def test_template_module_name():
    assert template_module_name("my-cool-plugin") == "my_cool_plugin"
    assert template_module_name("hello.world") == "hello_world"


def test_scaffold_tool_writes_complete_layout(tmp_path):
    target = scaffold_plugin(
        "greeter",
        kind="tool",
        output_dir=tmp_path,
        author="Test Author",
        description="A greeting tool.",
        version="2.3.4",
    )
    assert target == tmp_path / "greeter"
    assert (target / "manifest.json").exists()
    assert (target / "greeter.py").exists()
    assert (target / "tests" / "test_greeter.py").exists()
    assert (target / "README.md").exists()

    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "greeter"
    assert manifest["version"] == "2.3.4"
    assert manifest["kind"] == "tool"
    assert manifest["author"] == "Test Author"
    assert manifest["entry"] == "greeter"
    assert manifest["capabilities"][0]["name"] == "greeter"
    assert manifest["permissions"][0]["scope"] == "read"

    _manifest, result = validate_plugin_directory(target)
    assert result.valid, result.errors


@pytest.mark.parametrize("kind", ["tool", "provider", "skill", "personality"])
def test_scaffold_all_kinds(tmp_path, kind):
    target = scaffold_plugin("demo", kind=kind, output_dir=tmp_path)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == kind
    _manifest, result = validate_plugin_directory(target)
    assert result.valid, result.errors
    assert (target / "demo.py").exists()
    assert (target / "tests" / "test_demo.py").exists()


def test_scaffold_rejects_invalid_kind(tmp_path):
    with pytest.raises(ScaffoldError, match="kind"):
        scaffold_plugin("demo", kind="gadget", output_dir=tmp_path)


def test_scaffold_rejects_existing_dir(tmp_path):
    (tmp_path / "demo").mkdir()
    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold_plugin("demo", output_dir=tmp_path)


def test_scaffold_rejects_invalid_name(tmp_path):
    with pytest.raises(ScaffoldError):
        scaffold_plugin("!!!", output_dir=tmp_path)


def test_scaffolded_tool_loads(tmp_path):
    target = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    harness = PluginHarness(plugin_dir=target)
    try:
        assert f"greeter@1.0.0" in harness.keys()
        record = asyncio.run(harness.load("greeter@1.0.0"))
        assert record.state.value == "active"
        assert "tool:greeter" in record.contributions
        assert harness.tool_registry.has_tool("greeter")

        tool = harness.tool_registry.get_tool("greeter")
        result = asyncio.run(tool.run({"who": "world"}))
        assert result.ok is True
        assert result.data["greeting"] == "Hello, world!"
    finally:
        harness.cleanup()


def test_scaffolded_provider_loads(tmp_path):
    target = scaffold_plugin("pinger", kind="provider", output_dir=tmp_path)
    harness = PluginHarness(plugin_dir=target)
    try:
        record = asyncio.run(harness.load("pinger@1.0.0"))
        assert record.state.value == "active"
        assert "provider:pinger" in record.contributions
        assert harness.communication_registry.has_provider("pinger")
    finally:
        harness.cleanup()


# --------------------------------------------------------------------------- #
# Install / uninstall / list
# --------------------------------------------------------------------------- #


def test_install_valid_plugin(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    dest = install_plugin(src, plugins_dir=tmp_path / "plugins")
    assert dest == tmp_path / "plugins" / "greeter"
    assert (dest / "manifest.json").exists()
    assert (dest / "greeter.py").exists()


def test_install_rejects_invalid_manifest(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text(
        json.dumps({"id": "BROKEN", "version": "not-a-version", "entry": "nope"}),
        encoding="utf-8",
    )
    with pytest.raises(InstallError):
        install_plugin(bad, plugins_dir=tmp_path / "plugins")


def test_install_rejects_missing_entry(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    (src / "greeter.py").unlink()
    with pytest.raises(InstallError, match="Entry module"):
        install_plugin(src, plugins_dir=tmp_path / "plugins")


def test_install_duplicate_requires_force(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    plugins_dir = tmp_path / "plugins"
    install_plugin(src, plugins_dir=plugins_dir)
    with pytest.raises(InstallError, match="already installed"):
        install_plugin(src, plugins_dir=plugins_dir)
    install_plugin(src, plugins_dir=plugins_dir, force=True)


def test_uninstall_and_list_installed(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    plugins_dir = tmp_path / "plugins"
    install_plugin(src, plugins_dir=plugins_dir)

    installed = list_installed(plugins_dir=plugins_dir)
    assert [(p.name, m.id) for p, m in installed] == [("greeter", "greeter")]

    assert uninstall_plugin("greeter", plugins_dir=plugins_dir) is True
    assert list_installed(plugins_dir=plugins_dir) == []


def test_uninstall_missing_returns_false(tmp_path):
    assert uninstall_plugin("ghost", plugins_dir=tmp_path / "plugins") is False


def test_list_installed_empty_when_missing(tmp_path):
    assert list_installed(plugins_dir=tmp_path / "nope") == []


def test_validate_plugin_directory_rejects_missing_dir(tmp_path):
    with pytest.raises(InstallError, match="Not a directory"):
        validate_plugin_directory(tmp_path / "missing")


def test_resolve_plugins_dir_override_and_default(tmp_path):
    assert resolve_plugins_dir(tmp_path / "x") == tmp_path / "x"
    assert resolve_plugins_dir(None) == Path(Settings().plugin_dir)


def test_settings_plugin_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SAMAKTHA_PLUGIN_DIR", str(tmp_path / "env"))
    assert Settings().plugin_dir == str(tmp_path / "env")


# --------------------------------------------------------------------------- #
# PluginHarness
# --------------------------------------------------------------------------- #


def test_harness_fresh_registries(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    harness = PluginHarness(plugin_dir=src)
    try:
        assert isinstance(harness.keys(), list)
        assert "greeter@1.0.0" in harness.keys()
    finally:
        harness.cleanup()


def test_harness_unload_removes_contributions(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    harness = PluginHarness(plugin_dir=src)
    try:
        asyncio.run(harness.load("greeter@1.0.0"))
        assert harness.tool_registry.has_tool("greeter")
        assert harness.is_loaded("greeter@1.0.0")

        asyncio.run(harness.unload("greeter@1.0.0"))
        assert not harness.tool_registry.has_tool("greeter")
        assert not harness.is_loaded("greeter@1.0.0")
    finally:
        harness.cleanup()


def test_harness_cleanup_removes_sys_path(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    harness = PluginHarness(plugin_dir=src)
    assert str(src) in sys.path
    harness.cleanup()
    assert str(src) not in sys.path


def test_harness_load_sync(tmp_path):
    src = scaffold_plugin("greeter", kind="tool", output_dir=tmp_path)
    harness = PluginHarness(plugin_dir=src)
    try:
        record = harness.load_sync("greeter@1.0.0")
        assert record.state.value == "active"
    finally:
        harness.cleanup()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_new_and_validate(tmp_path, capsys):
    assert main(["new", "cli_demo", "--dir", str(tmp_path), "--author", "CLI"]) == 0
    captured = capsys.readouterr().out
    assert "cli_demo" in captured

    target = tmp_path / "cli_demo"
    assert (target / "manifest.json").exists()

    assert main(["validate", str(target)]) == 0
    assert "OK: cli_demo@1.0.0" in capsys.readouterr().out


def test_cli_validate_invalid_returns_1(tmp_path, capsys):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text(
        json.dumps({"id": "x", "version": "abc", "entry": "nope"}), encoding="utf-8"
    )
    assert main(["validate", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err or "error:" in capsys.readouterr().out


def test_cli_install_list_uninstall_roundtrip(tmp_path, capsys):
    src = scaffold_plugin("cli_demo", kind="tool", output_dir=tmp_path)
    plugins_dir = tmp_path / "plugins"

    assert main(["install", str(src), "--plugins-dir", str(plugins_dir)]) == 0

    assert main(["list", "--plugins-dir", str(plugins_dir)]) == 0
    assert "cli_demo@1.0.0" in capsys.readouterr().out

    assert main(["uninstall", "cli_demo", "--plugins-dir", str(plugins_dir)]) == 0

    assert main(["list", "--plugins-dir", str(plugins_dir)]) == 0
    assert "No plugins installed" in capsys.readouterr().out


def test_cli_duplicate_install_returns_1(tmp_path, capsys):
    src = scaffold_plugin("cli_demo", kind="tool", output_dir=tmp_path)
    plugins_dir = tmp_path / "plugins"
    assert main(["install", str(src), "--plugins-dir", str(plugins_dir)]) == 0
    assert main(["install", str(src), "--plugins-dir", str(plugins_dir)]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_uninstall_missing_returns_1(tmp_path, capsys):
    assert main(["uninstall", "ghost", "--plugins-dir", str(tmp_path / "plugins")]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_new_rejects_bad_kind(tmp_path):
    with pytest.raises(SystemExit):
        main(["new", "demo", "--kind", "gadget", "--dir", str(tmp_path)])


def test_cli_test_runs_scaffolded_suite(tmp_path):
    src = scaffold_plugin("cli_demo", kind="tool", output_dir=tmp_path)
    assert main(["test", str(src)]) == 0


def test_cli_test_without_tests_returns_1(tmp_path, capsys):
    plugin = tmp_path / "bare"
    plugin.mkdir()
    (plugin / "manifest.json").write_text(
        json.dumps({"id": "bare", "version": "1.0.0", "entry": "bare"}), encoding="utf-8"
    )
    assert main(["test", str(plugin)]) == 1
    assert "tests/" in capsys.readouterr().err


def test_build_parser_exposes_expected_subcommands():
    parser = build_parser()
    choices = {action.dest: action.choices for action in parser._actions}
    assert "new" in choices or any(a.dest == "command" for a in parser._actions)


# --------------------------------------------------------------------------- #
# Example plugins
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "key"),
    [("hello", "hello@1.0.0"), ("wordbox", "wordbox@1.0.0"), ("health_probe", "health_probe@1.0.0")],
)
def test_examples_validate(name, key):
    _manifest, result = validate_plugin_directory(EXAMPLES / name)
    assert result.valid, result.errors


def test_example_hello_plugin():
    harness = PluginHarness(plugin_dir=EXAMPLES / "hello")
    try:
        record = asyncio.run(harness.load("hello@1.0.0"))
        assert record.state.value == "active"
        assert harness.tool_registry.has_tool("hello")
        tool = harness.tool_registry.get_tool("hello")
        result = asyncio.run(tool.run({"who": "Samaktha"}))
        assert result.data["greeting"] == "Hello, Samaktha!"
    finally:
        harness.cleanup()


def test_example_wordbox_tool():
    harness = PluginHarness(plugin_dir=EXAMPLES / "wordbox")
    try:
        record = asyncio.run(harness.load("wordbox@1.0.0"))
        assert record.state.value == "active"
        tool = harness.tool_registry.get_tool("wordbox")
        result = asyncio.run(tool.run({"text": "one two three"}))
        assert result.data == {"words": 3, "characters": 13}
    finally:
        harness.cleanup()


def test_example_health_probe_provider():
    harness = PluginHarness(plugin_dir=EXAMPLES / "health_probe")
    try:
        record = asyncio.run(harness.load("health_probe@1.0.0"))
        assert record.state.value == "active"
        assert harness.communication_registry.has_provider("health_probe")
        provider = harness.communication_registry.get_provider("health_probe")
        assert asyncio.run(provider.health()) is True
    finally:
        harness.cleanup()
