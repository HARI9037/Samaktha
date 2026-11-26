"""Phase 6.7 — Samaktha TUI Conversation Renderer.

Separates widget construction from the conversation panel state.
Each ConversationMessage produces exactly one RenderedMessage widget.
Extension hooks are marked for future capabilities.
"""

import logging

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widget import Widget
from textual.widgets import Label, Button, Markdown as TextualMarkdown

from app.tui.models import ConversationMessage
from app.tui.attachments import Attachment, AttachmentStatus

log = logging.getLogger(__name__)


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

        def sanitize(text: str) -> str:
            if not isinstance(text, str):
                text = str(text)
            text = text.replace("[", "\\[").replace("]", "\\]")
            import re
            text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
            try:
                text.encode('utf-8')
            except UnicodeEncodeError:
                text = text.encode('utf-8', errors='replace').decode('utf-8')
            return text

        # Handle structured ERROR event (event_type: "ERROR" with payload)
        if isinstance(content, dict) and content.get("event_type") == "ERROR":
            error_payload = content.get("payload", {})
            error_code = sanitize(error_payload.get("error_code", "UNKNOWN_ERROR"))
            error_message = sanitize(error_payload.get("error_message", ""))
            details = error_payload.get("details")

            yield Label(f"Event: ERROR", classes="msg-system", shrink=True)
            yield Label(f"Error Code: {error_code}", classes="msg-error", shrink=True)
            yield Label(f"Message: {error_message}", classes="msg-system", shrink=True)
            if details:
                import json
                yield Label(f"Details: {json.dumps(details, ensure_ascii=False)}", classes="msg-system", shrink=True)
        elif isinstance(content, str):
            # Sanitize for Rich markup
            content = sanitize(content)
            yield Label(content, classes="msg-system", shrink=True)
        else:
            # Fallback: stringify
            yield Label(sanitize(str(content)), classes="msg-system", shrink=True)


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
            except Exception:
                # Rendering failures must not write exception content to an
                # unmanaged, hard-coded path.  Tool data and paths may be
                # sensitive; fall back to the generic safe renderer below.
                log.debug("Directory tool-output rendering failed")
        
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
        action_text = "\n".join(_approval_summary_lines(self.message.pause_data))
        
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


def _approval_summary_lines(pause_data: dict | None) -> list[str]:
    """Return bounded, user-readable details for the exact proposed action."""
    metadata = (pause_data or {}).get("metadata", {})
    action = str(metadata.get("action") or metadata.get("action_type") or "Unknown")
    tool = metadata.get("tool")
    args = metadata.get("args") if isinstance(metadata.get("args"), dict) else {}
    target = metadata.get("target") or next(
        (
            args.get(key)
            for key in (
                "path", "target_path", "destination", "recipient", "to",
                "url", "host", "query", "command", "executable", "name",
            )
            if args.get(key)
        ),
        None,
    )
    lines = ["CAP Approval Required", f"Action: {action}"]
    if tool:
        lines.append(f"Tool: {tool}")
    if target:
        lines.append(f"Target: {target}")
    if args:
        details = ", ".join(
            f"{key}={value}" for key, value in sorted(args.items())
        )
        lines.append(f"Important arguments: {details}")
    risk = metadata.get("risk")
    if risk:
        lines.append(f"Risk: {risk}")
    permissions = metadata.get("permissions")
    if isinstance(permissions, list) and permissions:
        lines.append(f"Permissions: {', '.join(str(item) for item in permissions)}")
    lines.append("Allow executes only this exact bound operation; Deny executes nothing.")
    return [line[:1000] for line in lines]


# ---------------------------------------------------------------------------
# Structured Protocol Event Message Types (M5)
# ---------------------------------------------------------------------------

