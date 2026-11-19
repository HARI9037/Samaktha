"""Tests for TUI approval flow button clicks."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tui.app import MainScreen
from app.tui.conversation import ConversationPanel
from app.tui.renderer import RenderedApprovalMessage
from app.tui.models import ConversationMessage
from app.core.contracts.runtime import RuntimeResult
from app.core.contracts.planning import TaskStatus
from textual.app import App, ComposeResult
from textual.widgets import Button


class TestApprovalApp(App):
    """Test app that includes MainScreen."""
    def __init__(self, runtime=None, **kwargs):
        super().__init__(**kwargs)
        self._runtime = runtime

    def compose(self) -> ComposeResult:
        yield MainScreen(runtime=self._runtime, id="main")


@pytest.fixture
def mock_runtime():
    """Create a mock runtime with resume_pipeline mocked."""
    with patch('app.agent.production.create_orchestrator'):
        from app.agent.production import ProductionAgentRuntime
        rt = ProductionAgentRuntime()
        rt._orchestrator = AsyncMock()
        rt._coordinator = AsyncMock()
        rt._session_executions = {"default": "test-execution-id"}
        rt._coordinator.submit_approval.return_value = AsyncMock(
            runtime_result=RuntimeResult(task_id="test-task", status=TaskStatus.COMPLETED)
        )
        rt._orchestrator.run_pipeline.return_value = AsyncMock(
            runtime_result=RuntimeResult(task_id="test-task", status=TaskStatus.COMPLETED)
        )
        return rt


@pytest.mark.asyncio
async def test_tui_approval_button_click_resumes(mock_runtime):
    """Test that clicking Allow button calls runtime.resume()."""
    app = TestApprovalApp(runtime=mock_runtime)

    async with app.run_test() as pilot:
        main_screen = app.query_one("#main", MainScreen)
        conv = main_screen.query_one("#conversation", ConversationPanel)

        # Simulate an approval request being appended
        task_id = "test-task-123"
        pause_data = {
            "metadata": {
                "action": "write_file",
                "tool": "write",
                "args": {"path": "/test/file.txt", "content": "test"},
                "target": "/test/file.txt"
            }
        }
        conv.append_approval_request(task_id=task_id, pause_data=pause_data)

        # Wait for the approval widget to be mounted
        await pilot.pause()

        # Find the approval widget and Allow button
        approval_widget = main_screen.query_one(RenderedApprovalMessage)
        assert approval_widget is not None

        allow_button = approval_widget.query_one(f"#btn_allow_{task_id}", Button)
        assert allow_button is not None
        assert "Allow" in str(allow_button.label)

        # Create a mock Button.Pressed event and call the handler directly
        # This tests the handler logic without relying on pilot.click()
        from textual.widgets._button import Button as ButtonClass
        event = ButtonClass.Pressed(allow_button)
        main_screen.on_button_pressed(event)

        # Wait for the async task to complete
        await pilot.pause(0.5)

        # Verify runtime.resume_pipeline was called
        mock_runtime._coordinator.submit_approval.assert_called_once()
        print(f"Call args: {mock_runtime._coordinator.submit_approval.call_args}")
        call_args = mock_runtime._coordinator.submit_approval.call_args
        assert call_args[0][0] == "test-execution-id"  # execution_id
        assert call_args[0][1] == task_id              # task_id
        assert call_args[0][2] == "allow"              # decision
        assert call_args[1]["reasons"] == ["User response via TUI"]


@pytest.mark.asyncio
async def test_tui_approval_typed_input_treated_as_message(mock_runtime):
    """Test that typing 'approved' is treated as a new user message, not a resume."""
    app = TestApprovalApp(runtime=mock_runtime)

    async with app.run_test() as pilot:
        main_screen = app.query_one("#main", MainScreen)
        conv = main_screen.query_one("#conversation", ConversationPanel)

        # Simulate an approval request being appended
        task_id = "test-task-456"
        pause_data = {
            "metadata": {
                "action": "write_file",
                "tool": "write",
                "args": {"path": "/test/file.txt", "content": "test"},
                "target": "/test/file.txt"
            }
        }
        conv.append_approval_request(task_id=task_id, pause_data=pause_data)

        # Wait for the approval widget to be mounted
        await pilot.pause()

        # Verify the approval widget exists
        approval_widget = main_screen.query_one(RenderedApprovalMessage)
        assert approval_widget is not None

        # Simulate user typing "approved" (not clicking button)
        input_bar = main_screen.query_one("#input-bar")
        # Directly call _handle_user_input with "approved"
        main_screen._handle_user_input("approved")
        await pilot.pause()

        # Verify runtime.resume_pipeline was NOT called
        mock_runtime._orchestrator.resume_pipeline.assert_not_called()

        # Verify the text was treated as a user message (appended to conversation)
        # The approval widget should still be there since we didn't click a button
        approval_widget_after = main_screen.query_one(RenderedApprovalMessage)
        assert approval_widget_after is not None


@pytest.mark.asyncio
async def test_tui_approval_deny_button_click_resumes(mock_runtime):
    """Test that clicking Deny button calls runtime.resume() with deny decision."""
    app = TestApprovalApp(runtime=mock_runtime)

    async with app.run_test() as pilot:
        main_screen = app.query_one("#main", MainScreen)
        conv = main_screen.query_one("#conversation", ConversationPanel)

        # Simulate an approval request being appended
        task_id = "test-task-789"
        pause_data = {
            "metadata": {
                "action": "delete_file",
                "tool": "delete",
                "args": {"path": "/test/file.txt"},
                "target": "/test/file.txt"
            }
        }
        conv.append_approval_request(task_id=task_id, pause_data=pause_data)

        # Wait for the approval widget to be mounted
        await pilot.pause()

        # Find the approval widget and Deny button
        approval_widget = main_screen.query_one(RenderedApprovalMessage)
        assert approval_widget is not None

        deny_button = approval_widget.query_one(f"#btn_deny_{task_id}", Button)
        assert deny_button is not None
        assert "Deny" in str(deny_button.label)

        # Create a mock Button.Pressed event and call the handler directly
        from textual.widgets._button import Button as ButtonClass
        event = ButtonClass.Pressed(deny_button)
        main_screen.on_button_pressed(event)

        # Wait for the async task to complete
        await pilot.pause(0.5)

        # Verify runtime.resume_pipeline was called with deny decision
        mock_runtime._coordinator.submit_approval.assert_called_once()
        print(f"Call args: {mock_runtime._coordinator.submit_approval.call_args}")
        call_args = mock_runtime._coordinator.submit_approval.call_args
        assert call_args[0][0] == "test-execution-id"  # execution_id
        assert call_args[0][1] == task_id              # task_id
        assert call_args[0][2] == "deny"               # decision
        assert call_args[1]["reasons"] == ["User response via TUI"]
