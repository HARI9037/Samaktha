"""WordBox — example Samaktha tool plugin.

A tiny tool-only plugin: it contributes a single ``Tool`` that counts words
and characters. See docs/PLUGINS.md for the plugin author guide.
"""

from __future__ import annotations

from app.plugins import Plugin
from app.plugins.models import PluginCapability, PluginManifest, PluginPermission
from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy


class WordBoxTool(Tool):
    name = "wordbox"

    category = ToolCategory.PRODUCTIVITY
    capabilities = ["wordbox"]
    policy = ToolPolicy(
        permissions=(ToolPermission.READ,),
        description="Counts words and characters in supplied text.",
    )

    async def run(self, arguments):
        text = arguments.get("text", "")
        words = len([part for part in text.split() if part])
        return ToolResult(
            ok=True,
            data={"words": words, "characters": len(text)},
        )


MANIFEST = PluginManifest(
    id="wordbox",
    name="WordBox Example Tool",
    version="1.0.0",
    kind="tool",
    description="Example tool: counts words and characters in supplied text.",
    author="Samaktha Team",
    entry="wordbox",
    capabilities=[PluginCapability(name="wordbox", description="Counts words and characters in text.")],
    permissions=[PluginPermission(scope="read", description="Read-only text analysis.")],
)


class WordBoxPlugin(Plugin):
    @property
    def manifest(self):
        return MANIFEST

    def provide_tools(self):
        return [WordBoxTool()]


def create_plugin():
    return WordBoxPlugin()
