"""Phase 6.5 — Samaktha TUI Main Application.

Top-level Textual App wiring all widgets and AgentRuntime together.
Includes mascot state, in-TUI notifications, and personality profiles.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen

from app.agent.models import AgentEvent
from app.config.settings import get_settings
from app.voice.events import VoiceEvent
from app.tui.conversation import ConversationPanel
from app.tui.header import SamakthaHeader
from app.tui.input_bar import InputBar
from app.tui.startup import StartupScreen
from app.tui.status_panel import StatusPanel
from app.tui.theme import SAMAKTHA_CSS
from app.tui.timeline import TimelinePanel
from app.tui.feedback import AgentEventLog
from app.tui.attachments import Attachment

from app.tui.commands import CommandRegistry
from app.tui.command_palette import CommandPalette
from app.tui.session_browser import SessionBrowser
from app.tui.memory_panel import MemoryInspector
from app.tui.plan_panel import PlanInspector
from app.tui.tool_panel import ToolExecutionPanel
from app.tui.notifications import NotificationHost, NotificationKind


class MainScreen(Screen):
    """The primary chat screen shown after startup."""

    BINDINGS = [
        Binding("ctrl+l", "clear_conversation", "Clear"),
        Binding("ctrl+k", "clear_input", "Clear Input"),
        Binding("ctrl+q", "quit_app", "Quit"),
        Binding("ctrl+home", "jump_first", "First Message"),
        Binding("ctrl+end", "jump_latest", "Last Message"),
        Binding("ctrl+r", "reload_session", "Reload"),
        Binding("ctrl+m", "show_memory", "Memory"),
        Binding("ctrl+p", "show_plan", "Plan"),
        Binding("ctrl+t", "show_tools", "Tools"),
        Binding("f1", "show_help", "Help"),
    ]

    def __init__(self, runtime=None, command_registry=None, **kwargs):
        super().__init__(**kwargs)
        self._runtime = runtime
        self._active_session_id: str | None = None
        self._cmd_registry = command_registry or CommandRegistry()
        self._event_log = AgentEventLog()

    def compose(self) -> ComposeResult:
        yield SamakthaHeader()
        yield ConversationPanel(id="conversation")
        yield StatusPanel(id="status-panel")
        yield InputBar(on_submit=self._handle_user_input, id="input-bar")
        yield NotificationHost(id="notification-host")

    def on_mount(self) -> None:
        """Focus input bar on mount."""
        self.query_one("#user-input").focus()

    # ------------------------------------------------------------------
    # Actions (Keyboard Shortcuts)
    # ------------------------------------------------------------------

    def action_clear_conversation(self) -> None:
        conv = self.query_one("#conversation", ConversationPanel)
        conv.reset()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_clear_input(self) -> None:
        try:
            ta = self.query_one("#user-input")
            ta.text = ""
        except Exception:
            pass

    def action_jump_first(self) -> None:
        try:
            conv = self.query_one("#conversation", ConversationPanel)
            conv.scroll_home(animate=False)
        except Exception:
            pass

    def action_jump_latest(self) -> None:
        try:
            conv = self.query_one("#conversation", ConversationPanel)
            conv.scroll_end(animate=False)
        except Exception:
            pass

    def action_show_command_palette(self) -> None:
        def check_command(cmd: str | None) -> None:
            if cmd:
                self._handle_user_input(cmd)
        self.app.push_screen(CommandPalette(registry=self._cmd_registry), check_command)

    def action_reload_session(self) -> None:
        pass # To be implemented fully

    def action_show_memory(self) -> None:
        self.app.push_screen(MemoryInspector())

    def action_show_plan(self) -> None:
        self.app.push_screen(PlanInspector())

    def action_show_tools(self) -> None:
        self.app.push_screen(ToolExecutionPanel())

    def action_show_help(self) -> None:
        self._handle_user_input("/help")

    def action_show_sessions(self) -> None:
        if self._runtime and self._runtime.session_manager:
            def switch_session(sid: str | None) -> None:
                if sid:
                    self._active_session_id = sid
            self.app.push_screen(SessionBrowser(self._runtime.session_manager), switch_session)

    # ------------------------------------------------------------------
    # AgentRuntime wiring
    # ------------------------------------------------------------------

    def agent_event_callback(self, event: AgentEvent, data: Dict[str, Any]) -> None:
        """Receives AgentEvents from AgentRuntime and distributes to widgets."""
        import threading
        if threading.get_ident() == getattr(self.app, "_thread_id", None):
            self._dispatch_event(event, data)
        else:
            self.app.call_from_thread(self._dispatch_event, event, data)

    def voice_event_callback(self, event: VoiceEvent, data: Dict[str, Any]) -> None:
        """Receive voice lifecycle state without polling AgentRuntime."""
        import threading
        if threading.get_ident() == getattr(self.app, "_thread_id", None):
            self._dispatch_voice_event(event, data)
        else:
            self.app.call_from_thread(self._dispatch_voice_event, event, data)

    def _dispatch_voice_event(self, event: VoiceEvent, data: Dict[str, Any]) -> None:
        self.query_one("#status-panel", StatusPanel).update_voice_event(event, data)

    def _dispatch_event(self, event: AgentEvent, data: Dict[str, Any]) -> None:
        status = self.query_one("#status-panel", StatusPanel)
        notifs = self.query_one("#notification-host", NotificationHost)

        # Always update status and diagnostic log
        status.update_event(event, data)
        entry = self._event_log.record(event.value, data)

        # Feed timeline panel if present
        try:
            self.query_one(TimelinePanel).log_event(event, data)
        except Exception:
            pass

        # Resolve conversation panel (may not be mounted on startup screen)
        try:
            conv = self.query_one("#conversation", ConversationPanel)
        except Exception:
            conv = None

        # --- Pipeline stage transitions ---
        if event == AgentEvent.USER_MESSAGE and conv:
            conv.show_typing_indicator()
        elif event == AgentEvent.MEMORY_UPDATED and conv:
            items = data.get("items_found", 0)
            conv.advance_pipeline("memory")
            if items > 0:
                conv.append_memory_feedback(items)
            notifs.notify_tui("Memory updated", NotificationKind.SUCCESS, duration=2.0)
        elif event == AgentEvent.PLAN_STARTED and conv:
            conv.advance_pipeline("planning")
        elif event == AgentEvent.TOOL_STARTED and conv:
            conv.advance_pipeline("executing")
            tool = data.get("tool", "Tool")
            conv.append_tool_activity(tool, done=False)
        elif event == AgentEvent.TOOL_FINISHED and conv:
            tool = data.get("tool", "Tool")
            conv.append_tool_activity(tool, done=True)
            notifs.notify_tui(f"{tool} complete", NotificationKind.INFO, duration=2.0)
        elif event == AgentEvent.STREAM_STARTED and conv:
            conv.advance_pipeline("generating")

        # --- Lifecycle notifications ---
        elif event == AgentEvent.MODEL_SELECTED:
            provider = data.get("provider", "Local")
            notifs.notify_tui(f"Provider: {provider.capitalize()}", NotificationKind.INFO, duration=3.0)
        elif event == AgentEvent.SESSION_CREATED:
            notifs.notify_tui("Connected", NotificationKind.SUCCESS)
        elif event == AgentEvent.STREAM_FINISHED:
            notifs.notify_tui("Response complete", NotificationKind.SUCCESS, duration=2.0)
        elif event == AgentEvent.PLAN_FINISHED:
            notifs.notify_tui("Task completed", NotificationKind.SUCCESS)
        elif event == AgentEvent.ERROR_OCCURRED:
            reason = data.get("reason", "Execution failed")
            notifs.notify_tui(f"\u26a0 {reason}", NotificationKind.ERROR, duration=6.0)
            
        elif event == AgentEvent.PAUSE_REQUESTED:
            notifs.notify_tui("Action paused for user input", NotificationKind.WARNING, duration=8.0)
            if conv:
                conv.append_approval_request(task_id=data.get("task_id"), pause_data=data.get("pause"))

    def _handle_user_input(self, text: str) -> None:
        """Called when user submits a message."""
        # Check commands first
        if self._cmd_registry.parse_and_execute(text):
            return

        conv = self.query_one("#conversation", ConversationPanel)
        conv.append_user(text)

        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.set_enabled(False)

        conv.show_typing_indicator()

        asyncio.get_event_loop().create_task(self._stream_response(text))

    async def _stream_response(self, text: str) -> None:
        """Streams the AgentRuntime response into the conversation panel."""
        conv = self.query_one("#conversation", ConversationPanel)
        input_bar = self.query_one("#input-bar", InputBar)

        try:
            if self._runtime is not None:
                session_id = self._active_session_id or "default"
                started = False
                async for item in self._runtime.handle_message(session_id, text):
                    if isinstance(item, dict):
                        etype = item.get("type")
                        content = item.get("content", "")
                        
                        if etype == "provider":
                            if not started:
                                conv.hide_typing_indicator()
                                conv.append_assistant_start()
                                started = True
                                
                            if content and "CAP governance blocked user request" in content:
                                content = "Operation cancelled.\nPermission denied by user."
                                
                            conv.append_stream_token(content)
                        elif etype == "tool":
                            conv.hide_typing_indicator()
                            action = item.get("action")
                            settings = get_settings()
                            if settings.debug or (hasattr(settings, 'show_tool_output') and settings.show_tool_output):
                                conv.append_tool_output(content, action=action, show_header=True)
                        elif etype == "error":
                            conv.hide_typing_indicator()
                            conv.append_error(content)
                    else:
                        pass
            else:
                conv.hide_typing_indicator()
                conv.append_assistant_start()
                demo_text = f"[Demo mode] Echo: {text}"
                for char in demo_text:
                    conv.append_stream_token(char)
                    await asyncio.sleep(0.01)
        except Exception as exc:
            conv.hide_typing_indicator()
            conv.append_error(f"⚠ Provider error: {exc}")
        finally:
            conv.append_assistant_end()
            input_bar.set_enabled(True)
            self.query_one("#user-input").focus()

    from textual.widgets import Button
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if not button_id:
            return
            
        if button_id.startswith("btn_allow_") or button_id.startswith("btn_deny_"):
            task_id = button_id.split("_", 2)[2]
            decision = "allow" if button_id.startswith("btn_allow_") else "deny"
            
            # Disable the buttons
            event.button.parent.disabled = True
            
            # Remove the approval widget
            from app.tui.renderer import RenderedApprovalMessage
            for ancestor in event.button.ancestors:
                if isinstance(ancestor, RenderedApprovalMessage):
                    ancestor.remove()
                    break
            
            asyncio.create_task(self._submit_resume(task_id, {"permit": {"decision": decision, "reasons": ["User response via TUI"]}}))

    async def _submit_resume(self, task_id: str, updates: dict) -> None:
        conv = self.query_one("#conversation", ConversationPanel)
        input_bar = self.query_one("#input-bar", InputBar)
        
        input_bar.set_enabled(False)
        conv.show_typing_indicator()
        
        try:
            if self._runtime is not None:
                session_id = self._active_session_id or "default"
                started = False
                async for item in self._runtime.resume(session_id, task_id, updates):
                    if isinstance(item, dict):
                        etype = item.get("type")
                        content = item.get("content", "")
                        
                        if etype == "provider":
                            if not started:
                                conv.hide_typing_indicator()
                                conv.append_assistant_start()
                                started = True
                                
                            if content and "CAP governance blocked user request" in content:
                                content = "Operation cancelled.\nPermission denied by user."
                                
                            conv.append_stream_token(content)
                        elif etype == "tool":
                            conv.hide_typing_indicator()
                            action = item.get("action")
                            settings = get_settings()
                            if settings.debug or (hasattr(settings, 'show_tool_output') and settings.show_tool_output):
                                conv.append_tool_output(content, action=action, show_header=True)
                        elif etype == "error":
                            conv.hide_typing_indicator()
                            conv.append_error(content)
                    else:
                        pass
            else:
                conv.hide_typing_indicator()
                conv.append_error("No runtime attached to resume.")
        except Exception as exc:
            conv.hide_typing_indicator()
            conv.append_error(f"⚠ Resume error: {exc}")
        finally:
            conv.append_assistant_end()
            input_bar.set_enabled(True)
            self.query_one("#user-input").focus()


class SamakthaApp(App):
    """Top-level Samaktha TUI application."""

    CSS = SAMAKTHA_CSS
    TITLE = "Samaktha"

    def __init__(self, runtime=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._cmd_registry = CommandRegistry()
        self._register_commands()

    def _register_commands(self) -> None:
        self._cmd_registry.register("help", "Show help", lambda: self.screen.action_show_help())
        self._cmd_registry.register("clear", "Clear history", lambda: self.screen.action_clear_conversation())
        self._cmd_registry.register("session", "Open Session Browser", lambda: self.screen.action_show_sessions())
        self._cmd_registry.register("memory", "Open Memory Inspector", lambda: self.screen.action_show_memory())
        self._cmd_registry.register("plan", "Open Plan Inspector", lambda: self.screen.action_show_plan())
        self._cmd_registry.register("tools", "Open Tool Execution Panel", lambda: self.screen.action_show_tools())
        self._cmd_registry.register("quit", "Exit Samaktha", lambda: self.exit())
        
        # Stub the others required by the spec
        self._cmd_registry.register("history", "Show history", lambda: None)
        self._cmd_registry.register("provider", "Manage providers", lambda: None)
        self._cmd_registry.register("status", "Show status", lambda: None)
        self._cmd_registry.register("config", "Open configuration", lambda: None)
        self._cmd_registry.register("theme", "Change theme", lambda: None)
        self._cmd_registry.register("about", "About Samaktha", lambda: None)
        
        # Phase 6.8: Attachment Commands
        self._cmd_registry.register("attach", "Attach a file", self._cmd_attach)
        self._cmd_registry.register("drop", "Drop a file", self._cmd_attach)
        self._cmd_registry.register("open", "Open a file", self._cmd_attach)

    def _cmd_attach(self, *args) -> None:
        """Handler for /attach, /drop, /open slash commands."""
        import os
        import mimetypes
        from app.tui.conversation import ConversationPanel

        if not args:
            return
            
        path = " ".join(args)
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1].lower()
        mime_type, _ = mimetypes.guess_type(path)
        mime_type = mime_type or "application/octet-stream"
        
        # Estimate size if possible, otherwise dummy 0
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
            
        att = Attachment(
            path=path,
            filename=filename,
            extension=ext,
            mime_type=mime_type,
            size=size
        )
        
        main = self.query_one("MainScreen")
        if main:
            conv = main.query_one("#conversation", ConversationPanel)
            conv.append_attachment(att)

    def on_mount(self) -> None:
        main = MainScreen(runtime=self._runtime, command_registry=self._cmd_registry, name="main")
        if self._runtime is not None:
            self._runtime._event_callback = main.agent_event_callback
            
            # Setup Windows Integration hooks
            from app.windows import IS_WINDOWS
            if IS_WINDOWS:
                from app.windows.notifications import NotificationManager
                from app.windows.tray import TrayManager
                from app.windows.hotkeys import HotkeyManager
                from app.windows.window_state import WindowManager
                
                self._notification_manager = NotificationManager()
                self._hotkey_manager = HotkeyManager()
                
                # Intercept events for notifications and tray status
                original_cb = main.agent_event_callback
                
                def extended_cb(event, data):
                    original_cb(event, data)
                    if hasattr(self, "_notification_manager"):
                        self._notification_manager.handle_agent_event(event, data)
                    if hasattr(self, "_tray_manager"):
                        self._tray_manager.update_status(event.value)
                        
                self._runtime._event_callback = extended_cb
                
                # Start Tray
                self._tray_manager = TrayManager(
                    on_show=WindowManager.show,
                    on_hide=WindowManager.hide,
                    on_restart=lambda: None,
                    on_exit=lambda: self.exit()
                )
                
                # We don't have an icon yet, it will use the generated default
                self._tray_manager.start(icon_path=None)
                
                # Register Hotkey
                self._hotkey_manager.register(WindowManager.toggle)
        
        self.install_screen(main, "main")
        self.push_screen(StartupScreen(name="startup"))

    def on_unmount(self) -> None:
        if hasattr(self, "_tray_manager"):
            self._tray_manager.stop()
        if hasattr(self, "_hotkey_manager"):
            self._hotkey_manager.unregister()
