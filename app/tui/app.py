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
from textual.widgets import Button

from app.agent.models import AgentEvent
from app.config.settings import get_settings
from app.voice.events import VoiceEvent
from app.voice.config import VoiceConfig
from app.voice.session import VoiceSession
from app.tui.conversation import ConversationPanel
from app.tui.header import SamakthaHeader
from app.tui.input_bar import InputBar
from app.tui.startup import StartupScreen
from app.tui.status_bar import StatusBar
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
from app.tui.command_history import ShellHistory


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
        Binding("f9", "toggle_push_to_talk", "Push-to-Talk"),
    ]

    def __init__(self, runtime=None, command_registry=None, **kwargs):
        super().__init__(**kwargs)
        self._runtime = runtime
        self._active_session_id: str | None = None
        self._message_count = 0
        self._pending_delete: str | None = None
        self._cmd_registry = command_registry or CommandRegistry()
        self._legacy_names = set(getattr(self._cmd_registry, "_commands", {}).keys())
        self._histories: dict[str, ShellHistory] = {}
        self._event_log = AgentEventLog()
        self._voice_session: VoiceSession | None = None
        self._ptt_active = False

    def compose(self) -> ComposeResult:
        yield SamakthaHeader()
        yield ConversationPanel(id="conversation")
        yield StatusPanel(id="voice-status-panel")
        yield StatusBar(id="runtime-status-bar")
        yield InputBar(on_submit=self._handle_user_input, id="input-bar")
        yield NotificationHost(id="notification-host")

    def on_mount(self) -> None:
        """Focus input bar on mount."""
        self._attach_history()
        self.query_one("#user-input").focus()

        # Wire the RuntimeEventBus to the widgets
        session_id = self._active_session_id or "default"
        if self._runtime is not None and hasattr(self._runtime, "get_event_bus"):
            bus = self._runtime.get_event_bus(session_id)
            
            status_bar = self.query_one("#runtime-status-bar", StatusBar)
            status_bar.attach_bus(bus)
            
            conv = self.query_one("#conversation", ConversationPanel)
            if hasattr(conv, "attach_bus"):
                conv.attach_bus(bus)

        # Initialize voice session if runtime is available
        if self._runtime is not None:
            settings = get_settings()
            voice_config = VoiceConfig.from_settings(settings)
            if voice_config.enable_local_voice:
                self._voice_session = VoiceSession.from_config(
                    config=voice_config,
                    session_id=self._active_session_id or "default",
                    on_voice_event=self.voice_event_callback,
                )
                # Start voice session asynchronously
                asyncio.create_task(self._voice_session.start())

    # ------------------------------------------------------------------
    # Voice actions
    # ------------------------------------------------------------------

    def action_toggle_push_to_talk(self) -> None:
        """Toggle push-to-talk (F9)."""
        if self._voice_session and self._voice_session.config.enable_push_to_talk:
            if not self._ptt_active:
                asyncio.create_task(self._voice_session.push_to_talk_start())
                self._ptt_active = True
            else:
                asyncio.create_task(self._voice_session.push_to_talk_stop())
                self._ptt_active = False

    def action_toggle_voice(self) -> None:
        """Toggle voice session on/off."""
        if self._voice_session:
            self._voice_session.toggle()

    # ------------------------------------------------------------------
    # Per-session shell history
    # ------------------------------------------------------------------

    def _attach_history(self) -> None:
        """Attach the active session's history buffer to the input bar."""
        session_id = self._active_session_id or "default"
        history = self._histories.setdefault(session_id, ShellHistory())
        try:
            input_bar = self.query_one("#input-bar", InputBar)
            input_bar.set_session_history(history)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Actions (Keyboard Shortcuts)
    # ------------------------------------------------------------------

    def action_clear_conversation(self) -> None:
        conv = self.query_one("#conversation", ConversationPanel)
        conv.reset()

    def action_quit_app(self) -> None:
        self._save_current_session()
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
        """Reload the active session's persisted state and refresh history."""
        self._save_current_session()
        router = getattr(self.app, "command_router", None)
        if router is None or not hasattr(router, "reload_session"):
            return
        self._apply_command_result(router.reload_session(self._active_session_id))

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
        try:
            self.query_one("#voice-status-panel", StatusPanel).update_voice_event(event, data)
        except Exception:
            pass

    def _dispatch_event(self, event: AgentEvent, data: Dict[str, Any]) -> None:
        notifs = self.query_one("#notification-host", NotificationHost)

        # Always update diagnostic log
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
        text = (text or "").strip()
        if not text:
            return

        conv = self.query_one("#conversation", ConversationPanel)

        # Resolve a pending /delete-session approval before anything else.
        if self._pending_delete is not None:
            self._handle_pending_delete(text)
            return

        # Slash commands never reach the orchestrator / LLM.
        if text.startswith("/"):
            self._handle_slash(text)
            return

        conv.append_user(text)

        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.set_enabled(False)

        conv.show_typing_indicator()

        self._bump_message_count()

        asyncio.get_running_loop().create_task(self._stream_response(text))

    # ------------------------------------------------------------------
    # Phase 11.1 — Command Router integration
    # ------------------------------------------------------------------

    def _handle_slash(self, text: str) -> None:
        """Route a slash command to the Command Router or a legacy command."""
        conv = self.query_one("#conversation", ConversationPanel)
        router = getattr(self.app, "command_router", None)
        if router is not None and router.is_command(text):
            asyncio.get_running_loop().create_task(self._run_command(text))
            return
        if self._is_legacy_command(text):
            self._cmd_registry.parse_and_execute(text)
            return
        conv.append_system("Unknown command. Type /help for available commands.")

    def _is_legacy_command(self, text: str) -> bool:
        parts = text.split()
        if not parts:
            return False
        return parts[0].lstrip("/").lower() in self._legacy_names

    async def _run_command(self, text: str) -> None:
        """Execute a router command and apply its result to the UI."""
        conv = self.query_one("#conversation", ConversationPanel)
        input_bar = self.query_one("#input-bar", InputBar)
        router = getattr(self.app, "command_router", None)
        if router is None:
            conv.append_system("Unknown command. Type /help for available commands.")
            return
        input_bar.set_enabled(False)
        try:
            result = await router.execute(text, self._active_session_id)
        except Exception as exc:
            conv.append_system(f"⚠ Command error: {exc}")
            return
        finally:
            input_bar.set_enabled(True)
        self._apply_command_result(result)

    def _apply_command_result(self, result) -> None:
        """Apply a CommandResult to the conversation and session state."""
        conv = self.query_one("#conversation", ConversationPanel)
        if not result.handled:
            conv.append_system("Unknown command. Type /help for available commands.")
            return

        action = result.action
        if action == "clear":
            conv.reset()
            return
        if action == "exit":
            self._save_current_session()
            self.app.exit()
            return

        if action in ("new_session", "delete_session", "switch_session", "reload_session"):
            session_id = result.payload.get("session_id")
            if session_id:
                self._active_session_id = session_id
                self._message_count = int(result.payload.get("message_count") or 0)
                self._histories.setdefault(session_id, ShellHistory())
            self._attach_history()
        elif action == "delete_session_pending":
            self._pending_delete = result.payload.get("session_id")

        if result.output:
            conv.append_system(result.output)

    def _handle_pending_delete(self, text: str) -> None:
        """Interpret the next input as y/n for a pending /delete-session."""
        conv = self.query_one("#conversation", ConversationPanel)
        router = getattr(self.app, "command_router", None)
        lowered = text.lower()

        if text.startswith("/"):
            # A new slash command supersedes the pending approval.
            self._pending_delete = None
            self._handle_slash(text)
            return
        if router is None:
            self._pending_delete = None
            conv.append_system("Deletion cancelled.")
            return
        if lowered in ("y", "yes"):
            result = router.confirm_delete(self._active_session_id, approve=True)
        elif lowered in ("n", "no"):
            result = router.confirm_delete(self._active_session_id, approve=False)
        else:
            conv.append_system("Reply y to confirm or n to cancel.")
            return
        self._pending_delete = None
        self._apply_command_result(result)

    # ------------------------------------------------------------------
    # Session accounting
    # ------------------------------------------------------------------

    def _bump_message_count(self) -> None:
        """Increment the active session's message count and persist it."""
        self._message_count += 1
        router = getattr(self.app, "command_router", None)
        if router is not None:
            router.save_active_session(self._active_session_id, self._message_count)

    def _save_current_session(self) -> None:
        """Persist the active session before quitting or rotating."""
        router = getattr(self.app, "command_router", None)
        if router is not None:
            router.save_active_session(self._active_session_id, self._message_count)

    async def _stream_response(self, text: str) -> None:
        """Stream the AgentRuntime response into the conversation panel."""
        if self._runtime is None:
            await self._consume_demo_response(text)
            return
        session_id = self._active_session_id or "default"
        await self._consume_runtime_stream(
            self._runtime.handle_message(session_id, text), "Provider error"
        )

    async def _consume_demo_response(self, text: str) -> None:
        """Stream a canned echo when no runtime is attached (demo mode)."""
        conv = self.query_one("#conversation", ConversationPanel)
        conv.hide_typing_indicator()
        conv.append_assistant_start()
        demo_text = f"[Demo mode] Echo: {text}"
        for char in demo_text:
            conv.append_stream_token(char)
            await asyncio.sleep(0.01)
        conv.append_assistant_end()
        self._restore_input_bar()

    async def _consume_runtime_stream(self, stream, error_prefix: str) -> None:
        """Canonical consumer for runtime item streams.

        Handles provider/tool/error items from both ``handle_message`` and
        ``resume``, applies the tool-output visibility gate once, and always
        restores the input bar when the stream ends or fails.
        """
        conv = self.query_one("#conversation", ConversationPanel)
        started = False
        try:
            async for item in stream:
                if not isinstance(item, dict):
                    continue
                etype = item.get("type")
                content = item.get("content", "")
                if etype == "provider":
                    if not started:
                        conv.hide_typing_indicator()
                        conv.append_assistant_start()
                        started = True
                    conv.append_stream_token(content)
                elif etype == "tool":
                    conv.hide_typing_indicator()
                    settings = get_settings()
                    if settings.debug or (hasattr(settings, 'show_tool_output') and settings.show_tool_output):
                        conv.append_tool_output(content, action=item.get("action"), show_header=True)
                elif etype == "error":
                    conv.hide_typing_indicator()
                    conv.append_error(content)
        except Exception as exc:
            conv.hide_typing_indicator()
            conv.append_error(f"⚠ {error_prefix}: {exc}")
        finally:
            conv.append_assistant_end()
            self._restore_input_bar()

    def _restore_input_bar(self) -> None:
        """Re-enable the input bar and return focus after a stream ends."""
        try:
            input_bar = self.query_one("#input-bar", InputBar)
            input_bar.set_enabled(True)
        except Exception:
            pass
        try:
            self.query_one("#user-input").focus()
        except Exception:
            pass

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
            
            asyncio.create_task(self._submit_resume(task_id, {"approval_decision": decision, "approval_reasons": ["User response via TUI"]}))

    async def _submit_resume(self, task_id: str, updates: dict) -> None:
        conv = self.query_one("#conversation", ConversationPanel)
        input_bar = self.query_one("#input-bar", InputBar)

        input_bar.set_enabled(False)
        conv.show_typing_indicator()

        if self._runtime is None:
            conv.hide_typing_indicator()
            conv.append_error("No runtime attached to resume.")
            self._restore_input_bar()
            return
        session_id = self._active_session_id or "default"
        await self._consume_runtime_stream(
            self._runtime.resume(session_id, task_id, updates), "Resume error"
        )


