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

# Word-boundary regex for read-intent keyword detection.  Must be compiled at
# module level (not inside detect_intent) so it is only compiled once.
# Using \b prevents substring false-positives such as "bread" → "read",
# "thread" → "read", "already" → "read", or "spreadsheet" → "read".
_READ_KW_RE = re.compile(
    r"\b(?:read|open|cat|show|examine|inspect|summarize)\b",
    re.IGNORECASE,
)


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

        # 1b. Memory Deletion Intent — must be detected before any filesystem
        # delete routing so "forget everything about me" never reaches the
        # filesystem tool. Deterministic phrase matching only; no LLM.
        if GoalParser._is_memory_delete(lowered):
            return GoalIntent.DELETE_MEMORY, None, request

        # 1c. Internet Intelligence Intent (Phase 12) — evaluated before any
        # filesystem search routing so "search the web for X" never resolves
        # to SEARCH_RESOURCE. Memory search phrases remain excluded (handled
        # below). No LLM — deterministic signals only.
        if GoalParser._is_internet_intent(lowered):
            return GoalIntent.SEARCH_INTERNET, None, request

        # 1d. System-level intents (Phase 13) — high-precision triggers
        # evaluated before any filesystem routing so "copy X to the clipboard"
        # never resolves to COPY_RESOURCE, "run command …" never resolves to
        # LIST_DIRECTORY (via the "dir" substring in "directory"), and
        # "list processes" never resolves to LIST_DIRECTORY.
        if "list processes" in lowered or "running processes" in lowered:
            return GoalIntent.OPERATE_WINDOWS, None, request
        if any(kw in lowered for kw in ("notify me", "send notification", "send a notification", "show notification", "desktop notification", "notification")):
            return GoalIntent.SEND_NOTIFICATION, None, request
        if "clipboard" in lowered:
            return GoalIntent.CLIPBOARD, None, request
        if any(kw in lowered for kw in ("run command", "run the command", "run shell", "shell command", "execute command", "powershell", "cmd")):
            return GoalIntent.RUN_COMMAND, None, request

        # 2. Search Resource Intent
        search_keywords = ("search", "find", "locate")
        if any(lowered.startswith(f"{kw} ") for kw in search_keywords) or any(f" {kw} " in lowered for kw in search_keywords):
            # Exclude "search memory" which is SEARCH_MEMORY
            if not any(k in lowered for k in ("memory", "conversation", "yesterday", "recollection")):
                return GoalIntent.SEARCH_RESOURCE, extracted_path, None

        # 3. File / Resource Read Intent
        # Word-boundary match via module-level _READ_KW_RE (see top of module).
        # Previously used substring `kw in lowered` which caused false-positives:
        # "bread" → "read", "thread" → "read", "spreadsheet" → "read", etc.
        if extracted_path and _READ_KW_RE.search(lowered):
            return GoalIntent.READ_RESOURCE, extracted_path, None
        if _READ_KW_RE.match(lowered):
            return GoalIntent.READ_RESOURCE, extracted_path, None


        # 3.5. Write Resource
        write_keywords = ("create", "write", "save", "make", "generate file", "create file", "write file", "save file")
        if any(kw in lowered for kw in write_keywords):
            # Isolate the substring between the write verb and modifiers (with, in, content, text)
            # This prevents us from accidentally matching paths inside the directory specifier
            # (e.g. "in C:/Users/...") or the content block (e.g. "Completed Phase 11.5").
            _verb_re = re.search(
                r"(?:create|write|save|make|generate file|create file|write file|save file)\s+(?:a\s+|an\s+|the\s+)?(.*?)\s+(?:with|in|content|text|$)", 
                request, 
                re.IGNORECASE
            )
            _paths = []
            if _verb_re:
                _paths_str = _verb_re.group(1)
                _multi_matches = re.findall(
                    r"['\"]?([a-zA-Z]:[\\/][^'\",\s]+|/?[^'\",\s]+\.[a-zA-Z0-9]+)['\"]?", 
                    _paths_str
                )
                _paths = [m for m in _multi_matches if m]
                
            # Use the first path if multi-match failed but the fallback extracted_path worked
            if not _paths and extracted_path:
                _paths = [extracted_path]
                
            write_path_str = "|".join(_paths) if _paths else None

            content_match = re.search(r"(?:content|text)\s*(?:of|is|:)?\s*(.*)", request, re.IGNORECASE | re.DOTALL)
            if content_match:
                _raw = content_match.group(1).strip()
                # Only strip a matching outer quote PAIR (e.g. "..." or '...').
                # Never use .strip("'\"") which greedily eats internal quotes.
                if len(_raw) >= 2 and _raw[0] in ('"', "'") and _raw[-1] == _raw[0]:
                    content = _raw[1:-1]
                else:
                    content = _raw
            else:
                # Fallback: strip the write verb and the target path(s) from the raw
                # request so the path prefix is never injected into the file body.
                content = request
                # Strip leading write verb (e.g. "Create", "Write", "Save")
                _verb_re = re.compile(
                    r"^\s*(?:create|write|save|make|generate file|create file|write file|save file)\s+(?:a\s+|an\s+|the\s+)?",
                    re.IGNORECASE,
                )
                content = _verb_re.sub("", content, count=1).strip()
                # Strip ALL extracted target paths from the start of what remains
                for p in _paths:
                    _path_escaped = re.escape(p)
                    # Strip the path and optional commas/ands
                    content = re.sub(
                        r"^\s*(?:and\s+|,\s*)?" + _path_escaped + r"\s*(?:with\s+(?:the\s+)?(?:content|text)?\s*:?\s*)?",
                        "",
                        content,
                        count=1,
                        flags=re.IGNORECASE,
                    ).strip()
                # Strip any remaining leading "with the content/text" preamble
                content = re.sub(
                    r"^with\s+(?:the\s+)?(?:content|text)?\s*:?\s*",
                    "",
                    content,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()
                # Strip surrounding quotes that may wrap the entire content block
                if len(content) >= 2 and content[0] in ('"', "'") and content[-1] == content[0]:
                    content = content[1:-1].strip()
                    
            # Require strong evidence for WRITE_RESOURCE to prevent generic generation
            # from being classified as a file creation attempt.
            strong_keywords = ("create file", "save file", "write to file", "save as", "create document", "write into", "write file")
            has_strong_keyword = any(kw in lowered for kw in strong_keywords)
            
            if write_path_str or has_strong_keyword:
                return GoalIntent.WRITE_RESOURCE, write_path_str, content
            
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

        # 5. Delete, Move, Copy, Rename Resource
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

        # 9. Code Generation Intent
        if any(kw in lowered for kw in ("generate code", "write python", "write script", "build app", "implement function")):
            return GoalIntent.GENERATE_CODE, None, request

        return GoalIntent.ANSWER_QUESTION, None, None

    # ---------------------------------------------------------------------------
    # Memory deletion detection (deterministic, no filesystem routing)
    # ---------------------------------------------------------------------------

    _MEMORY_DELETE_PHRASES: tuple[str, ...] = (
        "delete my memory",
        "delete memory",
        "delete all memories",
        "delete all my memories",
        "delete my memories",
        "clear my memory",
        "clear memory",
        "erase my memory",
        "erase memory",
        "wipe my memory",
        "wipe memory",
        "forget everything about me",
        "forget everything",
        "forget all about me",
        "forget about me",
        "forget me",
        "forget all preferences",
        "forget my preferences",
        "forget my preference",
        "delete all preferences",
        "delete my preferences",
        "delete my preference",
        "remove all preferences",
        "remove my preferences",
        "remove my preference",
        "forget today's discussion",
        "forget today's conversation",
        "delete today's discussion",
        "delete today's conversation",
        "delete this conversation",
        "forget this conversation",
        "delete conversation",
        "forget conversation",
        "delete this session",
        "forget this session",
        "clear my session",
        "delete my session",
        "forget my session",
        "delete all my data",
        "erase all data",
        "wipe all data",
        "clear all my data",
        "delete all memory",
        "delete my history",
        "clear my history",
        "forget my history",
        "forget my project",
        "forget this project",
        "delete this project",
        "delete my data",
        "delete my session",
    )

    _MEMORY_DELETE_NOUNS: tuple[str, ...] = (
        "memory", "memories", "preference", "preferences", "conversation",
        "discussion", "history", "recollection", "recollections",
    )

    _MEMORY_DELETE_VERBS: tuple[str, ...] = (
        "forget", "forgot", "erase", "wipe", "clear", "remove",
    )

    @classmethod
    def _is_memory_delete(cls, lowered: str) -> bool:
        """Decide whether a request asks to forget/delete memory (not a file)."""
        if any(phrase in lowered for phrase in cls._MEMORY_DELETE_PHRASES):
            return True
        has_delete_verb = "delete" in lowered or any(
            f"{verb} " in lowered or lowered.endswith(verb)
            for verb in cls._MEMORY_DELETE_VERBS
        )
        if not has_delete_verb:
            return False
        # The request is an explicit memory target only when the memory noun is
        # the object of the deletion verb (e.g. "delete today's discussion").
        return any(
            f"{verb} " in lowered and noun in lowered
            for verb in cls._MEMORY_DELETE_VERBS + ("delete",)
            for noun in cls._MEMORY_DELETE_NOUNS
        ) or any(
            noun in lowered
            for noun in ("my memory", "all memories", "my memories", "everything about me")
        )

    # ---------------------------------------------------------------------------
    # Internet intelligence detection (Phase 12 — deterministic, no LLM)
    # ---------------------------------------------------------------------------

    # High-precision trigger phrases: when one appears, the request very likely
    # needs current, external information the model cannot know from training.
    _INTERNET_INTENT_PHRASES: tuple[str, ...] = (
        "what's the latest",
        "what is the latest",
        "latest news",
        "breaking news",
        "today's news",
        "recent news",
        "current news",
        "what's new",
        "what is new",
        "latest update",
        "latest version",
        "latest release",
        "what's trending",
        "what is trending",
        "current status",
        "live score",
        "live results",
        "current time",
        "current weather",
        "weather forecast",
        "this week",
        "this month",
        "recently",
        "as of today",
        "as of now",
        "just now",
        "updated today",
        "release notes",
        "changelog",
        "api documentation",
        "official documentation",
        "up to date",
        "up-to-date",
    )

    # Verbs that introduce an explicit search/lookup request.
    _INTERNET_INTENT_VERBS: tuple[str, ...] = (
        "search the web",
        "search online",
        "look up",
        "look it up",
        "google",
        "browse the web",
        "find online",
        "search the internet",
        "check online",
        "find out",
        "web search",
    )

    # Freshness/time-sensitivity markers that make an external lookup required.
    _INTERNET_FRESHNESS_MARKERS: tuple[str, ...] = (
        "latest",
        "current",
        "recent",
        "today",
        "now",
        "live",
        "updated",
        "newest",
        "news",
        "release",
        "version",
        "update",
    )

    @classmethod
    def _is_internet_intent(cls, lowered: str) -> bool:
        # Memory searches are always local; never route them to the internet.
        if any(k in lowered for k in ("memory", "conversation", "recollection")):
            return False
        if any(phrase in lowered for phrase in cls._INTERNET_INTENT_PHRASES):
            return True
        if any(f"{verb} " in lowered or lowered.endswith(verb) for verb in cls._INTERNET_INTENT_VERBS):
            return True
        # "search/look up/find <something>" about a current topic → internet.
        if any(kw in lowered for kw in ("search", "find", "look up")):
            if cls._INTERNET_FRESHNESS_MARKERS and any(
                marker in lowered for marker in cls._INTERNET_FRESHNESS_MARKERS
            ):
                return True
        return False

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
        GoalIntent.DELETE_MEMORY:    "memory",
        GoalIntent.DELETE_RESOURCE:  "filesystem",
        GoalIntent.MOVE_RESOURCE:    "filesystem",
        GoalIntent.COPY_RESOURCE:    "filesystem",
        GoalIntent.RENAME_RESOURCE:  "filesystem",
        GoalIntent.SEARCH_MEMORY:    "memory",
        GoalIntent.SEARCH_INTERNET:  "internet",
        GoalIntent.OPERATE_WINDOWS:  "windows",
        GoalIntent.RUN_COMMAND:      "shell",
        GoalIntent.CLIPBOARD:        "clipboard",
        GoalIntent.SEND_NOTIFICATION: "notification",
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
