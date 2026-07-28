"""Tests for Phase 6.3 TUI Commands system."""

from app.tui.commands import CommandRegistry


def test_command_registry_registers_command():
    registry = CommandRegistry()
    registry.register("test", "A test", lambda: None)
    cmds = registry.get_all()
    assert len(cmds) == 1
    assert cmds[0].name == "test"


def test_command_registry_aliases():
    registry = CommandRegistry()
    registry.register("test", "A test", lambda: None, aliases=["t"])
    cmds = registry.get_all()
    assert len(cmds) == 1
    
    # Check that both invoke the same command
    called = []
    registry._commands["test"].callback = lambda: called.append(1)
    
    registry.parse_and_execute("/test")
    assert called == [1]
    
    registry.parse_and_execute("/t")
    assert called == [1, 1]


def test_command_registry_parse_args():
    registry = CommandRegistry()
    args_received = []
    
    def my_cmd(arg1, arg2):
        args_received.append((arg1, arg2))
        
    registry.register("args", "Args test", my_cmd)
    
    # Should parse correctly with quotes
    registry.parse_and_execute('/args "hello world" foo')
    assert args_received == [("hello world", "foo")]


def test_parse_and_execute_returns_false_for_non_commands():
    registry = CommandRegistry()
    assert registry.parse_and_execute("hello") is False
    assert registry.parse_and_execute(" /not_a_command") is True  # Strips whitespace, starts with /, handled as command
    
    assert registry.parse_and_execute("hello /test") is False
