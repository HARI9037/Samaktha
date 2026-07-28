"""Phase 6.8 — Samaktha TUI Attachments Layer.

Defines the core Attachment model and extension hooks for rich content rendering.
No backend processing. Pure presentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label


class AttachmentStatus(str, Enum):
    """Lifecycle status of an attachment."""
    QUEUED = "Queued"
    UPLOADED = "Uploaded"
    PROCESSING = "Processing"
    READY = "Ready"
    FAILED = "Failed"


@dataclass
class Attachment:
    """Single source of truth for an uploaded file in the UI."""
    path: str
    filename: str
    extension: str
    mime_type: str
    size: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: AttachmentStatus = AttachmentStatus.UPLOADED
    preview_type: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Extension Hooks (for future drag & drop)
# ---------------------------------------------------------------------------

def on_file_drop(path: str) -> None:
    """Stub hook for future platform drag-and-drop events."""
    pass


def on_attachment_added() -> None:
    """Stub hook for when an attachment is successfully added."""
    pass


# ---------------------------------------------------------------------------
# Preview Widgets (Architecture stubs for future intelligence phases)
# ---------------------------------------------------------------------------

class AttachmentPreview(Widget):
    """Base class for rich attachment previews."""
    def compose(self) -> ComposeResult:
        yield Label("Preview not implemented")


class DocumentPreview(AttachmentPreview):
    """Future stub for Document Intelligence previews."""
    pass


class ImagePreview(AttachmentPreview):
    """Future stub for Vision previews."""
    pass


class AudioPreview(AttachmentPreview):
    """Future stub for Audio intelligence previews."""
    pass


class VideoPreview(AttachmentPreview):
    """Future stub for Video intelligence previews."""
    pass
