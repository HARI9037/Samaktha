"""Hello — example Samaktha tool plugin.

Demonstrates the full plugin lifecycle: a contributed tool plus ``start``
and ``stop`` hooks. See docs/PLUGINS.md for the plugin author guide.
"""

from __future__ import annotations

from app.plugins import Plugin
from app.plugins.models import PluginCapability, PluginManifest, PluginPermission
from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy


class HelloTool(Tool):
    name = "hello"

    category = ToolCategory.PRODUCTIVITY
    capabilities = ["hello"]
    policy = ToolPolicy(
        permissions=(ToolPermission.READ,),
        description="Greets the caller and echoes the message.",
    )

    async def run(self, arguments):
        who = arguments.get("who", "world")
        return ToolResult(ok=True, data={"greeting": f"Hello, {who}!"})


MANIFEST = PluginManifest(
    id="hello",
    name="Hello Example Plugin",
    version="1.0.0",
    kind="tool",
    description="Example plugin: greets the caller and demonstrates the plugin lifecycle.",
    author="Samaktha Team",
    entry="hello",
    capabilities=[PluginCapability(name="hello", description="Greets the caller.")],
    permissions=[PluginPermission(scope="read", description="Read-only greeting.")],
)


class HelloPlugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_tools(self):
        return [HelloTool()]

    async def start(self, context):
        self.greetings_sent = 0

    async def stop(self):
        pass


def create_plugin():
    return HelloPlugin()
