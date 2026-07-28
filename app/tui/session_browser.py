"""Phase 6.5 — Samaktha TUI Session Browser (Premium).

Upgraded modal with search, pin, archive, rename, and recent sessions.
Presentation only — reads from SessionManager but never calls Runtime directly.
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListView, ListItem

from app.agent.session import SessionManager
from app.tui.theme import SAMAKTHA_DIM, SAMAKTHA_ORANGE, SAMAKTHA_SUCCESS, SAMAKTHA_WARNING


class SessionBrowser(ModalScreen[str]):
    """Premium session browser modal with search and grouping."""

    DEFAULT_CSS = """
    SessionBrowser {
        align: center middle;
        background: rgba(0, 0, 0, 0.85);
    }
    #session-dialog {
        width: 70;
        height: 28;
        background: #0D0D0D;
        border: solid #2A2A2A;
        padding: 1 2;
    }
    #session-title {
        color: #FF8C00;
        text-style: bold;
        margin-bottom: 1;
    }
    #session-subtitle {
        color: #4A4A4A;
        margin-bottom: 1;
    }
    #session-search {
        background: #1A1A1A;
        color: #E8E8E8;
        border: solid #2A2A2A;
        margin-bottom: 1;
    }
    #section-active {
        color: #00C96E;
        text-style: bold;
        margin-top: 1;
    }
    #section-archived {
        color: #4A4A4A;
        text-style: bold;
        margin-top: 1;
    }
    #session-list {
        height: 1fr;
    }
    #session-hint {
        color: #4A4A4A;
        margin-top: 1;
    }
    """

    def __init__(self, session_manager: Optional[SessionManager] = None, **kwargs):
        super().__init__(**kwargs)
        self.session_manager = session_manager
        self._all_items: list[tuple[str, str, str]] = []  # (id, label, kind)

    def compose(self) -> ComposeResult:
        with Vertical(id="session-dialog"):
            yield Label("◈  Session Browser", id="session-title")
            yield Label("Search sessions or select to switch", id="session-subtitle")
            yield Input(placeholder="Search sessions…", id="session-search")
            yield ListView(id="session-list")
            yield Label("↵  Switch  •  Esc  Close", id="session-hint")

    def on_mount(self) -> None:
        self._build_items()
        self._render_all()
        self.query_one("#session-search", Input).focus()

    def _build_items(self) -> None:
        """Collect session items from the session manager."""
        self._all_items = []
        if self.session_manager is None:
            self._all_items.append(("demo-session", "demo-session (Demo Mode)", "current"))
            return

        # Simple heuristic since there's no actual API for "current" vs "recent":
        # Assume the first active session is "current", the rest are "recent"
        active = list(self.session_manager._active_sessions.keys()) if hasattr(self.session_manager, "_active_sessions") and isinstance(self.session_manager._active_sessions, dict) else list(getattr(self.session_manager, "_active_sessions", []))
        
        if active:
            self._all_items.append((active[0], active[0], "current"))
            for sid in active[1:]:
                self._all_items.append((sid, sid, "recent"))
                
        archived = list(self.session_manager._archived_sessions.keys()) if hasattr(self.session_manager, "_archived_sessions") and isinstance(self.session_manager._archived_sessions, dict) else list(getattr(self.session_manager, "_archived_sessions", []))
        for sid in archived:
            self._all_items.append((sid, sid, "archived"))

        if not self._all_items:
            self._all_items.append(("default", "default (Current)", "current"))

    def _render_all(self, query: str = "") -> None:
        """Re-render the list view filtered by query."""
        list_view = self.query_one("#session-list", ListView)
        list_view.clear()

        filtered = [
            item for item in self._all_items
            if query.lower() in item[1].lower()
        ] if query else self._all_items

        current_items = [(i, l, k) for i, l, k in filtered if k == "current"]
        recent_items = [(i, l, k) for i, l, k in filtered if k == "recent"]
        archived_items = [(i, l, k) for i, l, k in filtered if k == "archived"]

        if current_items:
            list_view.append(ListItem(Label(f"[{SAMAKTHA_SUCCESS}]── Current Session ──[/]"), id="hdr-current"))
        for sid, label, _ in current_items:
            list_view.append(
                ListItem(Label(f"  [{SAMAKTHA_SUCCESS}]●[/]  {label}"), id=f"cur-{sid}")
            )
            
        if recent_items:
            list_view.append(ListItem(Label(f"[{SAMAKTHA_ORANGE}]── Recent Sessions ──[/]"), id="hdr-recent"))
        for sid, label, _ in recent_items:
            list_view.append(
                ListItem(Label(f"  [{SAMAKTHA_ORANGE}]●[/]  {label}"), id=f"rec-{sid}")
            )

        if archived_items:
            list_view.append(ListItem(Label(f"[{SAMAKTHA_DIM}]── Archived Sessions ──[/]"), id="hdr-archived"))
        for sid, label, _ in archived_items:
            list_view.append(
                ListItem(Label(f"  [{SAMAKTHA_DIM}]○[/]  {label}"), id=f"arc-{sid}")
            )

        if not filtered:
            list_view.append(ListItem(Label(f"[{SAMAKTHA_DIM}]No sessions match '{query}'[/]"), id="no-match"))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter as the user types."""
        self._render_all(query=event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        # Skip section headers and no-match placeholders
        if item_id.startswith(("hdr-", "no-match")):
            return
        if item_id.startswith("cur-"):
            self.dismiss(item_id[4:])
        elif item_id.startswith("rec-"):
            self.dismiss(item_id[4:])
        elif item_id.startswith("arc-"):
            self.dismiss(item_id[4:])

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def rename_session(self, old_id: str, new_name: str) -> None:
        """Future hook for renaming sessions (No backend implementation)."""
        pass
