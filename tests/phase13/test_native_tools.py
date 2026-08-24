"""Phase 13.8 — native core tools: Shell, Clipboard and Notification."""

from app.tools.clipboard import ClipboardTool
from app.tools.framework import ToolCapability
from app.tools.notification import NotificationTool
from app.tools.shell import ShellTool

from .conftest import run_async


# ---------------------------------------------------------------------------
# ShellTool
# ---------------------------------------------------------------------------


def test_shell_denylist_refuses_destructive_commands():
    tool = ShellTool()
    for command in ("rm -rf /", "format c:", "shutdown /s"):
        result = run_async(tool.run({"command": command}))
        assert result.ok is False, command
        assert "denylist" in result.error


def test_shell_empty_command():
    result = run_async(ShellTool().run({"command": "  "}))
    assert result.ok is False


def test_shell_input_schema_declared():
    schema = ShellTool().input_schema
    assert "command" in schema
    assert schema["command"].get("required") is True


def test_shell_execution_smoke():
    class FakeShell(ShellTool):
        async def _run_command(self, cmd_list, timeout_s, cwd, env, use_shell=False):
            return f"ran: {cmd_list}"

    result = run_async(FakeShell().run({"command": "echo hello"}))
    assert result.ok
    assert "ran:" in result.data["output"]


def test_shell_caps_and_category():
    assert ToolCapability.SHELL_EXEC in ShellTool.capabilities
    assert ShellTool.category.value == "system"


# ---------------------------------------------------------------------------
# ClipboardTool
# ---------------------------------------------------------------------------


class _FakePyperclip:
    _content = ""

    def paste(self):
        return self._content

    def copy(self, value):
        self._content = value


def test_clipboard_read_with_fake_pyperclip(monkeypatch):
    fake = _FakePyperclip()
    fake._content = "hello"
    monkeypatch.setattr("app.tools.clipboard.pyperclip", fake)
    monkeypatch.setattr("app.tools.clipboard._HAS_CLIPBOARD", True)
    result = run_async(ClipboardTool().run({"action": "read"}))
    assert result.ok
    assert result.data["content"] == "hello"


def test_clipboard_write_with_fake_pyperclip(monkeypatch):
    fake = _FakePyperclip()
    monkeypatch.setattr("app.tools.clipboard.pyperclip", fake)
    monkeypatch.setattr("app.tools.clipboard._HAS_CLIPBOARD", True)
    result = run_async(ClipboardTool().run({"action": "write", "content": "abc"}))
    assert result.ok
    assert fake._content == "abc"


def test_clipboard_unavailable_without_pyperclip(monkeypatch):
    monkeypatch.setattr("app.tools.clipboard._HAS_CLIPBOARD", False)
    result = run_async(ClipboardTool().run({"action": "read"}))
    assert result.ok is False
    assert "unavailable" in result.error


def test_clipboard_unknown_action():
    result = run_async(ClipboardTool().run({"action": "nope"}))
    assert result.ok is False


def test_clipboard_write_requires_string_content(monkeypatch):
    fake = _FakePyperclip()
    monkeypatch.setattr("app.tools.clipboard.pyperclip", fake)
    monkeypatch.setattr("app.tools.clipboard._HAS_CLIPBOARD", True)
    result = run_async(ClipboardTool().run({"action": "write", "content": 42}))
    assert result.ok is False


# ---------------------------------------------------------------------------
# NotificationTool
# ---------------------------------------------------------------------------


def test_notification_graceful_without_notifier(monkeypatch):
    monkeypatch.setattr("app.tools.notification._PLYER", False)
    monkeypatch.setattr("app.tools.notification._WIN10", False)
    result = run_async(NotificationTool().run({"title": "Hi", "message": "Build done"}))
    assert result.ok
    assert result.data["sent"] is False


def test_notification_requires_title_and_message():
    assert run_async(NotificationTool().run({"title": "Hi"})).ok is False
    assert run_async(NotificationTool().run({})).ok is False


def test_notification_with_plyer(monkeypatch):
    class _FakePlyer:
        @staticmethod
        def notify(**kwargs):
            assert kwargs["title"] == "Hi"

    monkeypatch.setattr("app.tools.notification._plyer_notification", _FakePlyer)
    monkeypatch.setattr("app.tools.notification._PLYER", True)
    monkeypatch.setattr("app.tools.notification._WIN10", False)
    result = run_async(NotificationTool().run({"title": "Hi", "message": "msg"}))
    assert result.ok
    assert result.data["sent"] is True
