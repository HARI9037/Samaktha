"""Plugin scaffolding and development templates (P2.2 Plugin SDK).

``scaffold_plugin`` generates a complete, valid plugin directory — manifest,
entry module, a runnable test and a README — for any plugin kind. Every
scaffolded artifact is validated by the P2.1 plugin architecture before it
is written, so a new project is guaranteed to load.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from string import Template

from app.plugins.models import PluginManifest
from app.plugins.validation import validate_manifest

_KIND_CHOICES = ("tool", "provider", "skill", "personality")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9._-]*$")


class ScaffoldError(RuntimeError):
    """Raised when a plugin cannot be scaffolded."""


def template_plugin_id(name: str) -> str:
    """Derive a manifest-safe plugin id from a display name."""
    value = re.sub(r"[^a-z0-9._-]+", "-", (name or "").strip().lower())
    value = value.strip(".-_")
    return value or ""


def template_module_name(plugin_id: str) -> str:
    """Derive the entry module name for a plugin id."""
    return plugin_id.replace("-", "_").replace(".", "_")


def _class_name(plugin_id: str) -> str:
    parts = template_module_name(plugin_id).split("_")
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


_TOOL_MODULE_TEMPLATE = Template(
    '''"""{name} — a Samaktha tool plugin.

Scaffolded by ``samaktha-plugin new``. See docs/PLUGINS.md for the plugin
author guide.
"""

from app.plugins import Plugin
from app.plugins.models import PluginCapability, PluginManifest, PluginPermission
from app.tools.base import Tool, ToolResult
from app.tools.framework.models import ToolPermission, ToolPolicy
from app.tools.framework.capabilities import ToolCategory


class ${ClassName}Tool(Tool):
    name = "$tool_name"

    category = ToolCategory.PRODUCTIVITY
    capabilities = ["$capability"]
    policy = ToolPolicy(
        permissions=(ToolPermission.READ,),
        description="Greets the caller.",
    )

    async def run(self, arguments):
        who = arguments.get("who", "world")
        return ToolResult(ok=True, data={"greeting": "Hello, " + who + "!"})


MANIFEST = PluginManifest(
    id="$id",
    name="$name",
    version="$version",
    kind="tool",
    description="$description",
    author="$author",
    entry="$module",
    capabilities=[PluginCapability(name="$capability", description="Greets the caller.")],
    permissions=[PluginPermission(scope="read", description="Read-only greeting.")],
)


class ${ClassName}Plugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_tools(self):
        return [${ClassName}Tool()]


def create_plugin():
    return ${ClassName}Plugin()
'''
)

_PROVIDER_MODULE_TEMPLATE = Template(
    '''"""{name} — a Samaktha provider plugin.

Scaffolded by ``samaktha-plugin new``. See docs/PLUGINS.md for the plugin
author guide.
"""

from app.plugins import Plugin
from app.plugins.models import PluginManifest
from app.communication.models import (
    CommunicationProvider as CommunicationProviderEnum,
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
)
from app.communication.provider import CommunicationProvider


class ${ClassName}Provider(CommunicationProvider):
    provider_id = "$provider_id"

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def send(self, request):
        return CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProviderEnum.TEST,
        )

    async def receive(self, limit=10):
        return []

    async def health(self):
        return True

    async def validate(self, request):
        return []


MANIFEST = PluginManifest(
    id="$id",
    name="$name",
    version="$version",
    kind="provider",
    description="$description",
    author="$author",
    entry="$module",
)


class ${ClassName}Plugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_providers(self):
        return [${ClassName}Provider()]


def create_plugin():
    return ${ClassName}Plugin()
'''
)

_MINIMAL_MODULE_TEMPLATE = Template(
    '''"""{name} — a Samaktha $kind plugin.

