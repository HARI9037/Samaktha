"""Phase 15 — Communication attachment system.

Validates, hashes, and manages communication attachments.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Optional

from app.communication.models import AttachmentMetadata

log = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "application/json",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "video/mp4",
    "video/webm",
}

SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-.\s]+$")


def validate_attachment(filepath: str) -> list[str]:
    errors = []
    if not filepath or not filepath.strip():
        errors.append("Attachment path is empty")
        return errors

    if not os.path.exists(filepath):
        errors.append(f"Attachment file not found: {filepath}")
        return errors

    size = os.path.getsize(filepath)
    if size > MAX_ATTACHMENT_SIZE:
        errors.append(f"Attachment exceeds maximum size of {MAX_ATTACHMENT_SIZE} bytes")

    return errors


def detect_mime_type(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }
    return mime_map.get(ext, "application/octet-stream")


def compute_hash(filepath: str) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def safe_filename(filename: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_\-.\s]", "_", filename)
    return sanitized.strip()


def validate_attachment_metadata(filepath: str) -> AttachmentMetadata:
    errors = validate_attachment(filepath)
    mime_type = detect_mime_type(filepath)
    size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    sha256 = compute_hash(filepath) if os.path.exists(filepath) else ""
    safe_name = safe_filename(os.path.basename(filepath))

    return AttachmentMetadata(
        filename=os.path.basename(filepath),
        mime_type=mime_type,
        size_bytes=size,
        sha256=sha256,
        safe_filename=safe_name,
        duplicate=False,
    )


def check_duplicate(filepath: str, known_hashes: set[str]) -> bool:
    if not os.path.exists(filepath):
        return False
    file_hash = compute_hash(filepath)
    return file_hash in known_hashes