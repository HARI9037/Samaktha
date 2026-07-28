"""Tests for Phase 6.3 TUI Panels."""

from app.tui.memory_panel import MemoryInspector
from app.tui.plan_panel import PlanInspector
from app.tui.tool_panel import ToolExecutionPanel
from app.tui.session_browser import SessionBrowser
from app.tui.command_palette import CommandPalette
from app.tui.commands import CommandRegistry


def test_panels_can_be_instantiated():
    """Ensure panels can be created without crashing."""
    mem = MemoryInspector()
    assert mem is not None
    
    plan = PlanInspector()
    assert plan is not None
    
    tools = ToolExecutionPanel()
    assert tools is not None
    
    reg = CommandRegistry()
    cmd = CommandPalette(registry=reg)
    assert cmd is not None
