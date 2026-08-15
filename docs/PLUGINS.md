# Samaktha Plugin Guide

Samaktha plugins extend the framework with **tools** (new capabilities a
user can invoke), **providers** (communication channels), **skills** and
**personalities**. Plugins are first-class citizens: they declare their
identity, dependencies, capabilities and permissions up front, and the
runtime loads them only after validation — through the exact same
CAP/security pipeline as system tools.

This guide covers the P2.1 plugin architecture and the P2.2 `samaktha-plugin`
SDK.

## Quick start

```bash
# Scaffold a plugin
samaktha-plugin new my_tool --kind tool --author "Your Name" --description "Does something useful"

# Work on it
cd my_tool
samaktha-plugin validate .      # manifest + structure checks
samaktha-plugin test .          # run the scaffolded pytest suite

# Install it locally
samaktha-plugin install .       # copies into $SAMAKTHA_PLUGIN_DIR (default samaktha_plugins/)
samaktha-plugin list
samaktha-plugin uninstall my_tool
```

## Anatomy of a plugin

A plugin is a directory containing:

```
my_tool/
├── manifest.json       # canonical declaration (the Plugin specification)
├── my_tool.py          # entry module exposing create_plugin()
├── tests/              # pytest suite using the SDK testing utilities
└── README.md
```

### manifest.json

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | no | Manifest schema ("1.0"). |
| `id` | yes | Lowercase identifier `[a-z][a-z0-9._-]*`. Becomes `id@version`. |
| `name` | yes | Human-readable name. |
| `version` | no | Strict semver `MAJOR.MINOR.PATCH` (default `1.0.0`). |
| `kind` | no | `tool`, `provider`, `skill` or `personality` (default `tool`). |
| `description` | no | One-line description. |
| `author` | no | Plugin author. |
| `entry` | yes | Importable module path that exposes the plugin. |
| `dependencies` | no | List of `{plugin_id, version}` the plugin requires. |
| `capabilities` | no | List of `{name, description}` domains the plugin provides. |
| `permissions` | no | List of `{scope, description}`; scope must be a `ToolPermission` (`read`, `write`, `modify`, `delete`, `execute`, `network`, `admin`). |

```json
{
  "schema_version": "1.0",
  "id": "my_tool",
  "name": "My Tool",
  "version": "1.0.0",
  "kind": "tool",
  "description": "Does something useful.",
  "author": "Your Name",
  "entry": "my_tool",
  "dependencies": [],
  "capabilities": [{ "name": "my_tool", "description": "Does the thing." }],
  "permissions": [{ "scope": "read", "description": "Read-only operation." }]
}
```

### Entry module

The entry module must expose one of:

1. a `create_plugin()` factory returning a `Plugin` instance (preferred);
2. a module-level `plugin` instance;
3. a `Plugin` subclass.

A `Plugin` subclass declares its manifest and may contribute tools and
providers. Lifecycle hooks are optional no-ops.

```python
from app.plugins import Plugin
from app.plugins.models import PluginCapability, PluginManifest, PluginPermission
from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy


class MyTool(Tool):
    name = "my_tool"
    category = ToolCategory.PRODUCTIVITY
    capabilities = ["my_tool"]
    policy = ToolPolicy(permissions=(ToolPermission.READ,), description="Does the thing.")

    async def run(self, arguments):
        return ToolResult(ok=True, data={"answer": 42})


MANIFEST = PluginManifest(
    id="my_tool",
    name="My Tool",
    version="1.0.0",
    kind="tool",
    description="Does something useful.",
    entry="my_tool",
    capabilities=[PluginCapability(name="my_tool", description="Does the thing.")],
    permissions=[PluginPermission(scope="read", description="Read-only operation.")],
)


class MyPlugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_tools(self):
        return [MyTool()]


def create_plugin():
    return MyPlugin()
```

## Validation rules (the contract)

Manifest validation (`app/plugins/validation.py`) rejects:

- unsupported `schema_version`, malformed `id`, non-semver `version`;
- entry paths that are not valid dotted module paths;
- duplicate dependencies, capabilities or permissions;
- unknown permission scopes, malformed version constraints;
- declarations a plugin does not honour.

Isolation boundaries (`app/plugins/isolation.py`) refuse to load a plugin whose:

- tools are not `Tool` instances;
- providers are not `CommunicationProvider` instances;
- tools require permissions the manifest never declared;
- tools provide capabilities the manifest never declared.

These are load-time guarantees. At runtime a plugin's tools are ordinary
`Tool` instances registered in the same `ToolRegistry` the orchestrator
uses, so they flow through the identical CAP and security pipeline as every
system tool. Plugins are never granted permissions — they only declare what
their tools may require, and CAP decides.

## Dependencies

Dependencies reference other plugins by `plugin_id` with an optional semver
constraint (`*`, exact, `>=`, `^`, `~`). The manager resolves them to a
concrete installed version, prefers an already-loaded version, and loads
dependencies first. Missing or unsatisfiable constraints and dependency
cycles fail the load.

## Installing plugins

`samaktha-plugin install <dir>` validates the plugin, copies it to
`<plugins-dir>/<id>/` (default `samaktha_plugins/`, override with
`SAMAKTHA_PLUGIN_DIR` or `--plugins-dir`), and `list`/`uninstall` manage it.
Installed plugins are discovered by the runtime's plugin discovery.

## Testing plugins

The SDK ships `PluginHarness` (`app/plugins/sdk/testing.py`): a fresh
`PluginManager` wired to fresh tool/communication/capability registries,
with the plugin directory on `sys.path` so the entry module imports.

```python
import asyncio
from pathlib import Path

from app.plugins.sdk.testing import PluginHarness


def test_plugin_loads():
    harness = PluginHarness(plugin_dir=Path(__file__).parent.parent)
    try:
        record = asyncio.run(harness.load("my_tool@1.0.0"))
        assert record.state.value == "active"
        assert harness.tool_registry.has_tool("my_tool")
    finally:
        harness.cleanup()
```

`samaktha-plugin test .` runs the plugin's `tests/` suite with the plugin
directory on `PYTHONPATH`.

## Examples

Ready-to-read examples live in `examples/plugins/`:

- `hello/` — example plugin (greeting tool, lifecycle hooks, tests);
- `wordbox/` — example tool (word/character counting);
- `health_probe/` — example provider (deterministic communication provider).

## References

- `app/plugins/` — architecture (models, validation, discovery, registry,
  dependencies, isolation, manager)
- `app/plugins/sdk/` — SDK (scaffold, install, testing, CLI)
- `docs/Samaktha_Implementation_Maturity_Checklist.md` — roadmap & progress
