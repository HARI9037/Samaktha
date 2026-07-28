import os
import logging
from pathlib import Path
from typing import Any, Dict, Protocol

from app.tools.base import Tool, ToolResult

DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".markdown", ".html", ".htm"}

logger = logging.getLogger(__name__)

class ToolRegistryProtocol(Protocol):
    def get_tool(self, tool_id: str) -> Tool | None:
        ...

class ResolverTool(Tool):
    """Dynamically resolves a semantic resource to the appropriate tool based on file type."""

    def __init__(self, registry: ToolRegistryProtocol) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "resolver"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "read")
        path_str = arguments.get("path") or arguments.get("target_path") or "."
        
        # 1. Determine tool based on path and action
        target_tool = "filesystem"
        ext = ""
        
        # Accommodate upstream misclassification of reads as list_directory for absolute paths
        if action in ("read", "extract_text", "analyze", "list", "list_directory", "ls", "dir", "summarize", "read_document"):
            # Check extension
            p = str(path_str).lower()
            p = p.strip().strip('"').strip("'")
            ext = Path(p).suffix
            
            if ext in DOCUMENT_EXTENSIONS:
                target_tool = "document"
                if action in ("read", "read_document", "extract_text"):
                    arguments["action"] = "read_document"
                elif action == "summarize":
                    arguments["action"] = "summarize_document"
            elif ext in (".png", ".jpg", ".jpeg", ".webp"):
                target_tool = "image"
                arguments["action"] = "analyze"
        
        logger.info("ResolverTool: routing — path=%s ext=%s target_tool=%s action=%s", path_str, ext, target_tool, arguments.get("action"))

        # 2. Get the resolved tool
        tool = self._registry.get_tool(target_tool)
        logger.info("ResolverTool: got tool=%s from registry", tool.__class__.__name__ if tool else None)
        if not tool:
            return ToolResult(
                ok=False, 
                error=f"Capability not installed. Required capability: {target_tool.capitalize()} Tool"
            )
            
        # 4. Delegate execution
        try:
            return await tool.run(arguments)
        except Exception as e:
            logger.warning("Resolver tool execution error: %s", e)
            return ToolResult(ok=False, error="Tool execution failed.")
