from __future__ import annotations

import re

from app.core.contracts.policy import PrivacyCategory, PrivacyClassification


class PrivacyClassifier:
    """Classifies request data for trust-aware routing decisions."""

    _critical_patterns = (
        r"\bpassword\b",
        r"\bapi[_ -]?key\b",
        r"\bsecret\b",
        r"\bprivate key\b",
        r"\bseed phrase\b",
        r"\btoken\b",
    )
    _sensitive_patterns = (
        r"\bssn\b",
        r"\bsocial security\b",
        r"\bcredit card\b",
        r"\bbank\b",
        r"\bmedical\b",
        r"\bhealth\b",
        r"\blegal\b",
    )
    _personal_patterns = (
        r"\bemail\b",
        r"\bphone\b",
        r"\baddress\b",
        r"\bcontact\b",
        r"\bcalendar\b",
        r"\boutlook\b",
        r"\bgmail\b",
    )
    _internal_patterns = (
        r"\binternal\b",
        r"\bconfidential\b",
        r"\bcompany\b",
        r"\bworkspace\b",
        r"\brepository\b",
    )

    def classify(self, value: object) -> PrivacyClassification:
        text = self._normalize(value)
        checks = (
            (PrivacyCategory.CRITICAL, self._critical_patterns),
            (PrivacyCategory.SENSITIVE, self._sensitive_patterns),
            (PrivacyCategory.PERSONAL, self._personal_patterns),
            (PrivacyCategory.INTERNAL, self._internal_patterns),
        )
        for category, patterns in checks:
            reasons = [
                f"Matched privacy signal: {pattern}"
                for pattern in patterns
                if re.search(pattern, text, flags=re.IGNORECASE)
            ]
            if reasons:
                return PrivacyClassification(category=category, reasons=reasons)
        return PrivacyClassification(category=PrivacyCategory.PUBLIC)

    @staticmethod
    def _normalize(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return " ".join(
                f"{key} {PrivacyClassifier._normalize(item)}"
                for key, item in value.items()
            )
        if isinstance(value, list):
            return " ".join(PrivacyClassifier._normalize(item) for item in value)
        return str(value)
