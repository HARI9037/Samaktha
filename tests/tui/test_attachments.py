"""Tests for Phase 6.8 — Rich Content & Attachments Layer."""

import pytest
from app.tui.attachments import Attachment, AttachmentStatus
from app.tui.models import ConversationMessage
from app.tui.renderer import (
    ConversationRenderer,
    AttachmentRenderer,
    RenderedAttachmentMessage
)


def test_attachment_model_defaults():
    att = Attachment(
        path="/tmp/test.pdf",
        filename="test.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size=1024
    )
    
    assert att.id is not None
    assert att.status == AttachmentStatus.UPLOADED
    assert att.preview_type == "unknown"


def test_conversation_message_supports_attachment():
    att = Attachment(
        path="foo", filename="foo.txt", extension=".txt", mime_type="text/plain", size=100
    )
    msg = ConversationMessage(role="attachment", attachment=att)
    assert msg.role == "attachment"
    assert msg.attachment is att


def test_attachment_renderer_creates_card():
    att = Attachment(
        path="foo", filename="foo.txt", extension=".txt", mime_type="text/plain", size=2048
    )
    widget = AttachmentRenderer.render(att)
    assert isinstance(widget, RenderedAttachmentMessage)
    
    # Verify the message it wraps
    assert widget.message.attachment == att


def test_conversation_renderer_routes_attachments():
    att = Attachment(
        path="foo", filename="foo.txt", extension=".txt", mime_type="text/plain", size=100
    )
    msg = ConversationMessage(role="attachment", attachment=att)
    widget = ConversationRenderer.render(msg)
    assert isinstance(widget, RenderedAttachmentMessage)


@pytest.mark.asyncio
async def test_rendered_attachment_message_content():
    from textual.app import App, ComposeResult
    from textual.widgets import Label
    
    att = Attachment(
        path="foo", filename="foo.txt", extension=".txt", mime_type="text/plain", size=2048, status=AttachmentStatus.QUEUED
    )
    msg = ConversationMessage(role="attachment", attachment=att)
    
    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield RenderedAttachmentMessage(msg)
            
    app = TestApp()
    async with app.run_test():
        widget = app.query_one(RenderedAttachmentMessage)
        assert widget.message.attachment.size == 2048
        
        # Verify UI renders labels
        labels = widget.query(Label)
        assert len(labels) == 2
        
        # Title label should contain filename
        assert "foo.txt" in str(labels[0].render())
        
        # Meta label should contain status
        assert "Queued" in str(labels[1].render())
