"""``samaktha-plugin`` CLI (P2.2 Plugin SDK).

Console entry point registered in ``pyproject.toml``:

    samaktha-plugin new <name> [--kind tool|provider|skill|personality]
    samaktha-plugin install <plugin-dir> [--plugins-dir DIR]
    samaktha-plugin uninstall <plugin-id> [--plugins-dir DIR]
    samaktha-plugin list [--plugins-dir DIR]
    samaktha-plugin validate <plugin-dir>
    samaktha-plugin test <plugin-dir>

All validation and installation flows are shared with ``app.plugins.sdk`` —
the CLI never bypasses manifest validation or the plugin architecture.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from app.plugins.sdk import (
    install_plugin,
    list_installed,
    resolve_plugins_dir,
    scaffold_plugin,
    uninstall_plugin,
    validate_plugin_directory,
)
from app.plugins.sdk.scaffold import ScaffoldError

_KIND_CHOICES = ("tool", "provider", "skill", "personality")


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _run_tests(path: str, plugins_dir: str | None) -> int:
    plugin_dir = Path(path).resolve()
    if not plugin_dir.is_dir():
        return _fail(f"Not a directory: {plugin_dir}")
    tests_dir = plugin_dir / "tests"
    if not tests_dir.exists():
        return _fail(f"No tests/ directory found in {plugin_dir}")
    env = dict(os.environ)
    pythonpath_bits = [str(plugin_dir)]
    if plugins_dir:
        pythonpath_bits.append(str(resolve_plugins_dir(plugins_dir)))
    existing = env.get("PYTHONPATH", "")
    if existing:
        pythonpath_bits.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_bits)
    # Run with the SDK's interpreter and keep pytest discovery inside the
    # plugin root.  In particular, do not inherit an unrelated user-site
    # pytest or let rootdir discovery climb through a shared temp hierarchy.
    env["PYTHONNOUSERSITE"] = "1"
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(tests_dir.resolve()),
        "--rootdir",
        str(plugin_dir),
        "-p",
        "no:cacheprovider",
        "-q",
    ]
    return subprocess.call(command, env=env, cwd=plugin_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="samaktha-plugin",
        description="Samaktha plugin SDK — scaffold, install, validate, test and list plugins.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="scaffold a new plugin directory")
    new.add_argument("name")
    new.add_argument("--kind", choices=_KIND_CHOICES, default="tool")
    new.add_argument("--dir", default=".", help="output directory (default: current)")
    new.add_argument("--author", default="")
    new.add_argument("--description", default="")
    new.add_argument("--version", default="1.0.0")

    install = subparsers.add_parser("install", help="install a plugin locally")
    install.add_argument("source", help="path to the plugin directory")
    install.add_argument("--plugins-dir", default=None)
    install.add_argument("--force", action="store_true", help="overwrite an existing install")

    uninstall = subparsers.add_parser("uninstall", help="remove an installed plugin")
    uninstall.add_argument("plugin_id")
    uninstall.add_argument("--plugins-dir", default=None)

    list_cmd = subparsers.add_parser("list", help="list installed plugins")
    list_cmd.add_argument("--plugins-dir", default=None)

    validate_cmd = subparsers.add_parser("validate", help="validate a plugin directory")
    validate_cmd.add_argument("path")
    validate_cmd.add_argument("--plugins-dir", default=None)

    test_cmd = subparsers.add_parser("test", help="run a plugin's pytest suite")
    test_cmd.add_argument("path")
    test_cmd.add_argument("--plugins-dir", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:])
    namespace = build_parser().parse_args(args)

    if namespace.command == "new":
        try:
            path = scaffold_plugin(
                namespace.name,
                kind=namespace.kind,
                output_dir=namespace.dir,
                author=namespace.author,
                description=namespace.description,
                version=namespace.version,
            )
        except ScaffoldError as exc:
            return _fail(str(exc))
        print(f"Created plugin at {path}")
        return 0

    if namespace.command == "install":
        try:
            dest = install_plugin(
                namespace.source,
                plugins_dir=namespace.plugins_dir,
                force=namespace.force,
            )
        except Exception as exc:  # noqa: BLE001 - CLI surface
            return _fail(str(exc))
        print(f"Installed {dest.name} -> {dest}")
        return 0

    if namespace.command == "uninstall":
        if not uninstall_plugin(namespace.plugin_id, plugins_dir=namespace.plugins_dir):
            return _fail(f"Plugin not installed: {namespace.plugin_id}")
        print(f"Uninstalled {namespace.plugin_id}")
        return 0

    if namespace.command == "list":
        root = resolve_plugins_dir(namespace.plugins_dir)
        installed = list_installed(plugins_dir=namespace.plugins_dir)
        if not installed:
            print(f"No plugins installed in {root}")
            return 0
        print(f"Installed plugins in {root}:")
        for _directory, manifest in installed:
            print(f"  {manifest.key}  ({manifest.kind.value})  entry={manifest.entry}")
        return 0

    if namespace.command == "validate":
        try:
            manifest, result = validate_plugin_directory(namespace.path)
        except Exception as exc:  # noqa: BLE001 - CLI surface
            return _fail(str(exc))
        for error in result.errors:
            print(f"error: {error}")
        for warning in result.warnings:
            print(f"warning: {warning}")
        if not result.valid:
            return 1
        print(f"OK: {manifest.key} ({manifest.kind.value})")
        return 0

    if namespace.command == "test":
        return _run_tests(namespace.path, namespace.plugins_dir)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
