"""Phase 11.1 — Samaktha Shell Command Router.

Deterministic, testable slash-command handling for the Samaktha TUI. Sits
between the TUI and the orchestrator: slash commands are parsed and executed
here and NEVER reach the GoalParser / CAP / GAMBIT / LLM / Provider pipeline.

The only exception is ``/delete-session``, which passes through the real CAP
``PolicyEngine`` + ``ApprovalEngine`` before any file is removed. No memory
learning, no scoring, no embeddings — this layer is a pure function of the
command text and the session index.

This module deliberately lives outside ``app/tui`` so the shell layer may
reuse the core trust-boundary engines (CAP) and the memory/session subsystems
directly without crossing the UI architecture boundary.
"""

from __future__ import annotations

import shlex
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.contracts.policy import (
    ApprovalDecision,
    ApprovalRequest,
    PermissionScope,
    PlannedAction,
)
from app.memory.session_manager import SessionManager
from app.memory.session_store import (
    session_memory_json_path,
    session_memory_md_path,
)

COMMAND_DEFINITIONS: list[tuple[str, str]] = [
    ("new", "Start a fresh session"),
    ("clear", "Clear the conversation window"),
    ("session", "Show the current session"),
    ("sessions", "List recent sessions"),
    ("switch", "Switch to a session: /switch <session-id>"),
    ("delete-session", "Delete a session (requires approval): /delete-session <session-id>"),
    ("doctor", "Run Samaktha diagnostics"),
    ("repo", "Inspect the current repository"),
    ("workspace", "Summarize the current workspace"),
    ("review", "Run a deterministic code review"),
    ("debug", "Summarize a failure trace"),
    ("explain", "Explain the current project"),
    ("tests", "Analyze test impact"),
    ("status", "Show repository status"),
    ("changes", "Summarize changed files"),
    ("performance", "Review performance concerns"),
    ("security", "Review security concerns"),
    ("architecture", "Summarize architecture"),
    ("summarize", "Summarize the project"),
    ("help", "Show available commands"),
    ("exit", "Exit Samaktha"),
]

_COMMAND_NAMES: list[str] = [name for name, _description in COMMAND_DEFINITIONS]


def command_names() -> list[str]:
    """Deterministic list of slash-command names (without the leading slash)."""
    return list(_COMMAND_NAMES)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_session_label(iso: str) -> str:
    """Render a session timestamp as a readable id label.

    ``2026-08-02T18:43:11.123Z`` → ``2026-08-02_18-43-11``
    """
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d_%H-%M-%S")


def format_session_time(iso: str, now: datetime | None = None) -> str:
    """Human-friendly relative time for a session timestamp.

    Today → "Today 18:41"; yesterday → "Yesterday"; otherwise a short date.
    """
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    local_dt = dt.astimezone()
    local_now = reference.astimezone()
    today = local_now.date()
    day = local_dt.date()
    if day == today:
        return f"Today {local_dt.strftime('%H:%M')}"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return local_dt.strftime("%b %d, %Y")


