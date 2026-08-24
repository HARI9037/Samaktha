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
        intent_action, intent_arguments, missing_arguments = (
            self.extract_intent_arguments(intent, normalized)
        )
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
            intent_action=intent_action,
            intent_arguments=intent_arguments,
            missing_arguments=missing_arguments,
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

        if any(kw in lowered for kw in ("search memory", "previous memory", "search previous memory", "remember", "yesterday", "recollection", "past conversation", "find in memory")):
            return GoalIntent.SEARCH_MEMORY, None, request

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

        # 1e. Personal and communication actions.  These patterns require an
        # action verb near the product noun so technical discussion such as
        # "email architecture" or "calendar algorithm" remains a question.
        if re.search(r"\b(?:remind me|create|add|list|show|cancel|update|complete)\b.*\breminder(?:s)?\b", lowered) or lowered.startswith("remind me"):
            return GoalIntent.MANAGE_REMINDER, None, request
        if "memory" not in lowered and (
            re.search(r"\b(?:create|add|write)\b.*\b(?:a\s+)?note\b(?:\s+(?:titled|called|with)\b|$)", lowered)
            or re.search(r"\b(?:list|show|search|find|read|update|delete)\b.*\bnotes?\b(?!\.)", lowered)
        ):
            return GoalIntent.MANAGE_NOTE, None, request
        if re.search(r"\b(?:create|add|list|show|complete|finish|update|delete|find|search)\b.*\btask(?:s)?\b", lowered):
            return GoalIntent.MANAGE_TASK, None, request
        if re.search(r"\b(?:create|add|update|delete|list|show)\b.*\bcontact(?:s)?\b", lowered):
            return GoalIntent.MANAGE_CONTACT, None, request
        if re.search(r"\b(?:find|search|look up)\b.*\bcontact(?:s)?\b|\bcontact\s+(?:for\s+)?\S+", lowered):
            return GoalIntent.SEARCH_CONTACT, None, request
        if re.search(r"\b(?:create|add|schedule|list|show|delete|cancel|update)\b.*\b(?:calendar|event|appointment)\b", lowered):
            return GoalIntent.MANAGE_CALENDAR, None, request
        if re.search(r"\bforward\b.*\bemail\b", lowered):
            return GoalIntent.FORWARD_EMAIL, None, request
        if re.search(r"\breply\b.*\bemail\b", lowered):
            return GoalIntent.REPLY_EMAIL, None, request
        if re.search(r"\b(?:read|show|list|search|find)\b.*\bemail(?:s)?\b", lowered):
            return GoalIntent.READ_EMAIL, None, request
        if re.search(r"\b(?:send|compose|draft|write)\b\s+(?:an?\s+)?email\b", lowered):
            return GoalIntent.SEND_EMAIL, None, request
        if re.search(r"\breply\b.*\bmessage\b", lowered):
            return GoalIntent.SEND_MESSAGE, None, request
        if re.search(r"\b(?:read|show|list)\b.*\bmessages\b", lowered):
            return GoalIntent.READ_MESSAGES, None, request
        if re.search(r"\b(?:search|find)\b.*\bmessages\b", lowered):
            return GoalIntent.SEARCH_MESSAGES, None, request
        if re.search(r"\b(?:send|draft|write)\b\s+(?:a\s+)?message\b", lowered):
            return GoalIntent.SEND_MESSAGE, None, request
        if re.search(r"\b(?:use|open|browse)\b.*\bbrowser\b|\bin (?:the )?browser\b", lowered):
            return GoalIntent.USE_BROWSER, None, request

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
            "what is inside", "what's inside", "contents of", "show files", "desktop contents"
        )
        has_list_verb = bool(re.search(r"\b(?:list|ls|dir|browse)\b", lowered))
        if has_list_verb or any(kw in lowered for kw in list_keywords) or (extracted_path and any(k in lowered for k in ("folder", "directory", "desktop"))):
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

        # 6. Media intent. Execution remains explicitly unavailable in P2.
        if "spotify" in lowered or "play media" in lowered or "play music" in lowered:
            return GoalIntent.PLAY_MEDIA, None, request

        # 7. Memory Search Intent
        if any(kw in lowered for kw in ("search memory", "previous memory", "search previous memory", "remember", "yesterday", "recollection", "past conversation", "find in memory")):
            return GoalIntent.SEARCH_MEMORY, None, request

        # 9. Code Generation Intent
        if any(kw in lowered for kw in ("generate code", "write python", "write script", "build app", "implement function")):
            return GoalIntent.GENERATE_CODE, None, request

        return GoalIntent.ANSWER_QUESTION, None, None

    @staticmethod
    def extract_intent_arguments(
        intent: GoalIntent, request: str
    ) -> tuple[str | None, dict, list[str]]:
        """Extract only deterministic, user-supplied tool arguments.

        Missing values are returned explicitly.  No recipient, title, path,
        time, destination, or identifier is fabricated by GAMBIT.
        """
        lowered = request.lower()
        args: dict = {}
        missing: list[str] = []

        def _match(pattern: str, group: str = "value") -> str | None:
            found = re.search(pattern, request, re.IGNORECASE | re.DOTALL)
            return found.group(group).strip(" \t\r\n'\"") if found else None

        if intent in {
            GoalIntent.READ_RESOURCE,
            GoalIntent.WRITE_RESOURCE,
            GoalIntent.DELETE_RESOURCE,
            GoalIntent.MOVE_RESOURCE,
            GoalIntent.COPY_RESOURCE,
            GoalIntent.RENAME_RESOURCE,
        }:
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", request)
            action = {
                GoalIntent.READ_RESOURCE: "read",
                GoalIntent.WRITE_RESOURCE: "write",
                GoalIntent.DELETE_RESOURCE: "delete",
                GoalIntent.MOVE_RESOURCE: "move",
                GoalIntent.COPY_RESOURCE: "copy",
                GoalIntent.RENAME_RESOURCE: "rename",
            }[intent]
            source = quoted[0] if quoted else _match(
                r"(?:read|open|delete|remove|move|copy|rename|write(?:\s+to)?|create\s+file)\s+(?P<value>\S+)"
            )
            if source:
                args["path"] = source
            else:
                missing.append("path")
            if intent == GoalIntent.WRITE_RESOURCE:
                content = _match(r"\b(?:content|text)\s*(?:of|is|:)?\s*(?P<value>.+)$")
                if content:
                    args["content"] = content
                else:
                    missing.append("content")
            if intent in {GoalIntent.MOVE_RESOURCE, GoalIntent.COPY_RESOURCE, GoalIntent.RENAME_RESOURCE}:
                destination = quoted[1] if len(quoted) > 1 else _match(r"\bto\s+(?P<value>\S+)$")
                if destination:
                    args["destination"] = destination
                else:
                    missing.append("destination")
            return action, args, missing

        if intent == GoalIntent.RUN_COMMAND:
            command = re.sub(
                r"^\s*(?:please\s+)?(?:run|execute)\s+(?:the\s+)?(?:shell\s+)?command\s*[:\-]?\s*",
                "",
                request,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
            if command:
                args["command"] = command
            else:
                missing.append("command")
            return "run", args, missing

        if intent == GoalIntent.CLIPBOARD:
            write = any(word in lowered for word in ("copy", "write", "put", "set", "save"))
            if not write:
                return "read", {"action": "read"}, []
            content = _match(r"(?:copy|write|put|set|save)\s+(?P<value>.+?)\s+(?:to|on|into)\s+(?:the\s+)?clipboard\b")
            if content:
                args["content"] = content
            else:
                missing.append("content")
            args["action"] = "write"
            return "write", args, missing

        if intent == GoalIntent.SEND_NOTIFICATION:
            message = re.sub(
                r"^\s*(?:please\s+)?(?:notify me|send (?:me )?(?:a )?notification|show (?:me )?(?:a )?notification)\s*(?:that|to|:|-)?\s*",
                "",
                request,
                count=1,
                flags=re.IGNORECASE,
            ).strip()
            if not message or message.lower() == "notification":
                missing.append("message")
            else:
                args.update(title="Notification", message=message)
            return "send", args, missing

        if intent == GoalIntent.MANAGE_NOTE:
            if re.search(r"\b(?:list|show)\b", lowered):
                return "list", {"action": "list"}, []
            if re.search(r"\b(?:search|find)\b", lowered):
                query = _match(r"(?:search|find).*?notes?\s+(?:for\s+)?(?P<value>.+)$")
                return "search", {"action": "search", "query": query or ""}, ([] if query else ["query"])
            title = _match(r"\bnote\s+(?:titled|called)\s+(?P<value>.+?)(?:\s+with\s+(?:content|text)\b|$)")
            content = _match(r"\bwith\s+(?:content|text)\s+(?P<value>.+)$")
            args = {"action": "create"}
            if title: args["title"] = title
            else: missing.append("title")
            if content: args["content"] = content
            return "create", args, missing

        if intent == GoalIntent.MANAGE_TASK:
            if re.search(r"\b(?:list|show)\b", lowered):
                return "list", {"action": "list"}, []
            if re.search(r"\b(?:complete|finish)\b", lowered):
                task_id = _match(r"(?:complete|finish).*?task\s+(?P<value>[A-Za-z0-9_-]+)")
                args = {"action": "complete"}
                if task_id: args["task_id"] = task_id
                else: missing.append("task_id")
                return "complete", args, missing
            title = _match(r"\btask\s+(?:titled|called)\s+(?P<value>.+?)(?:\s+(?:due|with)\b|$)")
            args = {"action": "create"}
            if title: args["title"] = title
            else: missing.append("title")
            return "create", args, missing

        if intent == GoalIntent.MANAGE_REMINDER:
            if re.search(r"\b(?:list|show)\b", lowered):
                return "list", {"action": "list"}, []
            title = _match(r"\bremind me\s+(?:to\s+)?(?P<value>.+?)(?:\s+at\s+\d{4}-\d{2}-\d{2}T|$)")
            due_at = _match(r"\bat\s+(?P<value>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)")
            args = {"action": "create"}
            if title: args["title"] = title
            else: missing.append("title")
            if due_at: args["due_at"] = due_at
            else: missing.append("due_at")
            return "create", args, missing

        if intent in {GoalIntent.SEARCH_CONTACT, GoalIntent.MANAGE_CONTACT}:
            if intent == GoalIntent.SEARCH_CONTACT:
                query = _match(r"(?:find|search|look up).*?contact(?:s)?(?:\s+for)?\s+(?P<value>.+)$") or _match(r"\bcontact\s+(?:for\s+)?(?P<value>.+)$")
                return "search", {"action": "search", "query": query or ""}, ([] if query else ["query"])
            if re.search(r"\b(?:list|show)\b", lowered):
                return "list", {"action": "list"}, []
            name = _match(r"\bcontact\s+(?:named|called)?\s*(?P<value>.+?)(?:\s+(?:email|phone)\b|$)")
            email = _match(r"\bemail\s+(?P<value>\S+@\S+)")
            phone = _match(r"\bphone\s+(?P<value>[+()0-9 .-]+)$")
            args = {"action": "create"}
            if name: args["name"] = name
            else: missing.append("name")
            if email: args["emails"] = [email]
            if phone: args["phones"] = [phone]
            if not email and not phone: missing.append("email_or_phone")
            return "create", args, missing

        if intent == GoalIntent.MANAGE_CALENDAR:
            if re.search(r"\b(?:list|show)\b", lowered):
                return "list", {"action": "list"}, []
            title = _match(r"\b(?:event|appointment)\s+(?:titled|called)\s+(?P<value>.+?)(?:\s+at\s+\d{4}-\d{2}-\d{2}T|$)")
            start_at = _match(r"\bat\s+(?P<value>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)")
            args = {"action": "create"}
            if title: args["title"] = title
            else: missing.append("title")
            if start_at: args["start_at"] = start_at
            else: missing.append("start_at")
            return "create", args, missing

        if intent in {GoalIntent.SEND_EMAIL, GoalIntent.READ_EMAIL, GoalIntent.REPLY_EMAIL, GoalIntent.FORWARD_EMAIL}:
            if intent == GoalIntent.READ_EMAIL:
                if "search" in lowered or "find" in lowered:
                    query = _match(r"(?:search|find).*?emails?\s+(?:for\s+)?(?P<value>.+)$")
                    return "search", {"action": "search", "query": query or ""}, ([] if query else ["query"])
                return "list_folders", {"action": "list_folders"}, []
            action = "reply" if intent == GoalIntent.REPLY_EMAIL else "forward" if intent == GoalIntent.FORWARD_EMAIL else "draft" if re.search(r"\b(?:draft|compose)\b", lowered) else "send"
            recipient = _match(r"\bto\s+(?P<value>[^\s,;]+@[^\s,;]+)")
            subject = _match(r"\bsubject\s+(?P<value>.+?)(?:\s+body\b|$)")
            body = _match(r"\bbody\s+(?P<value>.+)$")
            message_id = _match(r"\bemail\s+(?P<value>[A-Za-z0-9_-]+)") if action in {"reply", "forward"} else None
            args = {"action": action}
            if recipient: args["recipient"] = recipient
            if subject: args["subject"] = subject
            if body: args["body"] = body
            if message_id: args["message_id"] = message_id
            required = ["recipient", "subject", "body"] if action in {"send", "draft"} else ["message_id", "body"] if action == "reply" else ["message_id", "recipient"]
            missing.extend(field for field in required if not args.get(field))
            return action, args, missing

        if intent in {GoalIntent.SEND_MESSAGE, GoalIntent.READ_MESSAGES, GoalIntent.SEARCH_MESSAGES}:
            if intent == GoalIntent.READ_MESSAGES:
                return "history", {"action": "history"}, []
            if intent == GoalIntent.SEARCH_MESSAGES:
                query = _match(r"(?:search|find).*?messages?\s+(?:for\s+)?(?P<value>.+)$")
                return "search", {"action": "search", "query": query or ""}, ([] if query else ["query"])
            action = "draft" if "draft" in lowered else "reply" if "reply" in lowered else "send"
            recipient = _match(r"\bto\s+(?P<value>.+?)(?:\s+saying\b|\s+body\b|$)")
            body = _match(r"\b(?:saying|body)\s+(?P<value>.+)$")
            args = {"action": action}
            if recipient: args["recipient"] = recipient
            if body: args["body"] = body
            missing.extend(field for field in ("recipient", "body") if not args.get(field))
            return action, args, missing

        return None, {}, []

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
        GoalIntent.MANAGE_REMINDER: "reminder",
        GoalIntent.MANAGE_NOTE: "note",
        GoalIntent.MANAGE_TASK: "task",
        GoalIntent.MANAGE_CONTACT: "contact",
        GoalIntent.USE_BROWSER:      "browser",
        GoalIntent.SEND_EMAIL:       "email",
        GoalIntent.READ_EMAIL:       "email",
        GoalIntent.REPLY_EMAIL:      "email",
        GoalIntent.FORWARD_EMAIL:    "email",
        GoalIntent.SEND_MESSAGE:     "message",
        GoalIntent.READ_MESSAGES:    "message",
        GoalIntent.SEARCH_MESSAGES:  "message",
        GoalIntent.SEARCH_CONTACT:   "contact",
        GoalIntent.MANAGE_CALENDAR:  "calendar",
        GoalIntent.PLAY_MEDIA:       "media",
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
