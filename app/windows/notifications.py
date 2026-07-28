"""Phase 6.4 — Samaktha Native Windows Notifications.

Wraps Windows 10/11 Action Center toast notifications.
"""

from typing import Optional

from app.agent.models import AgentEvent
from app.windows import IS_WINDOWS

if IS_WINDOWS:
    try:
        from windows_toasts import WindowsToaster, ToastText1, Toast
    except ImportError:
        pass


class NotificationManager:
    """Sends native Windows toast notifications."""

    def __init__(self, app_name: str = "Samaktha Agent"):
        self.app_name = app_name
        self._toaster: Optional["WindowsToaster"] = None
        
        if IS_WINDOWS:
            try:
                self._toaster = WindowsToaster(self.app_name)
            except Exception:
                pass

    def send_toast(self, message: str) -> None:
        """Send a simple text toast notification."""
        if not self._toaster:
            return
            
        try:
            toast = ToastText1()
            toast.SetBody(message)
            self._toaster.show_toast(toast)
        except Exception:
            pass

    def handle_agent_event(self, event: AgentEvent, data: dict) -> None:
        """Optionally trigger toasts for critical agent events."""
        if event == AgentEvent.TOOL_FINISHED:
            pass # Too noisy to notify on every tool
        elif event == AgentEvent.ERROR_OCCURRED:
            reason = data.get("reason", "Unknown error")
            self.send_toast(f"Error: {reason}")
        elif event == AgentEvent.PLAN_FINISHED:
            self.send_toast("Task Plan execution completed.")
        # We can add WAITING_FOR_APPROVAL when that event exists in the future
