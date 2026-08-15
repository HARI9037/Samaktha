"""P2.2 — Plugin SDK.

Tooling for authoring, installing, validating, testing and documenting
Samaktha plugins: a ``samaktha-plugin`` CLI, scaffolding/templates, local
installation into the configured plugin directory, and pytest test
utilities. The SDK builds entirely on the P2.1 plugin architecture — it
never bypasses validation, dependency resolution or the isolation
boundaries enforced by ``app.plugins``.
"""

from app.plugins.sdk.install import (
    InstallError,
    install_plugin,
    list_installed,
    resolve_plugins_dir,
    uninstall_plugin,
    validate_plugin_directory,
)
from app.plugins.sdk.scaffold import (
    ScaffoldError,
    scaffold_plugin,
    template_module_name,
    template_plugin_id,
)
from app.plugins.sdk.testing import PluginHarness

__all__ = [
    "InstallError",
    "PluginHarness",
    "ScaffoldError",
    "install_plugin",
    "list_installed",
    "resolve_plugins_dir",
    "scaffold_plugin",
    "template_module_name",
    "template_plugin_id",
    "uninstall_plugin",
    "validate_plugin_directory",
]
