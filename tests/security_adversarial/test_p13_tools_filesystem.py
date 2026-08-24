from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.filesystem import FileSystemTool
from app.tools.security import FileSystemSecurityPolicy


def _tool(root: Path, *, protected: tuple[Path, ...] = ()) -> FileSystemTool:
    root.mkdir(parents=True, exist_ok=True)
    return FileSystemTool(
        security_policy=FileSystemSecurityPolicy.build(
            allowed_roots=[root],
            default_root=root,
            protected_paths=protected,
            max_path_length=256,
            max_read_bytes=64,
            max_write_bytes=64,
            max_directory_entries=3,
            max_files_per_operation=3,
            max_recursion_depth=2,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_path",
    [
        "../escape", "..\\escape", "a/../../escape", "a\\..\\..\\escape",
        r"C:\escape", r"C:escape", r"\\server\share\escape",
        r"\\?\C:\escape", r"\\.\PhysicalDrive0", "%TEMP%\\escape",
        "~/.env", "$HOME/.env", "NUL", "CON.txt", "COM1 ", "LPT1.txt.",
        "x" * 300,
    ],
)
async def test_filesystem_hostile_paths_fail_closed(tmp_path: Path, hostile_path: str) -> None:
    result = await _tool(tmp_path / "workspace").run(
        {"action": "read", "path": hostile_path}
    )
    assert not result.ok, hostile_path
    assert result.data.get("security_blocked") is True, hostile_path


@pytest.mark.asyncio
async def test_filesystem_protected_security_state_is_unreadable(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    protected = {
        root / ".env": "P13_SENTINEL_SECRET",
        root / "permit_signing.key": "key",
        root / "memory.db": "memory",
        root / "evidence.db": "evidence",
        root / "checkpoints" / "state.json": "checkpoint",
        root / "plugins" / "plugin.json": "plugin",
    }
    for path, content in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    tool = _tool(root, protected=tuple(protected))

    for path, original in protected.items():
        for action in ("read", "delete"):
            result = await tool.run({"action": action, "path": str(path)})
            assert not result.ok, (path, action)
            assert result.data["security_reason"] == "protected_target"
        assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_filesystem_link_escape_is_denied_for_read_write_and_delete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "sentinel.txt"
    target.write_text("outside", encoding="utf-8")
    link = root / "escape-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this Windows host")
    tool = _tool(root)

    operations = (
        {"action": "read", "path": "escape-link/sentinel.txt"},
        {"action": "write", "path": "escape-link/new.txt", "content": "bad"},
        {"action": "delete", "path": "escape-link/sentinel.txt"},
    )
    for operation in operations:
        result = await tool.run(operation)
        assert not result.ok
        assert result.data["security_reason"] == "outside_allowed_root"
    assert target.read_text(encoding="utf-8") == "outside"
    assert not (outside / "new.txt").exists()


@pytest.mark.asyncio
async def test_filesystem_resource_limits_fail_without_partial_write(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    tool = _tool(root)
    oversized = await tool.run(
        {"action": "write", "path": "large.txt", "content": "x" * 65}
    )
    assert not oversized.ok
    assert oversized.data["security_reason"] == "resource_limit"
    assert not (root / "large.txt").exists()

    for index in range(4):
        (root / f"{index}.txt").write_text(str(index), encoding="utf-8")
    listing = await tool.run({"action": "list", "path": "."})
    assert not listing.ok
    assert "limit" in (listing.error or "").lower()
