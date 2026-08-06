"""Input Security Scanner for Samaktha Core.

Detects dangerous patterns, sensitive information, and classifies risk level
deterministically without ML models.
"""
import re

from app.core.contracts.security import SecurityDecision, SecurityLevel


class InputSecurityScanner:
    """Deterministically scans inputs for security risks."""

    def __init__(self) -> None:
        self._credential_pattern = re.compile(
            r"(?i)(api[_-]?key|password|secret|token|private[_-]?key)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]+['\"]?"
        )
        self._path_traversal_pattern = re.compile(r"\.\./|\.\.\\")
        self._dangerous_commands = ["rm -rf", "mkfs", "dd if=", "> /dev/sda"]

    def scan_text(self, text: str) -> SecurityDecision:
        """Scan text and return a security decision."""
        if not text:
            return SecurityDecision(allowed=True, security_level=SecurityLevel.LOW)

        # Check for path traversal
        if self._path_traversal_pattern.search(text):
            return SecurityDecision(
                allowed=False,
                reason="Path traversal attempt detected",
                policy_id="policy_path_traversal",
                security_level=SecurityLevel.CRITICAL,
            )

        # Check for dangerous commands
        for cmd in self._dangerous_commands:
            if cmd in text:
                return SecurityDecision(
                    allowed=False,
                    reason=f"Dangerous command detected: {cmd}",
                    policy_id="policy_dangerous_command",
                    security_level=SecurityLevel.CRITICAL,
                )

        # Check for credentials
        if self._credential_pattern.search(text):
            return SecurityDecision(
                allowed=False,
                reason="Credential leakage detected in input",
                policy_id="policy_credential_leak",
                security_level=SecurityLevel.HIGH,
            )

        return SecurityDecision(allowed=True, security_level=SecurityLevel.LOW)

    _SENSITIVE_KEYS = re.compile(
        r"(?i)^(api[_-]?key|password|secret|token|private[_-]?key|passwd|pwd)$"
    )

    def validate_request(self, request_data: dict) -> SecurityDecision:
        """Scan a dictionary (e.g. tool arguments) for risks."""
        for key, value in request_data.items():
            # If the dict key itself is a sensitive name, flag the value
            if self._SENSITIVE_KEYS.match(str(key)) and isinstance(value, str) and value:
                return SecurityDecision(
                    allowed=False,
                    reason="Credential leakage detected in input",
                    policy_id="policy_credential_leak",
                    security_level=SecurityLevel.HIGH,
                )
            if isinstance(value, str):
                decision = self.scan_text(value)
                if not decision.allowed:
                    return decision
            elif isinstance(value, dict):
                decision = self.validate_request(value)
                if not decision.allowed:
                    return decision
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        decision = self.scan_text(item)
                        if not decision.allowed:
                            return decision
                    elif isinstance(item, dict):
                        decision = self.validate_request(item)
                        if not decision.allowed:
                            return decision
        return SecurityDecision(allowed=True, security_level=SecurityLevel.LOW)
