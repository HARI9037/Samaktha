"""P8.4 — Evidence sanitization and redaction.

Centralized sanitization to ensure evidence never persists secrets,
raw content, or sensitive data. Defaults to metadata-only evidence.
"""

from __future__ import annotations

import re
from typing import Any
from copy import deepcopy

# Keys that indicate secret-bearing values (case-insensitive)
_SECRET_KEY_PATTERNS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "credential",
    "token",
    "cookie",
    "session_id",
    "bearer",
    "x-api-key",
    "x-subscription-token",
    "x-brave-api-key",
    "x-goog-api-key",
    "jwt",
    "hmac",
    "signing_key",
    "private_key",
    "client_secret",
    "client_id",
)

# Keys that indicate content that should not be persisted by default
_CONTENT_KEY_PATTERNS = (
    "prompt",
    "response",
    "content",
    "body",
    "message",
    "text",
    "output",
    "input",
    "stdout",
    "stderr",
    "clipboard",
    "file_content",
    "memory_content",
    "web_body",
    "html",
    "markdown",
)

# Known structured fields that are safe to persist (allowlist)
_SAFE_METADATA_KEYS = frozenset({
    "execution_id",
    "sequence_number",
    "request_id",
    "trace_id",
    "session_id",
    "principal_id",
    "task_id",
    "action_id",
    "permit_id",
    "approval_id",
    "operation_digest",
    "retry_attempt",
    "provider",
    "model",
    "tool_name",
    "tool_action",
    "status",
    "failure_type",
    "decision",
    "reason_code",
    "duration_ms",
    "input_chars",
    "output_chars",
    "input_bytes",
    "output_bytes",
    "content_type",
    "mime_type",
    "target_category",
    "sanitized_target",
    "result_status",
    "event_type",
    "severity",
    "schema_version",
    "event_version",
    "source",
    "streaming",
    "generation",
    "completed_tasks",
    "failed_tasks",
    "total_steps",
    "retry_count",
    "approval_count",
    "security_denial_count",
    "recovery_count",
})


def _is_secret_key(key: str) -> bool:
    """Check if a key name indicates a secret value."""
    lowered = key.lower()
    return any(pattern in lowered for pattern in _SECRET_KEY_PATTERNS)


def _is_content_key(key: str) -> bool:
    """Check if a key name indicates raw content that shouldn't be persisted."""
    lowered = key.lower()
    return any(pattern in lowered for pattern in _CONTENT_KEY_PATTERNS)


def _is_safe_key(key: str) -> bool:
    """Check if a key is explicitly safe to persist."""
    return key in _SAFE_METADATA_KEYS


def _redact_value(value: Any, max_len: int = 8) -> str:
    """Create a redacted representation of a value."""
    if isinstance(value, str):
        if len(value) <= max_len:
            return "***"
        return value[:max_len] + "***"
    return "***"


_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|"
    r"password|secret|credential|cookie|bearer)\b(\s*[:=]\s*|\s+)([^\s,;&]+)"
)


def _sanitize_string(value: str) -> str:
    """Redact common inline credential forms in otherwise safe fields."""
    return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def _sanitize_recursive(obj: Any, depth: int = 0, max_depth: int = 10) -> Any:
    """Recursively sanitize a data structure."""
    if depth > max_depth:
        return "[max_depth_exceeded]"

    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if _is_secret_key(key):
                result[key] = _redact_value(value)
            elif _is_content_key(key):
                # Replace content with metadata
                if isinstance(value, str):
                    result[key] = f"[content:{len(value)} chars]"
                elif isinstance(value, (bytes, bytearray)):
                    result[key] = f"[content:{len(value)} bytes]"
                elif isinstance(value, (list, dict)):
                    result[key] = f"[content:{type(value).__name__}]"
                else:
                    result[key] = "[content]"
            elif _is_safe_key(key):
                # Safe key - sanitize the value recursively
                result[key] = _sanitize_recursive(value, depth + 1, max_depth)
            else:
                # Unknown key - be conservative, sanitize if it looks like content
                if isinstance(value, str) and len(value) > 500:
                    result[key] = f"[truncated:{len(value)} chars]"
                else:
                    result[key] = _sanitize_recursive(value, depth + 1, max_depth)
        return result

    elif isinstance(obj, list):
        # Limit list size to prevent unbounded growth
        if len(obj) > 100:
            return [_sanitize_recursive(item, depth + 1, max_depth) for item in obj[:100]] + ["[list_truncated]"]
        return [_sanitize_recursive(item, depth + 1, max_depth) for item in obj]

    elif isinstance(obj, str):
        obj = _sanitize_string(obj)
        # Long strings might be content - truncate if very long
        if len(obj) > 10000:
            return f"[truncated:{len(obj)} chars]"
        return obj

    elif isinstance(obj, (bytes, bytearray)):
        if len(obj) > 10000:
            return f"[binary:{len(obj)} bytes]"
        return f"[binary:{len(obj)} bytes]"

    return obj


def sanitize_for_evidence(
    metadata: dict[str, Any],
    *,
    allow_content: bool = False,
    max_payload_bytes: int = 64_000,
) -> dict[str, Any]:
    """Sanitize metadata for durable evidence storage.

    Args:
        metadata: Raw metadata dictionary to sanitize
        allow_content: If True, allows content keys (prompts, responses) to pass through.
                       Default False for production safety.
        max_payload_bytes: Maximum size of sanitized output. Truncates if exceeded.

    Returns:
        Sanitized metadata safe for evidence persistence.
    """
    if not isinstance(metadata, dict):
        return {"_sanitized_type": type(metadata).__name__}

    # Deep copy to avoid mutating original
    sanitized = _sanitize_recursive(deepcopy(metadata))

    # Add safe metadata hints
    sanitized["_sanitized"] = True
    sanitized["_content_allowed"] = allow_content

    # Estimate size and truncate if needed
    import json
    try:
        payload = json.dumps(sanitized, ensure_ascii=False)
        if len(payload.encode("utf-8")) > max_payload_bytes:
            # Truncate non-safe fields
            safe_fields = {k: v for k, v in sanitized.items() if _is_safe_key(k) or k.startswith("_")}
            # Add back non-safe fields one by one until limit
            for k, v in sanitized.items():
                if k in safe_fields:
                    continue
                test = {**safe_fields, k: v}
                if len(json.dumps(test, ensure_ascii=False).encode("utf-8")) <= max_payload_bytes:
                    safe_fields[k] = v
                else:
                    safe_fields[k] = "[omitted:size_limit]"
            return safe_fields
    except (TypeError, ValueError):
        pass

    return sanitized


def sanitize_exception(exc: BaseException) -> dict[str, Any]:
    """Sanitize an exception for evidence storage."""
    return {
        "type": type(exc).__name__,
        "module": type(exc).__module__,
        "message": _sanitize_string(str(exc))[:500],
        "_sanitized": True,
    }


def sanitize_url(url: str) -> str:
    """Sanitize URL by removing credentials and query parameters that might contain secrets."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        # Remove userinfo (credentials)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        # Remove query and fragment
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
    except Exception:
        return "[invalid_url]"


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Sanitize HTTP headers by redacting secret-bearing headers."""
    sanitized = {}
    for key, value in headers.items():
        if _is_secret_key(key):
            sanitized[key] = _redact_value(value)
        else:
            sanitized[key] = value
    return sanitized


def sanitize_environment(env: dict[str, str]) -> dict[str, str]:
    """Sanitize environment variables by removing secret-bearing ones."""
    return {
        k: v if not _is_secret_key(k) else _redact_value(v)
        for k, v in env.items()
    }
