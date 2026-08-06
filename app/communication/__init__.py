"""Phase 15 — Communication Hub.

Communication subsystem for Samaktha.
Provides email, messaging, notification, and future communication providers.
"""

from __future__ import annotations

from app.communication.models import (
    CommunicationProvider,
    CommunicationPriority,
    CommunicationRequest,
    CommunicationResult,
    CommunicationStatus,
    AttachmentMetadata,
    CommunicationDiagnostics,
    CommunicationHistoryEntry,
)
from app.communication.provider import (
    CommunicationProvider as CommunicationProviderABC,
    SMTPProvider,
    GmailProvider,
    OutlookProvider,
    WhatsAppProvider,
    TelegramProvider,
    DiscordProvider,
    SlackProvider,
    SMSProvider,
    WebhookProvider,
    PushProvider,
    DesktopProvider,
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