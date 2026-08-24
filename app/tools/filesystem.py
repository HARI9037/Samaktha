"""Bounded local filesystem tool.

All actions are validated by the same deterministic policy used at the
ToolExecutor boundary. This second check protects internal adapters such as
ResolverTool; it does not replace CAP authorization.
"""
from __future__ import annotations

import fnmatch
import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict

from app.fileparsers.writer import write_document
from app.tools.base import Tool, ToolResult
from app.tools.document import DocumentTool, is_document_file
from app.tools.security import FileSystemSecurityPolicy, ToolSecurityContext, ToolSecurityEnforcer

DEFAULT_WRITE_DIR_ENV = "SAMAKTHA_WRITE_DIR"


class FileSystemTool(Tool):
    """Filesystem operations restricted to explicitly configured roots."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        write_dir: str | Path | None = None,
        *,
        security_policy: FileSystemSecurityPolicy | None = None,
    ) -> None:
        if security_policy is None:
            configured = root_dir or write_dir
            security_policy = FileSystemSecurityPolicy.build(
                allowed_roots=(configured,) if configured else (),
                default_root=write_dir or root_dir,
            )
        self.security_policy = security_policy
        self.security_enforcer = ToolSecurityEnforcer(security_policy)
        self._root_dir = security_policy.default_root
        if self._root_dir is not None:
            self._root_dir.mkdir(parents=True, exist_ok=True)
        from app.memory.resources import ResourceRegistry
        self._registry = ResourceRegistry()
        self._document_tool = DocumentTool(self._root_dir)

    @property
    def name(self) -> str:
        return "filesystem"

    def _validate(self, arguments: dict[str, Any]):
        action = str(arguments.get("action", "read"))
        context = ToolSecurityContext(
            principal_id="internal",
            execution_id="direct-filesystem",
            task_id="direct-filesystem",
            tool_name="filesystem",
            action=action,
            allowed_roots=tuple(str(root) for root in self.security_policy.allowed_roots),
        )
        return self.security_enforcer.validate(context, arguments)

    @staticmethod
    def _security_denied(decision) -> ToolResult:
        return ToolResult(
            ok=False,
            error=decision.message,
            data={
                "security_blocked": True,
                "security_reason": decision.reason_code.value,
                "failure_type": "tool_security_denied",
            },
        )

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        decision = self._validate(dict(arguments))
        if not decision.allowed:
            return self._security_denied(decision)
        arguments = decision.normalized_arguments
        action = str(arguments.get("action", "read")).lower()
        target_path = Path(arguments["path"])

        try:
            if action == "remember":
                self._registry.register(target_path)
                return ToolResult(ok=True, data={"remembered": str(target_path)})
            if action in ("exists", "check_exists"):
                return ToolResult(ok=True, data={"exists": target_path.exists(), "path": str(target_path)})
            if action in ("read", "read_file"):
                return await self._read(target_path)
            if action in ("write", "write_file"):
                target_path.parent.mkdir(parents=True, exist_ok=True)
                fmt, written_bytes = write_document(target_path, arguments.get("content", ""))
                await self._internal_unknown_effect_barrier()
                return ToolResult(ok=True, data={
                    "path": str(target_path), "format": fmt, "written_bytes": written_bytes,
                })
            if action in ("list", "list_directory", "ls", "dir"):
                return self._list(target_path)
            if action == "search":
                return self._search(target_path, str(arguments.get("pattern", "*")))
            if action in ("copy", "move"):
                return self._copy_or_move(action, target_path, Path(arguments["destination"]), bool(arguments.get("overwrite", False)))
            if action == "delete":
                if not target_path.exists():
                    return ToolResult(ok=False, error="File or directory not found.")
                self._enforce_tree_limit(target_path)
                shutil.rmtree(target_path) if target_path.is_dir() else target_path.unlink()
                return ToolResult(ok=True, data={"deleted": str(target_path)})
            if action == "mkdir":
                target_path.mkdir(parents=True, exist_ok=True)
                return ToolResult(ok=True, data={"created": str(target_path)})
            return ToolResult(ok=False, error=f"Unsupported filesystem action: {action}")
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception:
            return ToolResult(ok=False, error="Filesystem operation failed.")

    @staticmethod
    async def _internal_unknown_effect_barrier() -> None:
        """Bounded P12 seam after a real, policy-approved local write.

        This cannot expand filesystem scope or authorize an operation.  It is
        active only for the fixed internal validation command and provides a
        deterministic process-kill window after the effect but before Runtime
        receives the tool result.
        """
        if not (
            os.environ.get("SAMAKTHA_INTERNAL_VALIDATION") == "1"
            and os.environ.get("SAMAKTHA_INTERNAL_UNKNOWN_EFFECT") == "1"
        ):
            return
        from app import get_application_paths

        validation_root = get_application_paths().data_root / "p12_validation"
        validation_root.mkdir(parents=True, exist_ok=True)
        counter_path = validation_root / "unknown_effect_count.txt"
        try:
            count = int(counter_path.read_text(encoding="utf-8")) + 1
        except (OSError, ValueError):
            count = 1
        counter_path.write_text(str(count), encoding="utf-8")
        delay = min(
            60.0,
            max(0.0, float(os.environ.get("SAMAKTHA_INTERNAL_EFFECT_DELAY_SECONDS", "30"))),
        )
        if delay:
            await asyncio.sleep(delay)

    async def _read(self, target: Path) -> ToolResult:
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, error="File not found.")
        if is_document_file(target):
            result = await self._document_tool.run({"action": "read_document", "path": str(target)})
            if not result.ok:
                return result
            data = result.data.get("result", result.data)
            text = data.get("text", "")
            return ToolResult(ok=True, data={
                "path": data.get("path", str(target)), "content": text, "size": len(text),
                "title": data.get("title"), "page_count": data.get("page_count", 0),
                "sections": data.get("sections", []), "tables": data.get("tables", []),
                "images": data.get("images", []), "metadata": data.get("metadata", {}),
            })
        content = target.read_text(encoding="utf-8", errors="replace")
        return ToolResult(ok=True, data={
            "path": str(target), "content": content, "size": len(content.encode("utf-8")),
        })

    def _list(self, target: Path) -> ToolResult:
        if not target.exists() or not target.is_dir():
            return ToolResult(ok=False, error="Directory does not exist.")
        items = []
        for index, item in enumerate(target.iterdir(), start=1):
            if index > self.security_policy.max_directory_entries:
                return ToolResult(ok=False, error="Directory listing exceeds the configured entry limit.")
            child = self._validate({"action": "exists", "path": str(item)})
            if not child.allowed:
                return self._security_denied(child)
            items.append({
                "name": item.name, "path": str(item),
                "type": "folder" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return ToolResult(ok=True, data={"path": str(target), "items": items, "count": len(items)})

    def _search(self, target: Path, pattern: str) -> ToolResult:
        base = target if target.is_dir() else target.parent
        if not base.exists() or not base.is_dir():
            return ToolResult(ok=False, error="Search directory does not exist.")
        matches: list[str] = []
        inspected = 0
        base_depth = len(base.parts)
        for current, directories, files in os.walk(base, followlinks=False):
            current_path = Path(current)
            if len(current_path.parts) - base_depth >= self.security_policy.max_recursion_depth:
                directories[:] = []
            for name in [*directories, *files]:
                inspected += 1
                if inspected > self.security_policy.max_files_per_operation:
                    return ToolResult(ok=False, error="Filesystem search exceeds the configured file limit.")
                candidate = current_path / name
                if not self._validate({"action": "exists", "path": str(candidate)}).allowed:
                    continue
                if fnmatch.fnmatch(name, pattern):
                    matches.append(str(candidate))
        return ToolResult(ok=True, data={"matches": matches, "count": len(matches)})

    def _copy_or_move(self, action: str, source: Path, destination: Path, overwrite: bool) -> ToolResult:
        if not source.exists():
            return ToolResult(ok=False, error="Source does not exist.")
        self._enforce_tree_limit(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if action == "copy":
            shutil.copytree(source, destination, dirs_exist_ok=overwrite) if source.is_dir() else shutil.copy2(source, destination)
        else:
            if destination.exists() and overwrite:
                shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
            shutil.move(str(source), str(destination))
        return ToolResult(ok=True, data={"source": str(source), "destination": str(destination)})

    def _enforce_tree_limit(self, target: Path) -> None:
        if not target.is_dir():
            if target.stat().st_size > self.security_policy.max_read_bytes:
                raise ValueError("Filesystem operation exceeds the configured size limit.")
            return
        count = 0
        total_bytes = 0
        base_depth = len(target.parts)
        for current, directories, files in os.walk(target, followlinks=False):
            if len(Path(current).parts) - base_depth > self.security_policy.max_recursion_depth:
                raise ValueError("Filesystem operation exceeds the configured recursion limit.")
            count += len(directories) + len(files)
            if count > self.security_policy.max_files_per_operation:
                raise ValueError("Filesystem operation exceeds the configured file limit.")
            for name in files:
                total_bytes += (Path(current) / name).stat().st_size
                if total_bytes > self.security_policy.max_read_bytes:
                    raise ValueError("Filesystem operation exceeds the configured size limit.")
            for name in [*directories, *files]:
                decision = self._validate({
                    "action": "exists", "path": str(Path(current) / name),
                })
                if not decision.allowed:
                    raise ValueError("Filesystem tree contains a target outside the permitted scope.")
