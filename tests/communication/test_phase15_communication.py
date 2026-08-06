"""Phase 15 — Communication Hub tests.

Covers communication models, registry, dispatcher, email tool,
message tool, notification tool, attachments, history, diagnostics,
architecture boundaries, and governance verification.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.communication.models import (
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
    CommunicationProvider,
    CommunicationPriority,
    CommunicationHistoryEntry,
    AttachmentMetadata,
)
from app.communication.registry import CommunicationRegistry
from app.communication.manager import CommunicationManager
from app.communication.dispatcher import CommunicationDispatcher
from app.communication.formatter import CommunicationFormatter
from app.communication.validators import validate_request
from app.communication.policy import (
    get_required_permissions,
    get_risk_level,
    requires_approval,
)
from app.communication.attachments import (
    validate_attachment,
    detect_mime_type,
    compute_hash,
    safe_filename,
    validate_attachment_metadata,
)
from app.communication.history import CommunicationHistory
from app.communication.delivery import DeliveryTracker, DeliveryService
from app.communication.conversation import ConversationHistory, ConversationManager
from app.communication.diagnostics import run_diagnostics
from app.communication.email_tool import EmailTool
from app.communication.message_tool import MessageTool
from app.communication.notification_tool import NotificationTool


# ---------------------------------------------------------------------------
# Communication Models
# ---------------------------------------------------------------------------


class TestCommunicationModels:
    def test_communication_request_creation(self):
        request = CommunicationRequest(
            sender="user1",
            recipient="user2",
            provider=CommunicationProvider.SMTP,
            subject="Test",
            body="Hello",
        )
        assert request.sender == "user1"
        assert request.recipient == "user2"
        assert request.provider == CommunicationProvider.SMTP

    def test_communication_result_creation(self):
        result = CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProvider.DESKTOP,
            message_id="msg-123",
        )
        assert result.status == CommunicationStatus.SENT
        assert result.provider == CommunicationProvider.DESKTOP
        assert result.message_id == "msg-123"

    def test_communication_history_entry(self):
        from datetime import datetime, timezone
        entry = CommunicationHistoryEntry(
            recipient="user2",
            provider=CommunicationProvider.SMTP,
            status=CommunicationStatus.SENT,
            subject="Test",
        )
        assert entry.recipient == "user2"
        assert entry.provider == CommunicationProvider.SMTP

    def test_attachment_metadata(self):
        meta = AttachmentMetadata(
            filename="test.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )
        assert meta.filename == "test.pdf"
        assert meta.mime_type == "application/pdf"


# ---------------------------------------------------------------------------
# Communication Registry
# ---------------------------------------------------------------------------


class TestCommunicationRegistry:
    def test_registry_has_defaults(self):
        registry = CommunicationRegistry()
        providers = registry.list_providers()
        assert "smtp" in providers
        assert "gmail" in providers
        assert "desktop" in providers

    def test_registry_register(self):
        registry = CommunicationRegistry()
        registry.register("custom", MagicMock())
        assert registry.has_provider("custom")

    def test_registry_unregister(self):
        registry = CommunicationRegistry()
        assert registry.unregister("smtp") is True
        assert not registry.has_provider("smtp")

    def test_registry_count(self):
        registry = CommunicationRegistry()
        assert registry.count() > 0

    def test_registry_health_check(self):
        registry = CommunicationRegistry()
        health = registry.health_check()
        assert isinstance(health, dict)


# ---------------------------------------------------------------------------
# Communication Manager
# ---------------------------------------------------------------------------


class TestCommunicationManager:
    def test_manager_send_without_provider(self):
        registry = CommunicationRegistry()
        manager = CommunicationManager(registry)

        async def test():
            request = CommunicationRequest(
                sender="user1",
                recipient="user2",
                provider=CommunicationProvider.SMTP,
            )
            result = await manager.send(request)
            return result

        result = asyncio.run(test())
        assert result.status == CommunicationStatus.FAILED

    def test_manager_list_providers(self):
        registry = CommunicationRegistry()
        manager = CommunicationManager(registry)
        providers = manager.list_providers()
        assert len(providers) > 0


# ---------------------------------------------------------------------------
# Communication Dispatcher
# ---------------------------------------------------------------------------


class TestCommunicationDispatcher:
    def test_dispatcher_providers(self):
        registry = CommunicationRegistry()
        manager = CommunicationManager(registry)
        dispatcher = CommunicationDispatcher(manager)
        providers = dispatcher.get_providers()
        assert len(providers) > 0


# ---------------------------------------------------------------------------
# Communication Formatter
# ---------------------------------------------------------------------------


class TestCommunicationFormatter:
    def test_format_request(self):
        request = CommunicationRequest(
            sender="user1",
            recipient="user2",
            provider=CommunicationProvider.SMTP,
            subject="Test Subject",
            body="Test body",
        )
        formatter = CommunicationFormatter()
        formatted = formatter.format_request(request)
        assert formatted["sender"] == "user1"
        assert formatted["recipient"] == "user2"
        assert formatted["subject"] == "Test Subject"

    def test_format_result(self):
        result = CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProvider.DESKTOP,
            message_id="msg-123",
        )
        formatter = CommunicationFormatter()
        formatted = formatter.format_result(result)
        assert formatted["status"] == "sent"
        assert formatted["message_id"] == "msg-123"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


class TestValidators:
    def test_validate_request_empty(self):
        request = CommunicationRequest(
            sender="user1",
            recipient="",
            provider=CommunicationProvider.SMTP,
        )
        errors = validate_request(request)
        assert len(errors) > 0

    def test_validate_request_valid(self):
        request = CommunicationRequest(
            sender="user1",
            recipient="user2@example.com",
            provider=CommunicationProvider.SMTP,
            body="Hello",
        )
        errors = validate_request(request)
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class TestPolicy:
    def test_desktop_no_approval(self):
        assert requires_approval(CommunicationProvider.DESKTOP) is False

    def test_smtp_requires_approval(self):
        assert requires_approval(CommunicationProvider.SMTP) is True

    def test_gmail_requires_approval(self):
        assert requires_approval(CommunicationProvider.GMAIL) is True

    def test_get_risk_level(self):
        assert get_risk_level(CommunicationProvider.DESKTOP) == "LOW"
        assert get_risk_level(CommunicationProvider.SMTP) == "HIGH"

    def test_get_required_permissions(self):
        perms = get_required_permissions(CommunicationProvider.SMTP)
        assert "network" in perms
        assert "email" in perms


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


class TestAttachments:
    def test_safe_filename(self):
        assert safe_filename("test file.pdf") == "test file.pdf"

    def test_detect_mime_type(self):
        assert detect_mime_type("test.pdf") == "application/pdf"
        assert detect_mime_type("test.jpg") == "image/jpeg"
        assert detect_mime_type("test.txt") == "text/plain"

    def test_validate_attachment_metadata(self):
        meta = validate_attachment_metadata("README.md")
        assert meta.filename == "README.md"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestCommunicationHistory:
    def test_history_add_and_get(self):
        history = CommunicationHistory()
        from app.communication.models import CommunicationHistoryEntry
        entry = CommunicationHistoryEntry(
            recipient="user2",
            provider=CommunicationProvider.SMTP,
            status=CommunicationStatus.SENT,
            subject="Test",
        )
        history.add_entry(entry)
        assert history.count() == 1
        assert len(history.get_entries()) == 1

    def test_history_search(self):
        history = CommunicationHistory()
        entry = CommunicationHistoryEntry(
            recipient="user2",
            provider=CommunicationProvider.SMTP,
            status=CommunicationStatus.SENT,
            subject="Test search",
        )
        history.add_entry(entry)
        results = history.search("search")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class TestDeliveryTracker:
    def test_tracker_track(self):
        tracker = DeliveryTracker()
        result = CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProvider.DESKTOP,
            message_id="msg-123",
        )
        tracker.track(result)
        assert tracker.count() == 1

    def test_tracker_get_status(self):
        tracker = DeliveryTracker()
        result = CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProvider.DESKTOP,
            message_id="msg-123",
        )
        tracker.track(result)
        status = tracker.get_status("msg-123")
        assert status is not None
        assert status.status == CommunicationStatus.SENT


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class TestConversationManager:
    def test_conversation_add_and_get(self):
        manager = ConversationManager()
        result = CommunicationResult(
            status=CommunicationStatus.SENT,
            provider=CommunicationProvider.DESKTOP,
            message_id="msg-123",
        )
        manager.add_message("user2", result)
        history = manager.get_history("user2")
        assert len(history) == 1


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_run_diagnostics(self):
        registry = CommunicationRegistry()
        diagnostics = run_diagnostics(registry)
        assert len(diagnostics.registered_providers) > 0
        assert isinstance(diagnostics.provider_health, dict)


# ---------------------------------------------------------------------------
# Email Tool
# ---------------------------------------------------------------------------


class TestEmailTool:
    def test_email_tool_name(self):
        tool = EmailTool()
        assert tool.name == "email"

    def test_email_tool_approval_required(self):
        tool = EmailTool()
        assert tool.approval_required is True

    def test_email_tool_send_action(self):
        tool = EmailTool()
        result = asyncio.run(tool.run({"action": "send", "recipient": "user@example.com", "subject": "Test", "body": "Hello"}))
        assert result.ok is True

    def test_email_tool_search_action(self):
        tool = EmailTool()
        asyncio.run(tool.run({"action": "send", "recipient": "user@example.com", "subject": "Test", "body": "Hello"}))
        result = asyncio.run(tool.run({"action": "search", "query": "Test"}))
        assert result.ok is True
        assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# Message Tool
# ---------------------------------------------------------------------------


class TestMessageTool:
    def test_message_tool_name(self):
        tool = MessageTool()
        assert tool.name == "message"

    def test_message_tool_approval_required(self):
        tool = MessageTool()
        assert tool.approval_required is True

    def test_message_tool_send_action(self):
        tool = MessageTool()
        result = asyncio.run(tool.run({"action": "send", "recipient": "user", "body": "Hello"}))
        assert result.ok is True


# ---------------------------------------------------------------------------
# Notification Tool
# ---------------------------------------------------------------------------


class TestNotificationTool:
    def test_notification_tool_name(self):
        tool = NotificationTool()
        assert tool.name == "notification"

    def test_notification_tool_approval_required(self):
        tool = NotificationTool()
        assert tool.approval_required is False

    def test_notification_tool_send_action(self):
        tool = NotificationTool()
        result = asyncio.run(tool.run({"action": "send", "recipient": "user", "body": "Hello"}))
        assert result.ok is True


# ---------------------------------------------------------------------------
# Architecture Boundaries
# ---------------------------------------------------------------------------


def test_communication_no_provider_imports():
    """Communication subsystem must not import provider internals."""
    import inspect
    from app.communication import models

    source = inspect.getsource(models)
    assert "from app.providers" not in source
    assert "from app.runtime" not in source
    assert "from app.personality" not in source
    assert "from app.voice" not in source
    assert "from app.memory" not in source
    assert "from app.internet" not in source


def test_communication_no_cap_bypass():
    """Communication tools must require CAP approval for outbound actions."""
    email_tool = EmailTool()
    assert email_tool.approval_required is True

    message_tool = MessageTool()
    assert message_tool.approval_required is True


def test_communication_no_runtime_bypass():
    """Communication must execute only through Runtime."""
    import inspect
    from app.communication import email_tool

    source = inspect.getsource(email_tool)
    assert "from app.runtime" not in source


def test_communication_no_circular_imports():
    """Communication must not create circular imports."""
    import app.communication.models
    import app.communication.provider
    import app.communication.registry
    import app.communication.manager
    import app.communication.dispatcher
    import app.communication.formatter
    import app.communication.validators
    import app.communication.policy
    import app.communication.attachments
    import app.communication.history
    import app.communication.delivery
    import app.communication.conversation
    import app.communication.diagnostics
    import app.communication.email_tool
    import app.communication.message_tool
    import app.communication.notification_tool