"""Phase 5.5 tests — Input Security Scanner.

Validates:
- Secret detection (API keys, passwords, etc)
- Malicious command detection
- Safe input passing
"""
from app.core.contracts.security import SecurityLevel
from app.security.input_scanner import InputSecurityScanner


def test_input_scanner_safe_input():
    scanner = InputSecurityScanner()
    decision = scanner.validate_request({"arg1": "hello world", "arg2": ["safe", "input"]})
    assert decision.allowed is True
    assert decision.security_level == SecurityLevel.LOW


def test_input_scanner_detects_credentials():
    scanner = InputSecurityScanner()
    decision = scanner.validate_request({"arg1": "api_key=my_super_secret_123"})
    assert decision.allowed is False
    assert decision.security_level == SecurityLevel.HIGH
    assert "Credential leakage" in decision.reason

    # Nested check
    decision2 = scanner.validate_request({"args": [{"token": "password: foo"}]})
    assert decision2.allowed is False


def test_input_scanner_detects_dangerous_commands():
    scanner = InputSecurityScanner()
    decision = scanner.validate_request({"cmd": "rm -rf /var/log"})
    assert decision.allowed is False
    assert decision.security_level == SecurityLevel.CRITICAL
    assert "Dangerous command" in decision.reason


def test_input_scanner_detects_path_traversal():
    scanner = InputSecurityScanner()
    decision = scanner.validate_request({"path": "../../etc/passwd"})
    assert decision.allowed is False
    assert decision.security_level == SecurityLevel.CRITICAL
    assert "Path traversal" in decision.reason
