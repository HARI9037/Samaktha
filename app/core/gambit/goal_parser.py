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


import logging

from app.core.contracts.planning import Goal, GoalComplexity, GoalIntent

log = logging.getLogger(__name__)


class GoalParser:
    """Parses user requests into normalized goals for planning."""

    def parse(self, request: str) -> Goal:
        normalized = " ".join(request.split())
        complexity = self.estimate_complexity(normalized)
        intent, target_path, query = self.detect_intent(normalized)
        log.info("GoalParser: detect_intent returned intent=%s target_path=%s", intent, target_path)
        requires_long_context = self._contains_any(normalized, LONG_CONTEXT_SIGNALS) or intent == GoalIntent.READ_RESOURCE
        requires_code = self._contains_any(normalized, CODE_SIGNALS) or intent == GoalIntent.GENERATE_CODE
        requires_local_model = self._contains_any(normalized, LOCAL_MODEL_SIGNALS)
        requires_fast_response = self._contains_any(normalized, FAST_RESPONSE_SIGNALS)

        log.debug("GoalParser.parse() -> intent: %s, target_path: %s", intent, target_path)
        log.info("GoalParser: intent=%s target_path=%s", intent, target_path)

        return Goal(
            goal_id=f"goal-{uuid4()}",
            raw_request=request,
            summary=self._summarize(normalized),
            complexity=complexity,
            intent=intent,
            target_path=target_path,
            query=query,
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
    def detect_intent(request: str) -> tuple[GoalIntent, str | None, str | None]:
        lowered = request.lower()
        
        # 1. Path extraction helper
        quoted_path_match = re.search(
            r"['\"]([a-zA-Z]:[\\/][^'\"]+|/?[^'\"]+\.[a-zA-Z0-9]+)['\"]",
            request,
        )
        path_match = quoted_path_match or re.search(r"([a-zA-Z]:[\\/][^\s'\"]+|/?[^\s'\"]+\.[a-zA-Z0-9]+)", request)
        extracted_path = path_match.group(1) if path_match else None
        
        # Fallback extract path for things without dots like "LYRA"
        if not extracted_path:
            # Look for words after common verbs or prepositions
            match = re.search(r"(?:read|open|summarize|show|browse|inside|delete|move|copy|rename|find|search|locate)\s+([a-zA-Z0-9_.-]+)", request, re.IGNORECASE)
            if match and match.group(1).lower() not in ("desktop", "the", "a", "file", "folder", "directory", "files"):
                extracted_path = match.group(1)

        # 2. Search Resource Intent
        search_keywords = ("search", "find", "locate")
        if any(lowered.startswith(f"{kw} ") for kw in search_keywords) or any(f" {kw} " in lowered for kw in search_keywords):
            # Exclude "search memory" which is SEARCH_MEMORY
            if not any(k in lowered for k in ("memory", "conversation", "yesterday", "recollection")):
                return GoalIntent.SEARCH_RESOURCE, extracted_path, None

        # 3. File / Resource Read Intent
        read_keywords = ("read", "open", "cat", "show", "examine", "inspect", "summarize")
        if (extracted_path and any(kw in lowered for kw in read_keywords)) or lowered.startswith(read_keywords):
            return GoalIntent.READ_RESOURCE, extracted_path, None

        # 4. Directory Listing Intent
        list_keywords = (
            "list", "ls", "dir", "browse", "what is inside", "what's inside", "contents of", "show files", "desktop contents"
        )
        if any(kw in lowered for kw in list_keywords) or (extracted_path and any(k in lowered for k in ("folder", "directory", "desktop"))):
            target = extracted_path
            if not target:
                if "desktop" in lowered:
                    import os
                    target = os.path.expanduser("~/Desktop")
                else:
                    target = "."
            elif target.lower() == "desktop":
                import os
                target = os.path.expanduser("~/Desktop")
            return GoalIntent.LIST_DIRECTORY, target, None

        # 5. Write, Delete, Move, Copy, Rename Resource
        if "delete" in lowered or "remove" in lowered or "rm " in lowered:
            return GoalIntent.DELETE_RESOURCE, extracted_path, None
        if "move" in lowered:
            return GoalIntent.MOVE_RESOURCE, extracted_path, None
        if "copy" in lowered:
            return GoalIntent.COPY_RESOURCE, extracted_path, None
        if "rename" in lowered:
            return GoalIntent.RENAME_RESOURCE, extracted_path, None

        # 6. Email, Calendar, and Media Intents (which map to capabilities)
        if "email" in lowered:
            return GoalIntent.SEND_EMAIL, None, request
        if "calendar" in lowered:
            return GoalIntent.MANAGE_CALENDAR, None, request
        if "spotify" in lowered or "play media" in lowered or "play music" in lowered:
            return GoalIntent.PLAY_MEDIA, None, request

        # 7. Memory Search Intent
        if any(kw in lowered for kw in ("search memory", "previous memory", "search previous memory", "remember", "yesterday", "recollection", "past conversation", "find in memory")):
            return GoalIntent.SEARCH_MEMORY, None, request

        # 7. Windows / System Intent
        if any(kw in lowered for kw in ("list processes", "running processes", "clipboard", "run command", "powershell", "cmd")):
            return GoalIntent.OPERATE_WINDOWS, None, request

        # 9. Code Generation Intent
        if any(kw in lowered for kw in ("generate code", "write python", "write script", "build app", "implement function")):
            return GoalIntent.GENERATE_CODE, None, request

        return GoalIntent.ANSWER_QUESTION, None, None

    # ---------------------------------------------------------------------------
    # Capability domain mapping — used by the Planner to run registry check
    # ---------------------------------------------------------------------------

    # Maps GoalIntent → the capability domain required to fulfil it.
    # Intents that don't require a specific installed tool map to None.
    _INTENT_CAPABILITY_DOMAIN: dict = {
        GoalIntent.READ_RESOURCE:    "filesystem",
        GoalIntent.WRITE_RESOURCE:   "filesystem",
        GoalIntent.LIST_DIRECTORY:   "filesystem",
        GoalIntent.SEARCH_RESOURCE:  "filesystem",
        GoalIntent.DELETE_RESOURCE:  "filesystem",
        GoalIntent.MOVE_RESOURCE:    "filesystem",
        GoalIntent.COPY_RESOURCE:    "filesystem",
        GoalIntent.RENAME_RESOURCE:  "filesystem",
        GoalIntent.SEARCH_MEMORY:    "memory",
        GoalIntent.OPERATE_WINDOWS:  "windows",
        GoalIntent.RUN_COMMAND:      "terminal",
        GoalIntent.USE_BROWSER:      "browser",
        GoalIntent.SEND_EMAIL:       "email",
        GoalIntent.MANAGE_CALENDAR:  "calendar",
        GoalIntent.PLAY_MEDIA:       "spotify",
        GoalIntent.GENERATE_CODE:    None,   # handled by Provider — no tool required
        GoalIntent.ANSWER_QUESTION:  None,   # handled by Provider — no tool required
    }

    @classmethod
    def capability_domain_for_intent(cls, intent: GoalIntent) -> str | None:
        """Return the capability domain required for this intent, or None.

        None means the intent can be served by the Provider alone (no tool needed).
        The Planner passes this to the CapabilityRegistry to decide whether
        execution may proceed.
        """
        return cls._INTENT_CAPABILITY_DOMAIN.get(intent)

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
