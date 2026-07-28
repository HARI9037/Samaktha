"""Tests for Phase 6.4 Windows Native Integrations."""

import pytest
import os
import ast
from unittest.mock import MagicMock, patch

from app.windows import IS_WINDOWS
from app.windows.clipboard import ClipboardManager
from app.windows.hotkeys import HotkeyManager
from app.windows.notifications import NotificationManager
from app.windows.startup import StartupManager
from app.windows.files import FileManager
from app.windows.window_state import WindowManager
from app.windows.tray import TrayManager


def test_clipboard_manager():
    # If not windows, it should return False/Empty string gracefully
    if not IS_WINDOWS:
        assert ClipboardManager.read_text() == ""
        assert ClipboardManager.write_text("test") is False
        assert ClipboardManager.has_image() is False
    else:
        # Mock pyperclip
        with patch("pyperclip.paste", return_value="hello"), \
             patch("pyperclip.copy") as mock_copy:
            assert ClipboardManager.read_text() == "hello"
            assert ClipboardManager.write_text("world") is True
            mock_copy.assert_called_once_with("world")


def test_hotkey_manager():
    manager = HotkeyManager()
    assert manager._hooked is False
    
    if not IS_WINDOWS:
        assert manager.register(lambda: None) is False
    else:
        with patch("keyboard.add_hotkey"), patch("keyboard.unhook_all"):
            assert manager.register(lambda: None) is True
            assert manager._hooked is True
            manager.unregister()
            assert manager._hooked is False


def test_notification_manager():
    manager = NotificationManager()
    # It should not crash on initialization
    
    if IS_WINDOWS and manager._toaster:
        with patch("app.windows.notifications.ToastText1", create=True), \
             patch.object(manager._toaster, "show_toast") as mock_toast:
            manager.send_toast("Hello")
            mock_toast.assert_called_once()
            

def test_startup_manager():
    assert StartupManager.get_executable_path() != ""
    # We won't test actual registry writes, just that the methods exist
    assert hasattr(StartupManager, "is_enabled")
    assert hasattr(StartupManager, "enable")
    assert hasattr(StartupManager, "disable")


def test_window_manager():
    # Mostly ctypes wrappers, ensure they don't crash
    # If not on Windows, get_hwnd returns 0
    if not IS_WINDOWS:
        assert WindowManager.get_hwnd() == 0


def test_tray_manager():
    manager = TrayManager(lambda: None, lambda: None, lambda: None, lambda: None)
    assert manager.status_text == "Status: IDLE"
    manager.update_status("THINKING")
    assert manager.status_text == "Status: THINKING"


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
WIN_DIR = os.path.join(ROOT, "app", "windows")

def _collect_imports(stmts: list, imports: list[str]) -> None:
    for node in stmts:
        if isinstance(node, ast.If):
            test = node.test
            is_tc = (
                (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or
                (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
            )
            if is_tc:
                continue
            _collect_imports(node.body, imports)
            _collect_imports(node.orelse, imports)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif hasattr(node, "body"):
            _collect_imports(
                node.body if isinstance(node.body, list) else [node.body], imports
            )

def _get_imports(filepath: str) -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return []
    imports: list[str] = []
    _collect_imports(tree.body, imports)
    return imports

def test_windows_strict_boundaries_phase64():
    """Verify Phase 6.4 components don't violate architecture boundaries."""
    forbidden = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.runtime",
        "app.providers",
        "app.memory.manager",
        "app.security",
        "app.tools",
    ]
    violations = []
    for root, _, files in os.walk(WIN_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(root, fname)
            for imp in _get_imports(filepath):
                for prefix in forbidden:
                    if imp.startswith(prefix):
                        rel = os.path.relpath(filepath, ROOT)
                        violations.append(
                            f"{rel} imports '{imp}' (violates '{prefix}')"
                        )
    assert violations == [], (
        "Architecture boundary violations found in app/windows:\n" +
        "\n".join(violations)
    )