class RenderedSearchResultsMessage(RenderedMessage):
    """Structured rendering for SEARCH events (STARTED, COMPLETED, FAILED)."""

    def compose(self) -> ComposeResult:
        content = self.message.content
        event_type = ""

        # Extract event_type from content
        if isinstance(content, dict):
            event_type = content.get("event_type", "")
            payload = content.get("payload", {})
        else:
            payload = {}

        # Sanitize helper
        def sanitize(text: str) -> str:
            if not isinstance(text, str):
                text = str(text)
            text = text.replace("[", "\\[").replace("]", "\\]")
            import re
            text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
            try:
                text.encode('utf-8')
            except UnicodeEncodeError:
                text = text.encode('utf-8', errors='replace').decode('utf-8')
            return text

        with Vertical(classes="msg-tool-container"):
            # Header
            header_text = "🔍 Search"
            if event_type == "SEARCH.STARTED":
                header_text += " Started"
            elif event_type == "SEARCH.COMPLETED":
                header_text += " Completed"
            elif event_type == "SEARCH.FAILED":
                header_text += " Failed"

            yield Label(header_text, classes="msg-tool-label")
            yield Label("────────────────────────────", classes="msg-separator")

            if event_type == "SEARCH.STARTED":
                query = sanitize(payload.get("query", ""))
                backend = sanitize(payload.get("backend", ""))
                filters = payload.get("filters")
                req_id = sanitize(payload.get("request_id", ""))

                yield Label(f"Event: {event_type}", classes="msg-system", shrink=True)
                yield Label(f"Query: {query}", classes="msg-system", shrink=True)
                yield Label(f"Backend: {backend}", classes="msg-system", shrink=True)
                if filters:
                    import json
                    yield Label(f"Filters: {json.dumps(filters, ensure_ascii=False)}", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "SEARCH.COMPLETED":
                query = sanitize(payload.get("query", ""))
                backend = sanitize(payload.get("backend", ""))
                results = payload.get("results", [])
                result_count = payload.get("result_count", 0)
                req_id = sanitize(payload.get("request_id", ""))

                yield Label(f"Event: {event_type}", classes="msg-system", shrink=True)
                yield Label(f"Query: {query}", classes="msg-system", shrink=True)
                yield Label(f"Backend: {backend} • {result_count} results", classes="msg-system", shrink=True)
                yield Label("────────────────────────────", classes="msg-separator")

                # Defensive: ensure results is a list
                if not isinstance(results, list):
                    yield Label(f"Invalid results format: expected list, got {type(results).__name__}", classes="msg-error", shrink=True)
                    results = []

                for i, result in enumerate(results):
                    # Defensive: ensure each result is a dict
                    if not isinstance(result, dict):
                        yield Label(f"Invalid result item {i}: expected dict, got {type(result).__name__}", classes="msg-error", shrink=True)
                        continue
                    title = sanitize(result.get("title", f"Result {i+1}"))
                    url = sanitize(result.get("url", ""))
                    snippet = sanitize(result.get("snippet", ""))
                    source = sanitize(result.get("source", "web"))

                    with Vertical(classes="msg-search-result"):
                        yield Label(f"📄 {title}", classes="msg-search-title", shrink=True)
                        if url:
                            yield Label(f"🔗 {url}", classes="msg-search-url", shrink=True)
                        if snippet:
                            yield Label(f"💬 {snippet[:200]}{'...' if len(snippet) > 200 else ''}", classes="msg-search-snippet", shrink=True)
                        yield Label(f"Source: {source}", classes="msg-system", shrink=True)

                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "SEARCH.FAILED":
                query = sanitize(payload.get("query", ""))
                backend = sanitize(payload.get("backend", ""))
                error_code = sanitize(payload.get("error_code", "UNKNOWN_ERROR"))
                error_message = sanitize(payload.get("error_message", ""))
                req_id = sanitize(payload.get("request_id", ""))

                yield Label(f"Query: {query}", classes="msg-system", shrink=True)
                yield Label(f"Backend: {backend}", classes="msg-system", shrink=True)
                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"❌ Error: {error_code}", classes="msg-error", shrink=True)
                yield Label(f"Message: {error_message}", classes="msg-system", shrink=True)
                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            else:
                # Fallback for unknown search event
                yield Label(sanitize(str(payload)), classes="msg-system", shrink=True)