@dataclass
class CommandResult:
    """The result of executing one slash command.

    ``action`` is a machine-readable hint for the TUI so it can perform
    widget-level effects (clearing the panel, switching the active session,
    quitting) that are out of scope for the pure command layer.
    """

    handled: bool
    output: str = ""
    action: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class CommandRouter:
    """Parses and executes slash commands; never talks to the orchestrator.

    A command is considered handled when its text is a known slash command.
    Unknown slash text returns ``CommandResult(handled=False)`` so the caller
    can decide whether to fall back to legacy commands or report an error.
    """

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        memory_controller: Any | None = None,
        policy_engine: Any | None = None,
        approval_engine: Any | None = None,
        clock: Callable[[], str] = _utc_now,
        subject_id: str = "local-user",
        diagnostics: Callable[[], str] | None = None,
        conversation_state_manager: Any | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._memory_controller = memory_controller
        self._policy_engine = policy_engine
        self._approval_engine = approval_engine
        self._clock = clock
        self._subject_id = subject_id
        self._diagnostics = diagnostics
        self._conversation_state = conversation_state_manager
        self._pending_delete: str | None = None
        self._handlers: dict[str, Callable[..., CommandResult | Any]] = {
            "new": self._cmd_new,
            "clear": self._cmd_clear,
            "session": self._cmd_session,
            "sessions": self._cmd_sessions,
            "switch": self._cmd_switch,
            "delete-session": self._cmd_delete_session,
            "doctor": self._cmd_doctor,
            "repo": self._cmd_repo,
            "workspace": self._cmd_workspace,
            "review": self._cmd_review,
            "debug": self._cmd_debug,
            "explain": self._cmd_explain,
            "tests": self._cmd_tests,
            "status": self._cmd_status,
            "changes": self._cmd_changes,
            "performance": self._cmd_performance,
            "security": self._cmd_security,
            "architecture": self._cmd_architecture,
            "summarize": self._cmd_summarize,
            "help": self._cmd_help,
            "exit": self._cmd_exit,
        }

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @property
    def session_manager(self) -> SessionManager | None:
        """The SessionManager backing this router (may be None in demo mode)."""
        return self._session_manager

    def is_command(self, text: str) -> bool:
        """True when ``text`` is one of the router's known slash commands."""
        return self._parse(text) is not None

    def parse(self, text: str) -> tuple[str, list[str]] | None:
        """Split command text into (name, args); None when not a command."""
        return self._parse(text)

    def _parse(self, text: str) -> tuple[str, list[str]] | None:
        text = (text or "").strip()
        if not text.startswith("/"):
            return None
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()
        if not parts:
            return None
        name = parts[0][1:].lower()
        if name not in self._handlers:
            return None
        return name, parts[1:]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        text: str,
        active_session_id: str | None = None,
    ) -> CommandResult:
        """Execute a slash command. Returns a CommandResult.

        ``active_session_id`` is the session the TUI currently displays; the
        router uses it for message counts, saving, and rotation when the
        active session is deleted.
        """
        parsed = self._parse(text)
        if parsed is None:
            return CommandResult(handled=False)
        name, args = parsed
        if name == "delete-session":
            return await self._cmd_delete_session(active_session_id, args)
        return self._handlers[name](active_session_id, args)

    async def execute_delete(
        self,
        session_id: str,
        active_session_id: str | None = None,
    ) -> CommandResult:
        """Directly run the CAP-gated deletion flow for ``session_id``."""
        return await self._cmd_delete_session(active_session_id, [session_id])

    def confirm_delete(self, active_session_id: str | None, approve: bool) -> CommandResult:
        """Resolve a pending /delete-session approval (user replied y/n)."""
        session_id = self._pending_delete
        self._pending_delete = None
        if session_id is None:
            return CommandResult(handled=True, output="No pending deletion.")
        if not approve:
            return CommandResult(handled=True, output="Deletion cancelled.")
        if self._session_manager is None:
            return CommandResult(handled=True, output="Session storage is unavailable.")
        if not self._session_manager.session_exists(session_id):
            return CommandResult(handled=True, output=f"Session not found: {session_id}")
        return self._finish_delete(active_session_id, session_id)

    # ------------------------------------------------------------------
    # Lifecycle helpers used by the TUI
    # ------------------------------------------------------------------

    def create_initial_session(self) -> str:
        """Create the session used at startup; returns its session id."""
        if self._session_manager is None:
            return "default"
        session = self._session_manager.create_session()
        return session.session_id

    def save_active_session(self, session_id: str | None, message_count: int) -> None:
        """Persist the active session's message count (touches updated_at)."""
        if self._session_manager is None or not session_id:
            return
        try:
            self._session_manager.update_metadata(
                session_id, message_count=message_count
            )
        except Exception:
            pass

    def reload_session(self, session_id: str | None) -> CommandResult:
        """Re-read the persisted active session state for the TUI reload action."""
        if self._session_manager is None or not session_id:
            return CommandResult(
                handled=True,
                output="No session to reload.",
                action="reload_session",
                payload={"session_id": session_id or "default", "message_count": 0},
            )
        try:
            metadata = self._session_manager.load_session(session_id).metadata
        except Exception:
            return CommandResult(
                handled=True,
                output=f"Session not found: {session_id}",
                action="reload_session",
                payload={"session_id": session_id, "message_count": None},
            )
        label = format_session_label(metadata.created_at)
        return CommandResult(
            handled=True,
            output=(
                "Reloaded session\n\n"
                f"Session:\n{label}\n\n"
                f"Messages:\n{metadata.message_count}"
            ),
            action="reload_session",
            payload={"session_id": session_id, "message_count": metadata.message_count},
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _cmd_new(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        if self._session_manager is None:
            return CommandResult(
                handled=True,
                output="Session storage is unavailable.",
                action="new_session",
                payload={"session_id": "default", "message_count": 0},
            )
        self._save_active(active_session_id)
        session = self._session_manager.create_session()
        if self._conversation_state is not None:
            self._conversation_state.reset(session.session_id)
        label = format_session_label(session.metadata.created_at)
        count = self._conversation_memory_count(session.session_id)
        output = (
            "Started new session\n\n"
            f"Session:\n{label}\n\n"
            f"Conversation memories:\n{count}\n\n"
            "Context:\nFresh\n\n"
            "Ready."
        )
        return CommandResult(
            handled=True,
            output=output,
            action="new_session",
            payload={"session_id": session.session_id, "message_count": 0},
        )

    def _cmd_clear(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return CommandResult(handled=True, output="", action="clear")

    def _cmd_session(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        if self._session_manager is None:
            return CommandResult(handled=True, output="Session storage is unavailable.")
        session_id = active_session_id or "default"
        try:
            metadata = self._session_manager.load_session(session_id).metadata
        except Exception:
            return CommandResult(handled=True, output="No active session. Start one with /new.")
        base = self._session_manager.base_dir
        output = (
            "Current Session\n\n"
            f"ID: {metadata.session_id}\n"
            f"Created: {format_session_time(metadata.created_at)}\n"
            f"Message Count: {metadata.message_count}\n"
            f"Conversation Memories: {self._conversation_memory_count(metadata.session_id)}\n"
            f"Session Markdown Path: {session_memory_md_path(base, metadata.session_id)}\n"
            f"Session JSON Path: {session_memory_json_path(base, metadata.session_id)}"
        )
        return CommandResult(handled=True, output=output)

    def _cmd_sessions(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        if self._session_manager is None:
            return CommandResult(handled=True, output="Session storage is unavailable.")
        entries = self._session_manager.list_sessions()
        if not entries:
            return CommandResult(handled=True, output="No sessions yet.\n\nStart one with /new.")
        lines = ["Recent Sessions", ""]
        for index, metadata in enumerate(entries, start=1):
            lines.append(f"{index}.")
            lines.append(format_session_time(metadata.updated_at))
            lines.append("")
            lines.append(f"Messages: {metadata.message_count}")
            lines.append("")
        return CommandResult(handled=True, output="\n".join(lines).rstrip())

    def _cmd_switch(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(handled=True, output="Usage: /switch <session-id>")
        session_id = args[0]
        if self._session_manager is None:
            return CommandResult(handled=True, output="Session storage is unavailable.")
        if not self._session_manager.session_exists(session_id):
            return CommandResult(handled=True, output=f"Session not found: {session_id}")
        metadata = self._session_manager.load_session(session_id).metadata
        output = (
            "Switched to session\n\n"
            f"Session:\n{session_id}\n\n"
            f"Messages:\n{metadata.message_count}"
        )
        return CommandResult(
            handled=True,
            output=output,
            action="switch_session",
            payload={"session_id": session_id, "message_count": metadata.message_count},
        )

    async def _cmd_delete_session(
        self, active_session_id: str | None, args: list[str]
    ) -> CommandResult:
        if not args:
            return CommandResult(handled=True, output="Usage: /delete-session <session-id>")
        session_id = args[0]
        if self._session_manager is None or not self._session_manager.session_exists(session_id):
            return CommandResult(handled=True, output=f"Session not found: {session_id}")

        decision = await self._approve_delete(session_id)
        if decision == ApprovalDecision.DENY:
            return CommandResult(handled=True, output="⚠ Deletion denied by CAP policy.")
        if decision == ApprovalDecision.ASK_USER:
            self._pending_delete = session_id
            output = (
                "⚠ Deletion requires approval.\n\n"
                f"Deleting session {session_id} will permanently remove its session files "
                "and all conversation memories linked to it.\n\n"
                "Reply y to confirm or n to cancel."
            )
            return CommandResult(
                handled=True,
                output=output,
                action="delete_session_pending",
                payload={"session_id": session_id},
            )
        # ALLOW / remembered permission — delete immediately.
        return self._finish_delete(active_session_id, session_id)

    def _cmd_help(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        lines = ["Available Commands", ""]
        for name, description in COMMAND_DEFINITIONS:
            lines.append(f"/{name} — {description}")
        return CommandResult(handled=True, output="\n".join(lines))

    def _cmd_doctor(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        if self._diagnostics is None:
            return CommandResult(
                handled=True,
                output="Diagnostics unavailable.\n\nStart Samaktha with a runtime to run /doctor.",
            )
        try:
            return CommandResult(handled=True, output=self._diagnostics())
        except Exception as exc:
            return CommandResult(handled=True, output=f"⚠ Diagnostics failed: {exc}")

    def _cmd_repo(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Repository")

    def _cmd_workspace(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Workspace")

    def _cmd_review(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        from app.developer.review import ReviewEngine

        engine = ReviewEngine()
        result = engine.review_repository(Path.cwd())
        counts = result.by_severity()
        lines = [
            "Review",
            "",
            f"Scanned {len(result.files_scanned)} files, {result.count()} findings",
            (
                f"HIGH: {counts['high']} | MEDIUM: {counts['medium']} | "
                f"LOW: {counts['low']} | INFO: {counts['info']}"
            ),
        ]
        if result.errors:
            lines.append(f"Errors: {len(result.errors)}")
        findings = result.sorted_findings()
        for finding in findings[:20]:
            location = finding.file
            if finding.line is not None:
                location = f"{location}:{finding.line}"
            lines.append("")
            lines.append(
                f"- [{finding.severity.value.upper()}] {finding.rule} — {location}"
            )
            lines.append(f"  {finding.message}")
            if finding.evidence:
                lines.append(f"  evidence: {finding.evidence[:200]}")
        if len(findings) > 20:
            lines.append("")
            lines.append(f"... and {len(findings) - 20} more findings")
        for error in result.errors[:10]:
            lines.append("")
            lines.append(f"⚠ {error}")
        return CommandResult(handled=True, output="\n".join(lines))

    def _cmd_debug(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Debug")

    def _cmd_explain(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Explain")

    def _cmd_tests(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Tests")

    def _cmd_status(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Status")

    def _cmd_changes(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Changes")

    def _cmd_performance(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Performance")

    def _cmd_security(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Security")

    def _cmd_architecture(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Architecture")

    def _cmd_summarize(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        return self._developer_summary("Summary")

    def _cmd_exit(self, active_session_id: str | None, args: list[str]) -> CommandResult:
        self._save_active(active_session_id)
        self._pending_delete = None
        return CommandResult(handled=True, output="Goodbye.", action="exit")

    # ------------------------------------------------------------------
    # CAP-gated deletion
    # ------------------------------------------------------------------

    async def _approve_delete(self, session_id: str) -> ApprovalDecision:
        if self._policy_engine is None or self._approval_engine is None:
            return ApprovalDecision.DENY
        action = PlannedAction(
            action_id=f"shell-delete-{uuid.uuid4().hex[:12]}",
            action_type="delete",
            description=f"Delete session {session_id}",
            target=session_id,
            payload={"resource": "session", "session_id": session_id},
            requested_permissions=[PermissionScope.DELETE],
        )
        try:
            policy = self._policy_engine.evaluate(action)
            result = await self._approval_engine.decide(
                ApprovalRequest(action=action, policy=policy),
                self._subject_id,
            )
            return result.decision
        except Exception:
            return ApprovalDecision.DENY

    def _finish_delete(
        self, active_session_id: str | None, session_id: str
    ) -> CommandResult:
        removed = self._delete_conversation_memories(session_id)
        if self._conversation_state is not None:
            self._conversation_state.remove(session_id)
        deleted = False
        if self._session_manager is not None:
            deleted = self._session_manager.delete_session(session_id)
        if not deleted:
            return CommandResult(handled=True, output=f"Could not delete session: {session_id}")

        was_active = active_session_id == session_id
        if was_active:
            session = self._session_manager.create_session()
            if self._conversation_state is not None:
                self._conversation_state.reset(session.session_id)
            output = (
                f"Deleted session {session_id}\n\n"
                f"Conversation memories removed: {removed}\n\n"
                "Started new session\n\n"
                f"Session:\n{format_session_label(session.metadata.created_at)}\n\n"
                "Context:\nFresh\n\n"
                "Ready."
            )
            return CommandResult(
                handled=True,
                output=output,
                action="delete_session",
                payload={"session_id": session.session_id, "message_count": 0, "was_active": True},
            )
        return CommandResult(
            handled=True,
            output=f"Deleted session {session_id}\n\nConversation memories removed: {removed}",
            action="delete_session",
            payload={"session_id": active_session_id, "message_count": None, "was_active": False},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_active(self, session_id: str | None) -> None:
        """Persist the active session so its updated_at reflects this turn."""
        if self._session_manager is None or not session_id:
            return
        try:
            self._session_manager.save_session(
                self._session_manager.load_session(session_id)
            )
        except Exception:
            pass

    def _conversation_memory_count(self, session_id: str) -> int:
        manager = getattr(self._memory_controller, "memory_manager", None)
        if manager is None:
            return 0
        try:
            items = manager.get_recent_context(n=10000, allow_private=True)
        except Exception:
            return 0
        return sum(
            1
            for item in items
            if (getattr(item, "metadata", None) or {}).get("session_id") == session_id
        )

    def _delete_conversation_memories(self, session_id: str) -> int:
        """Remove long-term conversation memories attached to a session."""
        if self._memory_controller is None:
            return 0
        manager = getattr(self._memory_controller, "memory_manager", None)
        if manager is None:
            return 0
        try:
            items = manager.get_recent_context(n=10000, allow_private=True)
        except Exception:
            return 0
        removed = 0
        for item in items:
            if (getattr(item, "metadata", None) or {}).get("session_id") != session_id:
                continue
            try:
                self._memory_controller.delete_memory(item.id)
                removed += 1
            except Exception:
                pass
        return removed

    def _developer_summary(self, label: str) -> CommandResult:
        from app.developer.repository.inspector import RepositoryInspector

        inspector = RepositoryInspector(Path.cwd())
        summary = inspector.inspect()
        output = (
            f"{label}\n\n"
            f"Root: {summary.root}\n"
            f"Branch: {summary.branch or 'unknown'}\n"
            f"Languages: {', '.join(summary.languages) or 'unknown'}\n"
            f"Frameworks: {', '.join(summary.frameworks) or 'unknown'}\n"
            f"README: {summary.readme_summary or 'none'}"
        )
        return CommandResult(handled=True, output=output)
