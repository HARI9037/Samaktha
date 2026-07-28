import os
import shutil
from pathlib import Path
from typing import Any, Dict

from app.tools.base import Tool, ToolResult
from app.tools.document import DocumentTool, is_document_file
from app.tools.resolver import FileResolver, MultipleMatches


class FileSystemTool(Tool):
    """Tool for local filesystem operations (exists, read, write, list, search, copy, move, delete, mkdir)."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        if root_dir:
            self._root_dir = Path(root_dir).resolve()
            self._root_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._root_dir = None
        self._resolver = FileResolver(root_dir)
        from app.memory.resources import ResourceRegistry
        self._registry = ResourceRegistry()
        self._document_tool = DocumentTool(root_dir)

    @property
    def name(self) -> str:
        return "filesystem"

    def _resolve(self, path_str: str) -> Path | MultipleMatches:
        return self._resolver.resolve(path_str)

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "read")
        path_str = arguments.get("path") or arguments.get("target_path") or "."
        path_str = path_str.strip().strip('"').strip("'")

        try:
            resolved = self._resolve(path_str)
            if resolved is None:
                return ToolResult(ok=False, error="Resource no longer exists.")
            if isinstance(resolved, MultipleMatches):
                return ToolResult(
                    ok=False, 
                    error="MULTIPLE_MATCHES", 
                    data={"candidates": resolved.candidates}
                )
            target_path = resolved

            if action == "remember":
                if not Path(path_str).is_absolute():
                    # Only explicit absolute paths can be 'remembered' without actually reading them
                    return ToolResult(ok=False, error="The 'remember' action requires an absolute path.")
                self._registry.register(target_path)
                return ToolResult(ok=True, data={"remembered": str(target_path)})

            # Security: reject path traversal outside root_dir before any filesystem access
            if self._root_dir is not None:
                try:
                    target_path.relative_to(self._root_dir)
                except ValueError:
                    return ToolResult(ok=False, error="Path traversal detected.")

            # The remainder of the standard actions
            result = None
            if action in ("exists", "check_exists"):
                result = ToolResult(ok=True, data={"exists": target_path.exists(), "path": str(target_path)})

            elif action in ("read", "read_file"):
                if not target_path.exists():
                    return ToolResult(ok=False, error="File not found.")
                if target_path.is_dir():
                    return ToolResult(ok=False, error="Target is a directory. Use Browse.")
                if not target_path.is_file():
                    return ToolResult(ok=False, error="File not found.")
                
                if is_document_file(target_path):
                    doc_result = await self._document_tool.run({
                        "action": "read_document",
                        "path": str(target_path),
                    })
                    if doc_result.ok:
                        data = doc_result.data.get("result", doc_result.data)
                        text_content = data.get("text", "")
                        return ToolResult(
                            ok=True,
                            data={
                                "path": data.get("path", str(target_path)),
                                "content": text_content,
                                "size": len(text_content),
                                "title": data.get("title"),
                                "page_count": data.get("page_count", 0),
                                "sections": data.get("sections", []),
                                "tables": data.get("tables", []),
                                "images": data.get("images", []),
                                "metadata": data.get("metadata", {}),
                            }
                        )
                    return doc_result
                
                content = target_path.read_text(encoding="utf-8", errors="replace")
                result = ToolResult(ok=True, data={"path": str(target_path), "content": content, "size": len(content)})

            elif action in ("write", "write_file"):
                content = arguments.get("content", "")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                result = ToolResult(ok=True, data={"path": str(target_path), "written_bytes": len(content)})

            elif action in ("list", "list_directory", "ls", "dir"):
                if not target_path.exists():
                    return ToolResult(ok=False, error=f"Directory does not exist: {target_path}")
                if not target_path.is_dir():
                    return ToolResult(ok=False, error=f"Target is not a directory: {target_path}")
                items = []
                for item in target_path.iterdir():
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "folder" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else 0,
                    })
                result = ToolResult(ok=True, data={"path": str(target_path), "items": items, "count": len(items)})

            elif action == "search":
                pattern = arguments.get("pattern", "*")
                if not target_path.is_dir():
                    target_path = target_path.parent
                matches = [str(p) for p in target_path.rglob(pattern)]
                result = ToolResult(ok=True, data={"matches": matches[:100], "count": len(matches)})

            elif action == "copy":
                destination = arguments.get("destination")
                if not destination:
                    return ToolResult(ok=False, error="Missing required argument 'destination'")
                destination = destination.strip().strip('"').strip("'")
                dest_resolved = self._resolve(destination)
                if dest_resolved is None:
                    return ToolResult(ok=False, error="Resource no longer exists (destination).")
                if isinstance(dest_resolved, MultipleMatches):
                    return ToolResult(
                        ok=False, 
                        error="MULTIPLE_MATCHES", 
                        data={"candidates": dest_resolved.candidates}
                    )
                dest_path = dest_resolved
                
                if target_path.is_dir():
                    shutil.copytree(target_path, dest_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(target_path, dest_path)
                result = ToolResult(ok=True, data={"source": str(target_path), "destination": str(dest_path)})

            elif action == "move":
                destination = arguments.get("destination")
                if not destination:
                    return ToolResult(ok=False, error="Missing required argument 'destination'")
                destination = destination.strip().strip('"').strip("'")
                dest_resolved = self._resolve(destination)
                if dest_resolved is None:
                    return ToolResult(ok=False, error="Resource no longer exists (destination).")
                if isinstance(dest_resolved, MultipleMatches):
                    return ToolResult(
                        ok=False, 
                        error="MULTIPLE_MATCHES", 
                        data={"candidates": dest_resolved.candidates}
                    )
                dest_path = dest_resolved
                
                shutil.move(str(target_path), str(dest_path))
                result = ToolResult(ok=True, data={"source": str(target_path), "destination": str(dest_path)})

            elif action == "delete":
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                elif target_path.exists():
                    target_path.unlink()
                result = ToolResult(ok=True, data={"deleted": str(target_path)})

            elif action == "mkdir":
                target_path.mkdir(parents=True, exist_ok=True)
                result = ToolResult(ok=True, data={"created": str(target_path)})

            else:
                return ToolResult(ok=False, error=f"Unsupported filesystem action: {action}")
                
            # If operation succeeded and the user supplied an absolute path, remember it automatically
            if result and result.ok:
                if Path(path_str).is_absolute():
                    self._registry.register(target_path)
                    
            return result

        except Exception as e:
            return ToolResult(ok=False, error=str(e))