Scaffolded by ``samaktha-plugin new``. See docs/PLUGINS.md for the plugin
author guide.
"""

from app.plugins import Plugin
from app.plugins.models import PluginManifest


MANIFEST = PluginManifest(
    id="$id",
    name="$name",
    version="$version",
    kind="$kind",
    description="$description",
    author="$author",
    entry="$module",
)


class ${ClassName}Plugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST


def create_plugin():
    return ${ClassName}Plugin()
'''
)

_TEST_TEMPLATE = Template(
    '''"""Tests for the $id plugin (scaffolded by ``samaktha-plugin new``)."""

import asyncio
from pathlib import Path

from app.plugins.sdk.testing import PluginHarness


def test_plugin_loads():
    harness = PluginHarness(plugin_dir=Path(__file__).parent.parent)
    try:
        record = asyncio.run(harness.load("$id@$version"))
        assert record.state.value == "active"
$asserts
    finally:
        harness.cleanup()
'''
)

_README_TEMPLATE = Template(
    '''# $name

$description

A $kind plugin for Samaktha ($id@$version). See [docs/PLUGINS.md](../../docs/PLUGINS.md)
for the plugin author guide.

## Layout

- `manifest.json` — canonical plugin declaration
- `$module.py` — entry module exposing `create_plugin()`
- `tests/` — pytest suite using the SDK testing utilities

## Development

```bash
samaktha-plugin validate .
samaktha-plugin test .
```
'''
)


def _manifest_dict(
    plugin_id: str,
    name: str,
    version: str,
    kind: str,
    description: str,
    author: str,
    module: str,
) -> dict:
    manifest: dict = {
        "schema_version": "1.0",
        "id": plugin_id,
        "name": name,
        "version": version,
        "kind": kind,
        "description": description,
        "author": author,
        "entry": module,
        "capabilities": [],
        "permissions": [],
        "dependencies": [],
    }
    if kind == "tool":
        manifest["capabilities"] = [
            {"name": plugin_id, "description": "Greets the caller."}
        ]
        manifest["permissions"] = [{"scope": "read", "description": "Read-only greeting."}]
    return manifest


def scaffold_plugin(
    name: str,
    *,
    kind: str = "tool",
    output_dir: str | Path = ".",
    author: str = "",
    description: str = "",
    version: str = "1.0.0",
) -> Path:
    """Scaffold a complete plugin directory; returns its path."""
    kind = kind or "tool"
    if kind not in _KIND_CHOICES:
        raise ScaffoldError(f"Unknown plugin kind {kind!r}; choose from {sorted(_KIND_CHOICES)}.")

    plugin_id = template_plugin_id(name)
    if not plugin_id:
        raise ScaffoldError("Plugin name must contain at least one letter or digit.")
    if not _IDENTIFIER.match(plugin_id):
        raise ScaffoldError(f"Name {name!r} produces an invalid plugin id {plugin_id!r}.")

    module = template_module_name(plugin_id)
    class_name = _class_name(plugin_id)

    target = Path(output_dir) / plugin_id
    if target.exists():
        raise ScaffoldError(f"Directory already exists: {target}")

    manifest_data = _manifest_dict(
        plugin_id, name.strip() or plugin_id, version, kind, description.strip(), author.strip(), module
    )
    manifest = PluginManifest.model_validate(manifest_data)
    validation = validate_manifest(manifest)
    if not validation.valid:
        raise ScaffoldError("Scaffolded manifest is invalid: " + "; ".join(validation.errors))

    if kind == "tool":
        module_source = _TOOL_MODULE_TEMPLATE.substitute(
            id=plugin_id, name=name.strip() or plugin_id, version=version,
            description=description.strip(), author=author.strip(), module=module,
            ClassName=class_name, tool_name=plugin_id, capability=plugin_id,
        )
        asserts = f'        assert harness.tool_registry.has_tool("{plugin_id}")'
    elif kind == "provider":
        module_source = _PROVIDER_MODULE_TEMPLATE.substitute(
            id=plugin_id, name=name.strip() or plugin_id, version=version,
            description=description.strip(), author=author.strip(), module=module,
            ClassName=class_name, provider_id=plugin_id,
        )
        asserts = f'        assert harness.communication_registry.has_provider("{plugin_id}")'
    else:
        module_source = _MINIMAL_MODULE_TEMPLATE.substitute(
            id=plugin_id, name=name.strip() or plugin_id, version=version,
            kind=kind, description=description.strip(), author=author.strip(),
            module=module, ClassName=class_name,
        )
        asserts = "        pass  # minimal plugin contributes nothing yet"

    tests_source = _TEST_TEMPLATE.substitute(
        id=plugin_id, version=version, asserts=asserts
    )
    readme_source = _README_TEMPLATE.substitute(
        name=name.strip() or plugin_id, description=description.strip() or "A Samaktha plugin.",
        kind=kind, id=plugin_id, version=version, module=module,
    )

    target.mkdir(parents=True)
    (target / "manifest.json").write_text(
        json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8"
    )
    (target / f"{module}.py").write_text(module_source, encoding="utf-8")
    (target / "tests").mkdir()
    (target / "tests" / f"test_{module}.py").write_text(tests_source, encoding="utf-8")
    (target / "README.md").write_text(readme_source, encoding="utf-8")
    return target