class SamakthaApp(App):
    """Top-level Samaktha TUI application."""

    CSS = SAMAKTHA_CSS
    TITLE = "Samaktha"

    def __init__(self, runtime=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._cmd_registry = CommandRegistry()
        self._command_router = None
        self._register_commands()

    @property
    def command_router(self):
        """The Phase 11.1 Command Router (built on mount)."""
        return getattr(self, "_command_router", None)

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
        self._command_router = self._build_command_router()
        initial_session_id = None
        if self._command_router is not None:
            initial_session_id = self._command_router.create_initial_session()

        if self._runtime is not None and hasattr(self._runtime, "start"):
            self.run_worker(self._runtime.start())

        main = MainScreen(runtime=self._runtime, command_registry=self._cmd_registry, name="main")
        if initial_session_id:
            main._active_session_id = initial_session_id
            main._message_count = 0

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
        self.push_screen(StartupScreen(info=self._build_startup_info(initial_session_id), name="startup"))

    def _build_command_router(self):
        """Build the Phase 11.1 Command Router from the runtime's engines.

        In production this wires the real Phase 10.1 SessionManager plus the
        CAP PolicyEngine / ApprovalEngine (used only by /delete-session). In
        demo mode (no runtime) a temp-dir SessionManager keeps the shell
        commands fully functional.
        """
        base = getattr(self._runtime, "_base", None)
        session_manager = getattr(base, "session_manager", None)
        memory_controller = getattr(base, "memory_controller", None)
        policy_engine = getattr(base, "_policy_engine", None)
        approval_engine = getattr(base, "_approval_engine", None)

        if session_manager is None:
            import tempfile
            from app.memory.session_manager import SessionManager

            session_manager = SessionManager(
                base_dir=tempfile.mkdtemp(prefix="samaktha-shell-")
            )

        from app.shell.command_router import CommandRouter

        def run_doctor() -> str:
            """Render the Phase 11.2 diagnostics report for /doctor."""
            from app.diagnostics import SystemDiagnostics, render_report

            report = SystemDiagnostics(
                settings=getattr(base, "provider_settings", None),
                orchestrator=base,
            ).run()
            return render_report(report)

        return CommandRouter(
            session_manager=session_manager,
            memory_controller=memory_controller,
            policy_engine=policy_engine,
            approval_engine=approval_engine,
            diagnostics=run_doctor,
            conversation_state_manager=getattr(base, "conversation_state_manager", None),
        )

    def _build_startup_info(self, session_id: str | None) -> dict:
        """Collect the Phase 11.1 launch-banner values (version/provider/...)."""
        base = getattr(self._runtime, "_base", None)
        settings = getattr(base, "provider_settings", None)
        provider = getattr(settings, "default_provider", "local") or "local"
        model = (
            getattr(settings, f"{provider}_model", None)
            or getattr(settings, "default_model", None)
            or "—"
        )
        provider_state = "Ready"
        if settings is not None:
            if not settings.is_provider_enabled(provider):
                provider_state = "Disabled"
            elif not settings.is_provider_configured(provider):
                provider_state = "Missing API key"
        return {
            "version": self._package_version(),
            "session_id": session_id or "creating...",
            "provider": provider,
            "model": model,
            "provider_state": provider_state,
            "memory": "Ready",
        }

    def _package_version(self) -> str:
        try:
            from importlib.metadata import version

            return version("samaktha-core")
        except Exception:
            pass
        try:
            from app.config.settings import get_settings

            return get_settings().app_version
        except Exception:
            return "0.x.x"

    def on_unmount(self) -> None:
        if hasattr(self, "_tray_manager"):
            self._tray_manager.stop()
        if hasattr(self, "_hotkey_manager"):
            self._hotkey_manager.unregister()
        if self._runtime is not None and hasattr(self._runtime, "stop"):
            self.run_worker(self._runtime.stop())
