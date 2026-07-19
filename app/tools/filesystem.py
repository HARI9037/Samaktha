import os
from pathlib import Path
from typing import Any, Dict

from app.tools.base import Tool, ToolResult


class FileSystemTool(Tool):
    """Tool for securely interacting with a sandboxed file system directory."""

    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir).resolve()
        
        # Ensure root_dir exists
        self._root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "filesystem"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action")
        path_str = arguments.get("path")

        if not action or path_str is None:
            return ToolResult(ok=False, error="Missing required arguments 'action' or 'path'.")

        try:
            target_path = (self._root_dir / path_str).resolve()
            
            # Prevent path traversal
            if not target_path.is_relative_to(self._root_dir):
                return ToolResult(ok=False, error="Path traversal attempt blocked.")

            if action == "read_file":
                return self._read_file(target_path)
            elif action == "write_file":
                content = arguments.get("content", "")
                return self._write_file(target_path, content)
            elif action == "list_directory":
                return self._list_directory(target_path)
            else:
                return ToolResult(ok=False, error=f"Unsupported action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    def _read_file(self, target_path: Path) -> ToolResult:
        if not target_path.is_file():
            return ToolResult(ok=False, error="File does not exist or is not a file.")
        content = target_path.read_text(encoding="utf-8")
        return ToolResult(ok=True, data={"content": content})

    def _write_file(self, target_path: Path, content: str) -> ToolResult:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return ToolResult(ok=True)

    def _list_directory(self, target_path: Path) -> ToolResult:
        if not target_path.is_dir():
            return ToolResult(ok=False, error="Directory does not exist or is not a directory.")
        files = []
        for item in target_path.iterdir():
            files.append({
                "name": item.name,
                "is_dir": item.is_dir(),
            })
        return ToolResult(ok=True, data={"files": files})
