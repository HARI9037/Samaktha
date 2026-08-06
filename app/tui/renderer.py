"""Phase 6.7 — Samaktha TUI Conversation Renderer.

Separates widget construction from the conversation panel state.
Each ConversationMessage produces exactly one RenderedMessage widget.
Extension hooks are marked for future capabilities.
"""

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widget import Widget
from textual.widgets import Label, Button, Markdown as TextualMarkdown

from app.tui.models import ConversationMessage
from app.tui.attachments import Attachment, AttachmentStatus


class RenderedMessage(Widget):
    """Base class for all rendered conversation turns."""

    def __init__(self, message: ConversationMessage, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def update_from_model(self) -> None:
        """Called when the underlying model changes. Override in subclasses."""
        pass


# ---------------------------------------------------------------------------
# Core message types
# ---------------------------------------------------------------------------

class RenderedUserMessage(RenderedMessage):
    def compose(self) -> ComposeResult:
        content = self.message.content
        if isinstance(content, str):
            # Sanitize for Rich markup since markup=True
            content = content.replace("[", "\\[").replace("]", "\\]")
            import re
            content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
            try:
                content.encode('utf-8')
            except UnicodeEncodeError:
                content = content.encode('utf-8', errors='replace').decode('utf-8')
        
        with Vertical(classes="msg-user-container"):
            yield Label("▶ You", classes="msg-user-label")
            yield Label("────────────────────────────", classes="msg-separator")
            yield Label(content, classes="msg-user-content", markup=True, shrink=True)


class RenderedAssistantMessage(RenderedMessage):
    def compose(self) -> ComposeResult:
        with Vertical(classes="msg-assistant-container"):
            yield Label("🔥 Samaktha", classes="msg-assistant-label")
            yield Label("────────────────────────────", classes="msg-separator")
            yield TextualMarkdown("")
            yield Label("", id="code-copy-stub", classes="msg-system")

    def on_mount(self) -> None:
        self.update_from_model()

    def update_from_model(self) -> None:
        try:
            content_md = self.query_one(TextualMarkdown)
            copy_stub = self.query_one("#code-copy-stub", Label)
            display_text = self.message.content
            
            # Sanitize content for Rich markup - escape/clean problematic characters
            if isinstance(display_text, str):
                # Escape Rich markup syntax that could cause MarkupError
                display_text = display_text.replace("[", "\\[").replace("]", "\\]")
                # Remove/replace control characters that could break rendering
                import re
                display_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', display_text)
                # Ensure valid UTF-8
                try:
                    display_text.encode('utf-8')
                except UnicodeEncodeError:
                    display_text = display_text.encode('utf-8', errors='replace').decode('utf-8')
            
            # Simple check for fenced code blocks
            has_code = "```" in display_text
            if has_code and not self.message.streaming:
                copy_stub.update("📋 Copy Available (Use copy_code(index) hook)")
                copy_stub.display = True
            else:
                copy_stub.update("")
                copy_stub.display = False
                
            if self.message.streaming:
                display_text += "▋"
                
            if self.message.markdown:
                import asyncio
                # Textual Markdown update might be coroutine in some versions, or synchronous in others
                if asyncio.iscoroutinefunction(content_md.update):
                    asyncio.create_task(content_md.update(display_text))
                else:
                    content_md.update(display_text)
            else:
                # TextualMarkdown renders plain text effectively anyway
                import asyncio
                if asyncio.iscoroutinefunction(content_md.update):
                    asyncio.create_task(content_md.update(display_text))
                else:
                    content_md.update(display_text)
        except Exception:
            pass


class RenderedSystemMessage(RenderedMessage):
    def compose(self) -> ComposeResult:
        content = self.message.content
        if isinstance(content, str):
            # Sanitize for Rich markup
            content = content.replace("[", "\\[").replace("]", "\\]")
            import re
            content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
            try:
                content.encode('utf-8')
            except UnicodeEncodeError:
                content = content.encode('utf-8', errors='replace').decode('utf-8')
        yield Label(f"◈ {content}", classes="msg-system", shrink=True)


class RenderedErrorMessage(RenderedMessage):
    def compose(self) -> ComposeResult:
        content = self.message.content
        if isinstance(content, str):
            # Sanitize for Rich markup
            content = content.replace("[", "\\[").replace("]", "\\]")
            import re
            content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
            try:
                content.encode('utf-8')
            except UnicodeEncodeError:
                content = content.encode('utf-8', errors='replace').decode('utf-8')
        yield Label(content, classes="msg-system", shrink=True)


# ---------------------------------------------------------------------------
# Agent feedback message types
# ---------------------------------------------------------------------------

class RenderedToolMessage(RenderedMessage):
    """Tool activity line or formatted tool output (like Directory Listings)."""

    def compose(self) -> ComposeResult:
        content = self.message.content
        action = (self.message.action or "").lower().strip()

        if self.message.show_header:
            yield Label("────────────", classes="msg-system")
            yield Label("Tool Output", classes="msg-assistant-label")
            yield Label("────────────", classes="msg-system")
        
        # Route based on explicit action metadata - handle directory listings
        if action in ("list", "list_directory", "ls", "dir", "browse"):
            try:
                if isinstance(content, dict):
                    data = content
                else:
                    import json
                    data = json.loads(content)
                if isinstance(data, dict) and "items" in data and "count" in data:
                    # It's a directory listing!
                    items = data["items"]
                    folder_count = sum(1 for i in items if i.get("type") == "folder")
                    file_count = len(items) - folder_count
                    
                    # Sort folders first, then alphabetically
                    folders = sorted([i for i in items if i.get("type") == "folder"], key=lambda x: x.get("name", "").lower())
                    files = sorted([i for i in items if i.get("type") != "folder"], key=lambda x: x.get("name", "").lower())
                    sorted_items = folders + files

                    def format_size(size_bytes: int) -> str:
                        if size_bytes < 1024:
                            return f"{size_bytes} B"
                        elif size_bytes < 1024 * 1024:
                            return f"{size_bytes / 1024:.0f} KB"
                        else:
                            return f"{size_bytes / (1024 * 1024):.1f} MB"
                    
                    with Vertical(classes="msg-assistant-container"):
                        yield Label(f"📂 {data.get('path', 'Directory')}", classes="msg-assistant-label")
                        yield Label(f"{data.get('count', 0)} items", classes="msg-system")
                        yield Label("────────────────────────────", classes="msg-separator")
                        
                        for item in sorted_items:
                            icon = "📁" if item.get("type") == "folder" else "📄"
                            name = item.get("name", "")
                            
                            if item.get("type") == "folder":
                                yield Label(f"{icon} {name}", shrink=True)
                            else:
                                size_str = format_size(item.get("size", 0))
                                yield Label(f"{icon} {name:<30} {size_str:>10}", shrink=True)
                            
                        yield Label("────────────────────────────", classes="msg-separator")
                        yield Label(f"Totals: {data['count']} items ({folder_count} folders, {file_count} files)", classes="msg-system")
                    return
            except Exception as e:
                with open("C:/Users/user/Desktop/Samaktha/renderer_error.log", "a") as f:
                    f.write(f"Renderer error: {e}\n")
                pass
        
        # For other tool outputs, render as formatted text (not JSON)
        if isinstance(content, dict):
            # Pretty-print dict content without JSON serialization artifacts
            lines = []
            for k, v in content.items():
                if isinstance(v, (list, dict)):
                    import json
                    lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
                else:
                    lines.append(f"{k}: {v}")
            display = "\n".join(lines)
        else:
            display = str(content)
        
        yield Label(display, classes="msg-system", shrink=True, markup=False)


from app.core.events import RuntimeEvent, RuntimeEventBus, RuntimeEventType
from textual.message import Message

class _RuntimeEventReceived(Message):
    """Fired when a RuntimeEvent is received from the bus."""
    def __init__(self, event: RuntimeEvent) -> None:
        self.event = event
        super().__init__()

class RenderedApprovalMessage(RenderedMessage):
    """Inline approval request indicator."""

    def __init__(self, message: ConversationMessage, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self._bus: RuntimeEventBus | None = None

    def attach_bus(self, bus: RuntimeEventBus) -> None:
        """Subscribe to the RuntimeEventBus."""
        self._bus = bus
        self._bus.subscribe(self._on_runtime_event_callback)

    def _on_runtime_event_callback(self, event: RuntimeEvent) -> None:
        """Called directly by the EventBus from an arbitrary context."""
        self.post_message(_RuntimeEventReceived(event))

    def on_runtime_event_received(self, message: _RuntimeEventReceived) -> None:
        """Handle the RuntimeEvent safely on the UI thread."""
        if message.event.type in (RuntimeEventType.CAP_STARTED, RuntimeEventType.WORKFLOW_SCHEDULED):
            self.remove()

    def compose(self) -> ComposeResult:
        action_text = "CAP Approval Required"
        if self.message.pause_data:
            metadata = self.message.pause_data.get("metadata", {})
            action = metadata.get("action", metadata.get("action_type", "Unknown"))
            args = metadata.get("args", {})
            
            target = args.get("path") or args.get("target_path") or args.get("query") or ""
            
            # Contextual formatting
            if action == "list":
                action_text = f"CAP requests permission to: Browse folder {target}"
            elif action in ("read", "extract_text", "analyze"):
                action_text = f"CAP requests permission to: Read file {target}"
            elif action == "delete":
                action_text = f"CAP requests permission to: Delete file {target}"
            elif action in ("rename", "move"):
                action_text = f"CAP requests permission to: Rename file {target}"
            else:
                action_text = f"CAP requests permission to: {action} {target}".strip()
        
        # Sanitize for Rich markup
        if isinstance(action_text, str):
            action_text = action_text.replace("[", "\\[").replace("]", "\\]")
            import re
            action_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', action_text)
            try:
                action_text.encode('utf-8')
            except UnicodeEncodeError:
                action_text = action_text.encode('utf-8', errors='replace').decode('utf-8')
        
        with Vertical(classes="msg-assistant-container"):
            yield Label("🔥 Samaktha", classes="msg-assistant-label")
            yield Label("────────────────────────────", classes="msg-separator")
            
            yield Label(action_text, markup=True)
            yield Label("────────────────────────────", classes="msg-separator")
                
            with Horizontal(classes="msg-approval-buttons"):
                yield Button("[Y] Allow", id=f"btn_allow_{self.message.task_id}", variant="success")
                yield Button("[N] Deny", id=f"btn_deny_{self.message.task_id}", variant="error")


# ---------------------------------------------------------------------------
# Attachment message types
# ---------------------------------------------------------------------------

class RenderedAttachmentMessage(RenderedMessage):
    """Compact card for a file attachment."""
    
    def compose(self) -> ComposeResult:
        if not self.message.attachment:
            yield Label("⚠ Invalid Attachment", classes="msg-error")
            return
            
        att = self.message.attachment
        
        # Simple size formatting
        size_kb = max(1, att.size // 1024)
        size_str = f"{size_kb} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        
        # Status icon
        status_icons = {
            AttachmentStatus.QUEUED: "⏳",
            AttachmentStatus.UPLOADED: "✓",
            AttachmentStatus.PROCESSING: "⏳",
            AttachmentStatus.READY: "✓",
            AttachmentStatus.FAILED: "✖",
        }
        icon = status_icons.get(att.status, "•")
        
        # UI Presentation (Minimal Card)
        with Vertical(classes="msg-attachment-card"):
            yield Label(f"📄 {att.filename}", classes="msg-attachment-title")
            yield Label(f"{size_str} • {icon} {att.status.value}", classes="msg-attachment-meta")


# ---------------------------------------------------------------------------
# Extension hooks (reserved for future phases — do not implement yet)
# ---------------------------------------------------------------------------
# HOOK: attachments  — RenderedAttachmentMessage
# HOOK: voice        — RenderedVoiceMessage
# HOOK: images       — RenderedImageMessage
# HOOK: tool_cards   — RenderedToolCardMessage


# ---------------------------------------------------------------------------
# Renderer factory
# ---------------------------------------------------------------------------

class ConversationRenderer:
    """Creates the correct RenderedMessage widget from a ConversationMessage."""

    @staticmethod
    def render(message: ConversationMessage) -> RenderedMessage:
        if message.error:
            if message.role == "approval":
                return RenderedApprovalMessage(message)
            return RenderedErrorMessage(message)
        elif message.role == "user":
            return RenderedUserMessage(message)
        elif message.role == "assistant":
            return RenderedAssistantMessage(message)
        elif message.role == "tool":
            return RenderedToolMessage(message)
        elif message.role == "attachment":
            return RenderedAttachmentMessage(message)
        else:
            return RenderedSystemMessage(message)

    @staticmethod
    def render_tool(tool_name: str, done: bool = False) -> RenderedMessage:
        """Convenience factory for compact tool activity messages."""
        if done:
            content = f"✓ {tool_name} complete"
        else:
            content = f"🔧 Running {tool_name}..."
        msg = ConversationMessage(role="tool", content=content, markdown=False)
        return RenderedToolMessage(msg)

    @staticmethod
    def render_approval(task_id: str | None = None, pause_data: dict | None = None) -> RenderedMessage:
        """Convenience factory for approval request messages."""
        msg = ConversationMessage(role="approval", content="", error=True, markdown=False, task_id=task_id, pause_data=pause_data)
        return RenderedApprovalMessage(msg)


class AttachmentRenderer:
    """Factory for routing attachments to the correct visual representation.
    
    Currently returns the base RenderedAttachmentMessage, but architected
    to support specialized rendering by file type.
    """

    @staticmethod
    def render(attachment: Attachment) -> RenderedMessage:
        # Future routing by preview_type
        if attachment.preview_type == "document":
            return AttachmentRenderer.render_document(attachment)
        elif attachment.preview_type == "image":
            return AttachmentRenderer.render_image(attachment)
        elif attachment.preview_type == "audio":
            return AttachmentRenderer.render_audio(attachment)
        elif attachment.preview_type == "video":
            return AttachmentRenderer.render_video(attachment)
        elif attachment.preview_type == "archive":
            return AttachmentRenderer.render_archive(attachment)
        
        return AttachmentRenderer.render_unknown(attachment)

    @staticmethod
    def render_document(attachment: Attachment) -> RenderedMessage:
        msg = ConversationMessage(role="attachment", attachment=attachment, markdown=False)
        return RenderedAttachmentMessage(msg)

    @staticmethod
    def render_image(attachment: Attachment) -> RenderedMessage:
        msg = ConversationMessage(role="attachment", attachment=attachment, markdown=False)
        return RenderedAttachmentMessage(msg)

    @staticmethod
    def render_audio(attachment: Attachment) -> RenderedMessage:
        msg = ConversationMessage(role="attachment", attachment=attachment, markdown=False)
        return RenderedAttachmentMessage(msg)

    @staticmethod
    def render_video(attachment: Attachment) -> RenderedMessage:
        msg = ConversationMessage(role="attachment", attachment=attachment, markdown=False)
        return RenderedAttachmentMessage(msg)

    @staticmethod
    def render_archive(attachment: Attachment) -> RenderedMessage:
        msg = ConversationMessage(role="attachment", attachment=attachment, markdown=False)
        return RenderedAttachmentMessage(msg)

    @staticmethod
    def render_unknown(attachment: Attachment) -> RenderedMessage:
        msg = ConversationMessage(role="attachment", attachment=attachment, markdown=False)
        return RenderedAttachmentMessage(msg)

