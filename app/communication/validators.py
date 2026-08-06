"""Phase 15 — Communication validators.

Validates communication requests before dispatch.
"""

from __future__ import annotations

import re
from typing import List

from app.communication.models import CommunicationRequest


def validate_recipient(recipient: str) -> list[str]:
    errors = []
    if not recipient or not recipient.strip():
        errors.append("Recipient is required")
    return errors


def validate_body(body: str, attachments: List[str]) -> List[str]:
    errors = []
    if not body.strip() and not attachments:
        errors.append("Body or attachments are required")
    return errors


def validate_subject(subject: str) -> list[str]:
    errors = []
    if len(subject) > 200:
        errors.append("Subject exceeds 200 characters")
    return errors


def validate_attachments(attachments: List[str]) -> List[str]:
    errors = []
    for attachment in attachments:
        if not attachment.strip():
            errors.append(f"Invalid attachment path: {attachment}")
    return errors


def validate_request(request: CommunicationRequest) -> list[str]:
    errors = []
    errors.extend(validate_recipient(request.recipient))
    errors.extend(validate_body(request.body, request.attachments))
    errors.extend(validate_subject(request.subject))
    errors.extend(validate_attachments(request.attachments))
    return errors