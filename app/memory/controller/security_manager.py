"""Phase 8 — Security Manager.

Provides integrity hashing, CAP access verification hooks, and security
metadata for the Memory Controller.

All operations remain local. No internet communication.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.contracts.security import SecurityDecision, SecurityLevel
from app.core.contracts.memory import MemoryAccessContext, MemoryScope


class SecurityManager:
    """Manages memory security: integrity, access control, encryption hooks."""

    def __init__(self) -> None:
        self._access_rules: dict[str, SecurityLevel] = {}

    # ------------------------------------------------------------------
    # Integrity hashes
    # ------------------------------------------------------------------

    @staticmethod
    def compute_integrity_hash(content: str, metadata: dict[str, Any]) -> str:
        """Full SHA-256 hash for integrity verification."""
        hasher = hashlib.sha256()
        hasher.update(content.encode("utf-8"))
        hasher.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def verify_integrity(
        content: str, metadata: dict[str, Any], expected_hash: str
    ) -> bool:
        """Verify content+metadata against a stored hash."""
        return SecurityManager.compute_integrity_hash(content, metadata) == expected_hash

    # ------------------------------------------------------------------
    # CAP integration — access verification
    # ------------------------------------------------------------------

    def register_access_rule(
        self, memory_type: str, required_level: SecurityLevel
    ) -> None:
        """Register a minimum security level required to access a memory type."""
        self._access_rules[memory_type] = required_level

    def check_read_access(
        self,
        memory_type: str,
        memory_security_level: SecurityLevel,
        user_security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> SecurityDecision:
        """Check whether a user/component can read a given memory.

        CAP calls this before returning memory items.  The caller (CAP)
        provides the user_security_level.
        """
        required = self._access_rules.get(memory_type, SecurityLevel.LOW)

        level_rank = {
            SecurityLevel.LOW: 0,
            SecurityLevel.MEDIUM: 1,
            SecurityLevel.HIGH: 2,
            SecurityLevel.CRITICAL: 3,
        }

        if level_rank.get(user_security_level, 0) < level_rank.get(required, 0):
            return SecurityDecision(
                allowed=False,
                reason=f"Security level too low: need {required.value}, got {user_security_level.value}",
                security_level=required,
            )

        if level_rank.get(user_security_level, 0) < level_rank.get(memory_security_level, 0):
            return SecurityDecision(
                allowed=False,
                reason=f"Memory security level {memory_security_level.value} exceeds user clearance {user_security_level.value}",
                security_level=memory_security_level,
            )

        return SecurityDecision(allowed=True, security_level=user_security_level)

    def check_write_access(
        self,
        memory_type: str,
        user_security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> SecurityDecision:
        """Check whether a component can write a given memory type."""
        required = self._access_rules.get(memory_type, SecurityLevel.LOW)

        level_rank = {
            SecurityLevel.LOW: 0,
            SecurityLevel.MEDIUM: 1,
            SecurityLevel.HIGH: 2,
            SecurityLevel.CRITICAL: 3,
        }

        if level_rank.get(user_security_level, 0) < level_rank.get(required, 0):
            return SecurityDecision(
                allowed=False,
                reason=f"Write access denied: need {required.value}, got {user_security_level.value}",
                security_level=required,
            )

        return SecurityDecision(allowed=True, security_level=user_security_level)

    @staticmethod
    def is_in_scope(item: Any, access_context: MemoryAccessContext) -> bool:
        """Apply ownership/scope eligibility before security or ranking."""

        try:
            scope = MemoryScope(getattr(item, "scope", None))
        except (TypeError, ValueError):
            return False
        owner_id = str(getattr(item, "owner_id", "") or "")
        if scope is MemoryScope.SYSTEM:
            return False
        if owner_id != access_context.principal_id:
            return False
        if scope is MemoryScope.SESSION:
            return bool(
                access_context.session_id
                and getattr(item, "session_id", None) == access_context.session_id
            )
        if scope is MemoryScope.WORKSPACE:
            return bool(
                access_context.workspace_id
                and getattr(item, "workspace_id", None) == access_context.workspace_id
            )
        return scope is MemoryScope.USER

    def can_read_item(
        self,
        item: Any,
        access_context: MemoryAccessContext,
    ) -> SecurityDecision:
        """Authorize an already scope-eligible item under caller clearance."""

        if not self.is_in_scope(item, access_context):
            return SecurityDecision(allowed=False, reason="memory is outside access scope")
        metadata = getattr(item, "metadata", {}) or {}
        memory_type = str(metadata.get("memory_type") or "context")
        level = getattr(item, "privacy_level", SecurityLevel.LOW)
        if not isinstance(level, SecurityLevel):
            try:
                level = SecurityLevel(level)
            except ValueError:
                level = SecurityLevel.CRITICAL
        return self.check_read_access(
            memory_type,
            level,
            access_context.security_level,
        )

    # ------------------------------------------------------------------
    # Encryption hooks (future)
    # ------------------------------------------------------------------

    @staticmethod
    def encrypt_payload(payload: str) -> str:
        """Placeholder for future encryption.

        Currently returns the payload unchanged (no-op).
        Phase 9+ can implement actual encryption here.
        """
        return payload

    @staticmethod
    def decrypt_payload(payload: str) -> str:
        """Placeholder for future decryption."""
        return payload
