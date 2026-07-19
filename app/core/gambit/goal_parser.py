from __future__ import annotations

import re
from uuid import uuid4

from app.core.contracts.planning import Goal, GoalComplexity

HIGH_COMPLEXITY_SIGNALS = (
    "build",
    "create",
    "design",
    "architect",
    "implement",
    "develop",
    "refactor",
    "optimize",
    "debug",
    "analyze",
    "research",
    "plan",
    "workflow",
    "automation",
    "orchestrate",
    "integrate",
)
MEDIUM_COMPLEXITY_SIGNALS = (
    "summarize",
    "explain",
    "format",
    "extract",
    "organize",
    "outline",
    "draft",
    "write",
    "convert",
    "parse",
)
LONG_CONTEXT_SIGNALS = (
    "long document",
    "full file",
    "entire",
    "whole project",
    "codebase",
    "repository",
    "multiple files",
    "large",
)
LOCAL_MODEL_SIGNALS = (
    "private",
    "confidential",
    "local only",
    "offline",
    "do not send",
    "don't send",
    "sensitive",
    "secret",
    "credential",
    "password",
    "token",
    "key",
)
FAST_RESPONSE_SIGNALS = (
    "quick",
    "fast",
    "asap",
    "urgent",
    "immediately",
    "right now",
)
CODE_SIGNALS = (
    "code",
    "python",
    "javascript",
    "script",
    "function",
    "class",
    "api",
    "endpoint",
    "sql",
    "json",
    "yaml",
    "html",
    "css",
    "debug",
    "refactor",
)


class GoalParser:
    """Parses user requests into normalized goals for planning."""

    def parse(self, request: str) -> Goal:
        normalized = " ".join(request.split())
        complexity = self.estimate_complexity(normalized)
        requires_long_context = self._contains_any(normalized, LONG_CONTEXT_SIGNALS)
        requires_code = self._contains_any(normalized, CODE_SIGNALS)
        requires_local_model = self._contains_any(normalized, LOCAL_MODEL_SIGNALS)
        requires_fast_response = self._contains_any(normalized, FAST_RESPONSE_SIGNALS)

        return Goal(
            goal_id=f"goal-{uuid4()}",
            raw_request=request,
            summary=self._summarize(normalized),
            complexity=complexity,
            requires_long_context=requires_long_context,
            requires_code=requires_code,
            requires_local_model=requires_local_model,
            requires_fast_response=requires_fast_response,
            estimated_context_tokens=self.estimate_context_tokens(
                complexity=complexity,
                requires_long_context=requires_long_context,
                requires_code=requires_code,
            ),
            constraints=self._extract_constraints(normalized),
        )

    @staticmethod
    def estimate_complexity(request: str) -> GoalComplexity:
        lowered = request.lower()
        high_score = sum(1 for signal in HIGH_COMPLEXITY_SIGNALS if signal in lowered)
        medium_score = sum(1 for signal in MEDIUM_COMPLEXITY_SIGNALS if signal in lowered)
        if high_score >= 2:
            return GoalComplexity.HIGH
        if high_score >= 1 or medium_score >= 2:
            return GoalComplexity.MEDIUM
        return GoalComplexity.LOW

    @staticmethod
    def estimate_context_tokens(
        complexity: GoalComplexity,
        requires_long_context: bool,
        requires_code: bool,
    ) -> int:
        estimate = 2000
        if requires_long_context:
            estimate = 20000
        if requires_code:
            estimate += 5000
        if complexity == GoalComplexity.HIGH:
            estimate += 10000
        return estimate

    @staticmethod
    def _contains_any(request: str, signals: tuple[str, ...]) -> bool:
        lowered = request.lower()
        return any(signal in lowered for signal in signals)

    @staticmethod
    def _summarize(request: str) -> str:
        return request[:240].strip()

    @staticmethod
    def _extract_constraints(request: str) -> list[str]:
        constraints = []
        for pattern in (r"\bdo not\b[^.]+", r"\bmust\b[^.]+", r"\bonly\b[^.]+"):
            constraints.extend(match.group(0).strip() for match in re.finditer(pattern, request, flags=re.IGNORECASE))
        return constraints[:8]
