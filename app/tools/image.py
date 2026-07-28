import os
from pathlib import Path
from typing import Any, Dict

from app.tools.base import Tool, ToolResult
from app.tools.resolver import FileResolver, MultipleMatches

class ImageTool(Tool):
    """Tool for image analysis and metadata extraction."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self._resolver = FileResolver(root_dir)

    @property
    def name(self) -> str:
        return "image"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "analyze")
        path_str = arguments.get("path") or arguments.get("target_path")

        if not path_str:
            return ToolResult(ok=False, error="Missing required argument 'path'")

        resolved = self._resolver.resolve(path_str)
        if isinstance(resolved, MultipleMatches):
            return ToolResult(
                ok=False,
                error="MULTIPLE_MATCHES",
                data={"candidates": resolved.candidates},
            )
        if resolved is None:
            return ToolResult(ok=False, error="Resource not found.")
        target_path = resolved

        if not target_path.exists():
            return ToolResult(ok=False, error=f"Image file does not exist: {target_path}")

        # Note: True image analysis requires a vision model capability,
        # which isn't wired in this mock version. We simulate success if the file exists.
        return ToolResult(
            ok=True,
            data={
                "path": str(target_path),
                "metadata": {
                    "size_bytes": target_path.stat().st_size,
                    "format": target_path.suffix.lstrip(".").upper()
                },
                "vision_analysis": "Simulated vision analysis: The image shows a sample content."
            }
        )
