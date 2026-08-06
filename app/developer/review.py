from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReviewEngine:
    findings: list[str]


class SecurityReviewer:
    def review(self, text: str) -> list[str]:
        return ["possible hardcoded secret"] if "password" in text.lower() else []


class PerformanceReviewer:
    def review(self, text: str) -> list[str]:
        return ["nested loop"] if "for " in text and "for " in text.split("for ", 1)[1] else []


class ArchitectureReviewer:
    def review(self, text: str) -> list[str]:
        return ["layer violation"] if "subprocess" in text else []


class MaintainabilityReviewer:
    def review(self, text: str) -> list[str]:
        return ["long function"] if len(text.splitlines()) > 200 else []


class DebtAnalyzer:
    def review(self, text: str) -> list[str]:
        return ["technical debt"] if "TODO" in text else []

