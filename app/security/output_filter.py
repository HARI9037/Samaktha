"""Output Security Filter for Samaktha Core.

Removes sensitive information, redacts secrets, and detects accidental leakage.
"""
import re

from app.security.security_metrics import SecurityMetricsCollector

# Keys whose values should be redacted directly, regardless of format
_SENSITIVE_KEYS = re.compile(
    r"(?i)^(api[_-]?key|password|secret|token|private[_-]?key|passwd|pwd)$"
)


class OutputSecurityFilter:
    """Deterministically filters and redacts output streams/text."""

    def __init__(self, metrics: SecurityMetricsCollector | None = None) -> None:
        self._metrics = metrics or SecurityMetricsCollector()
        # Matches inline key=value or key: value credential patterns
        self._credential_pattern = re.compile(
            r"(?i)(api[_-]?key|password|secret|token|private[_-]?key)(\s*[:=]\s*)(['\"]?[a-zA-Z0-9_\-]+['\"]?)"
        )

    def filter_text(self, text: str) -> str:
        """Redact sensitive information from text."""
        if not text:
            return text

        def _redact_match(match: re.Match) -> str:
            key = match.group(1)
            separator = match.group(2)
            self._metrics.record_filtered_output(redactions_count=1)
            return f"{key}{separator}[REDACTED]"

        return self._credential_pattern.sub(_redact_match, text)

    def filter_dict(self, data: dict) -> dict:
        """Recursively redact sensitive information from a dictionary."""
        result = {}
        for key, value in data.items():
            # If the key itself is a sensitive field name, redact the value directly
            if _SENSITIVE_KEYS.match(str(key)) and isinstance(value, str):
                self._metrics.record_filtered_output(redactions_count=1)
                result[key] = "[REDACTED]"
            elif isinstance(value, str):
                result[key] = self.filter_text(value)
            elif isinstance(value, dict):
                result[key] = self.filter_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.filter_text(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
