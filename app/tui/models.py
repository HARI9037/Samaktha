"""Phase 6.6B — Samaktha TUI Models.

Contains the data structures for TUI conversation rendering.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.tui.attachments import Attachment


@dataclass
class ConversationMessage:
    """Represents a single turn in the conversation."""
    role: str  # "user", "assistant", "system", "error", "tool", "approval", "attachment"
    content: Any = ""
    timestamp: datetime = field(default_factory=datetime.now)
    streaming: bool = False
    error: bool = False
    markdown: bool = True
    attachment: Optional[Attachment] = None
    task_id: Optional[str] = None
    pause_data: Optional[dict] = None
    action: Optional[str] = None
    show_header: bool = False