class RenderedFileEventMessage(RenderedMessage):
    """Structured rendering for FILE events (READ, WRITE, LIST)."""

    def compose(self) -> ComposeResult:
        content = self.message.content
        event_type = ""

        if isinstance(content, dict):
            event_type = content.get("event_type", "")
            payload = content.get("payload", {})
        else:
            payload = {}

        def sanitize(text: str) -> str:
            if not isinstance(text, str):
                text = str(text)
            text = text.replace("[", "\\[").replace("]", "\\]")
            import re
            text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
            try:
                text.encode('utf-8')
            except UnicodeEncodeError:
                text = text.encode('utf-8', errors='replace').decode('utf-8')
            return text

        def safe_path(path: str) -> str:
            """Extract filename or last few path components for display."""
            if not path:
                return "unknown"
            parts = path.replace("\\", "/").split("/")
            if len(parts) > 2:
                return f".../{'/'.join(parts[-2:])}"
            return path

        with Vertical(classes="msg-tool-container"):
            # Header
            header_text = "📁 File"
            action = ""
            if event_type == "FILE.READ_STARTED":
                action = "Reading"
            elif event_type == "FILE.READ_COMPLETED":
                action = "Read Complete"
            elif event_type == "FILE.WRITE_STARTED":
                action = "Writing"
            elif event_type == "FILE.WRITE_COMPLETED":
                action = "Write Complete"
            elif event_type == "FILE.LIST_STARTED":
                action = "Listing Directory"
            elif event_type == "FILE.LIST_COMPLETED":
                action = "Directory Listed"

            yield Label(f"{header_text} {action}", classes="msg-tool-label")
            yield Label("────────────────────────────", classes="msg-separator")

            path = sanitize(payload.get("path", ""))
            req_id = sanitize(payload.get("request_id", ""))

            yield Label(f"Path: {safe_path(path)}", classes="msg-system", shrink=True)
            yield Label(f"Full: {path}", classes="msg-system", shrink=True)

            if event_type == "FILE.READ_STARTED":
                offset = payload.get("offset", 0)
                limit = payload.get("limit")
                yield Label(f"Event: {event_type}", classes="msg-system", shrink=True)
                yield Label(f"Status: Read started", classes="msg-system", shrink=True)
                yield Label(f"Offset: {offset}", classes="msg-system", shrink=True)
                if limit:
                    yield Label(f"Limit: {limit} bytes", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "FILE.READ_COMPLETED":
                content_text = sanitize(payload.get("content", ""))
                size = payload.get("size", 0)
                encoding = sanitize(payload.get("encoding", "utf-8"))

                yield Label(f"Size: {size} bytes", classes="msg-system", shrink=True)
                yield Label(f"Encoding: {encoding}", classes="msg-system", shrink=True)
                yield Label("────────────────────────────", classes="msg-separator")
                # Preview first 500 chars
                preview = content_text[:500] + ("..." if len(content_text) > 500 else "")
                yield Label(preview, classes="msg-file-content", shrink=True, markup=False)
                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "FILE.WRITE_STARTED":
                content_length = payload.get("content_length", 0)
                mode = sanitize(payload.get("mode", "write"))

                yield Label(f"Content Length: {content_length} bytes", classes="msg-system", shrink=True)
                yield Label(f"Mode: {mode}", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "FILE.WRITE_COMPLETED":
                bytes_written = payload.get("bytes_written", 0)

                yield Label(f"Bytes Written: {bytes_written}", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "FILE.LIST_STARTED":
                recursive = payload.get("recursive", False)

                yield Label(f"Recursive: {recursive}", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            elif event_type == "FILE.LIST_COMPLETED":
                entries = payload.get("entries", [])
                entry_count = payload.get("entry_count", 0)

                yield Label(f"Entries: {entry_count}", classes="msg-system", shrink=True)
                yield Label("────────────────────────────", classes="msg-separator")

                for entry in entries:
                    name = sanitize(entry.get("name", ""))
                    entry_type = sanitize(entry.get("type", "file"))
                    size = entry.get("size", 0)

                    icon = "📁" if entry_type == "folder" else "📄"
                    if entry_type == "folder":
                        yield Label(f"{icon} {name}/", classes="msg-system", shrink=True)
                    else:
                        size_str = f"{size} B" if size < 1024 else f"{size/1024:.0f} KB"
                        yield Label(f"{icon} {name:<30} {size_str:>10}", classes="msg-system", shrink=True)

                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)

            else:
                yield Label(sanitize(str(payload)), classes="msg-system", shrink=True)


class RenderedAssistantEventMessage(RenderedMessage):
    """Structured rendering for ASSISTANT events (MESSAGE_STARTED, MESSAGE_COMPLETED, TOKEN, ERROR)."""

    def compose(self) -> ComposeResult:
        content = self.message.content
        event_type = ""

        if isinstance(content, dict):
            event_type = content.get("event_type", "")
            payload = content.get("payload", {})
        else:
            payload = {}

        def sanitize(text: str) -> str:
            if not isinstance(text, str):
                text = str(text)
            text = text.replace("[", "\\[").replace("]", "\\]")
            import re
            text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
            try:
                text.encode('utf-8')
            except UnicodeEncodeError:
                text = text.encode('utf-8', errors='replace').decode('utf-8')
            return text

        with Vertical(classes="msg-tool-container"):
            # Header
            header_text = "🤖 Assistant"
            if event_type == "ASSISTANT.MESSAGE_STARTED":
                header_text += " Started"
            elif event_type == "ASSISTANT.MESSAGE_COMPLETED":
                header_text += " Completed"
            elif event_type == "ASSISTANT.TOKEN":
                header_text += " Token"
            elif event_type == "ASSISTANT.ERROR":
                header_text += " Error"

            yield Label(header_text, classes="msg-tool-label")
            yield Label("────────────────────────────", classes="msg-separator")

            model_id = sanitize(payload.get("model_id", ""))
            provider_id = sanitize(payload.get("provider_id", ""))
            req_id = sanitize(payload.get("request_id", ""))
            trace_id = sanitize(payload.get("trace_id", ""))

            if model_id:
                yield Label(f"Model: {model_id}", classes="msg-system", shrink=True)
            if provider_id:
                yield Label(f"Provider: {provider_id}", classes="msg-system", shrink=True)

            if event_type == "ASSISTANT.MESSAGE_STARTED":
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)
                if trace_id:
                    yield Label(f"Trace ID: {trace_id}", classes="msg-system", shrink=True)

            elif event_type == "ASSISTANT.MESSAGE_COMPLETED":
                content_text = sanitize(payload.get("content", ""))
                finish_reason = sanitize(payload.get("finish_reason", ""))
                usage = payload.get("usage", {})

                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(content_text, classes="msg-assistant-content", shrink=True, markup=True)
                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"Finish Reason: {finish_reason}", classes="msg-system", shrink=True)
                if usage:
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)
                    total_tokens = usage.get("total_tokens", 0)
                    yield Label(f"Tokens: {prompt_tokens} prompt + {completion_tokens} completion = {total_tokens} total", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)
                if trace_id:
                    yield Label(f"Trace ID: {trace_id}", classes="msg-system", shrink=True)

            elif event_type == "ASSISTANT.TOKEN":
                token = sanitize(payload.get("token", ""))
                seq = payload.get("sequence_number", 0)

                yield Label(f"Token #{seq}: {token}", classes="msg-system", shrink=True)
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)
                if trace_id:
                    yield Label(f"Trace ID: {trace_id}", classes="msg-system", shrink=True)

            elif event_type == "ASSISTANT.ERROR":
                error_code = sanitize(payload.get("error_code", "UNKNOWN_ERROR"))
                error_message = sanitize(payload.get("error_message", ""))

                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"❌ Error: {error_code}", classes="msg-error", shrink=True)
                yield Label(f"Message: {error_message}", classes="msg-system", shrink=True)
                yield Label("────────────────────────────", classes="msg-separator")
                yield Label(f"Request ID: {req_id}", classes="msg-system", shrink=True)
                if trace_id:
                    yield Label(f"Trace ID: {trace_id}", classes="msg-system", shrink=True)

            else:
                yield Label(sanitize(str(payload)), classes="msg-system", shrink=True)


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
            # Check for structured protocol events (M5)
            content = message.content
            if isinstance(content, dict) and "event_type" in content:
                event_type = content.get("event_type", "")
                # Search events
                if event_type.startswith("SEARCH."):
                    return RenderedSearchResultsMessage(message)
                # File events
                elif event_type.startswith("FILE."):
                    return RenderedFileEventMessage(message)
                # Assistant events
                elif event_type.startswith("ASSISTANT."):
                    return RenderedAssistantEventMessage(message)
                # Resync/Cancellation events
                elif event_type in ("RESYNC", "CANCELLATION"):
                    return RenderedSystemMessage(message)
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
