"""Phase 11.4 — deterministic Reference Resolver.

Runs BEFORE the GoalParser (GAMBIT) and resolves conversational references
(``it``, ``this``, ``that``, ``the document``, ``the previous file``,
``the same file``, ``continue``, ``the first result``) against the session's
short-lived conversation state. It never calls the Provider/LLM, never
touches storage, and never mutates the state: it is a pure function of
(request, state) → (rewritten request, ReferenceResolution).
"""

from __future__ import annotations

import re

from app.conversation.models import (
    ConversationState,
    ReferenceKind,
    ReferenceResolution,
)

# Requests that talk about the conversation/session itself must never be
# rewritten, so "delete this conversation" keeps routing to memory deletion.
_SELF_REFERENCE_PHRASES = (
    "this conversation",
    "that conversation",
    "the conversation",
    "this session",
    "that session",
    "the session",
    "this discussion",
    "that discussion",
    "this chat",
    "this thread",
    "my memory",
    "my memories",
    "all memories",
    "my data",
    "my history",
    "my preferences",
)

# Answer-replay references ("previous answer", "first answer", ...) are
# inherently conversational: the provider answers them from the conversation
# history, so they must never be rewritten into a stale file/command reference.
_ANSWER_REFERENCE_PHRASES = (
    "previous answer",
    "earlier answer",
    "previous response",
    "earlier response",
    "first answer",
    "second answer",
    "third answer",
    "the first answer",
    "the second answer",
    "your first answer",
    "your second answer",
)

_CONTINUE_RE = re.compile(r"^(continue|keep going|go on)\b(.*)$", re.IGNORECASE)
_CONTINUE_FROM_RE = re.compile(
    r"^(continue from here|pick up where (?:i|we) left off|resume)\b(.*)$",
    re.IGNORECASE,
)
_PRONOUN_RE = re.compile(r"\b(it|this|that)\b", re.IGNORECASE)

# Follow-up elaboration requests. Each pattern matches a *standalone* phrase
# only (specific topics like "explain more about CAP" pass through untouched).
# ``{target}`` is replaced with the deterministic follow-up target.
_ELABORATION_PATTERNS = (
    (re.compile(r"^(please\s+)?explain\s+more[!?.]*$", re.IGNORECASE), "Explain more about {target}."),
    (re.compile(r"^(please\s+)?explain\s+further[!?.]*$", re.IGNORECASE), "Explain more about {target}."),
    (re.compile(r"^explain\s+(?:that|this|it)[!?.]*$", re.IGNORECASE), "Explain {target}."),
    (re.compile(r"^(please\s+)?go\s+deeper[!?.]*$", re.IGNORECASE), "Go deeper into {target}."),
    (re.compile(r"^(please\s+)?give\s+more\s+details?[!?.]*$", re.IGNORECASE), "Give more details about {target}."),
    (re.compile(r"^(please\s+)?more\s+details?[!?.]*$", re.IGNORECASE), "Give more details about {target}."),
    (re.compile(r"^(please\s+)?(?:can|could)\s+you\s+elaborate(?:\s+on\s+that)?[!?.]*$", re.IGNORECASE), "Elaborate on {target}."),
    (re.compile(r"^(please\s+)?elaborate(?:\s+on\s+that)?[!?.]*$", re.IGNORECASE), "Elaborate on {target}."),
    (re.compile(r"^(please\s+)?tell\s+me\s+more(?:\s+about\s+that)?[!?.]*$", re.IGNORECASE), "Tell me more about {target}."),
    (re.compile(r"^(please\s+)?expand(?:\s+on\s+)?(?:that|this|it)?[!?.]*$", re.IGNORECASE), "Expand on {target}."),
)
_BARE_WHY_RE = re.compile(r"^why(\s+is\s+that)?[!?.]*$", re.IGNORECASE)
_BARE_HOW_RE = re.compile(r"^how(\s+(?:so|come))?[!?.]*$", re.IGNORECASE)

# A follow-up target must be short enough to inline into the rewritten request.
_MAX_FOLLOWUP_TEXT_LENGTH = 200

_SEARCH_PHRASES = (
    "the first result",
    "first result",
    "the top result",
    "top result",
    "the first file",
    "first file",
    "the first match",
    "first match",
    "the results",
    "these results",
    "the matches",
    "these files",
)

_DOCUMENT_PHRASES = (
    "the previous document",
    "the same document",
    "this document",
    "that document",
    "the document",
    "the previous file",
    "the same file",
    "this file",
    "that file",
    "the file",
    "the previous pdf",
    "this pdf",
    "that pdf",
    "the pdf",
)

_PROJECT_PHRASES = (
    "the whole project",
    "this project",
    "that project",
    "the project",
    "this workspace",
    "the workspace",
)

_DIRECTORY_PHRASES = (
    "the current directory",
    "the current folder",
    "this directory",
    "that directory",
    "the directory",
    "this folder",
    "that folder",
    "the folder",
)

_REPOSITORY_PHRASES = (
    "the repository",
    "this repository",
    "that repository",
    "the repo",
    "this repo",
    "that repo",
    "the codebase",
)

_SAVE_VERBS = ("save", "export", "store", "keep", "persist", "record", "write")
_RUN_VERBS = ("run", "execute", "rerun", "replay", "compile", "test")
_READ_VERBS = (
    "read", "open", "show", "view", "examine", "inspect", "summarize",
    "explain", "translate", "extract", "analyze", "parse", "list", "describe",
    "outline", "convert", "delete", "remove", "copy", "move", "rename",
)


def _replace_first(text: str, phrase: str, replacement: str) -> str:
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    return pattern.sub(lambda _m: replacement, text, count=1)


def _phrase_match(lowered: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if phrase in lowered:
            return phrase
    return None


class ReferenceResolver:
    """Pure, deterministic request rewriter backed by conversation state."""

    def resolve(
        self,
        request: str,
        state: ConversationState,
    ) -> ReferenceResolution:
        original = " ".join((request or "").strip().split())
        unresolved = ReferenceResolution(
            resolved=False,
            original_request=original,
            request=original,
        )
        if not original:
            return unresolved

        lowered = original.lower()
        for phrase in _SELF_REFERENCE_PHRASES + _ANSWER_REFERENCE_PHRASES:
            if phrase in lowered:
                return unresolved

        # 1. continue from here / pick up where I left off / resume
        match = _CONTINUE_FROM_RE.match(original)
        if match:
            rest = match.group(2).strip()
            resource = state.last_command or state.last_resource
            if resource:
                rewritten = f"continue {resource}"
                if rest:
                    rewritten = f"{rewritten} {rest}"
                return self._resolved(original, rewritten, ReferenceKind.COMMAND, resource)

        # 1a. continue / keep going / go on
        match = _CONTINUE_RE.match(original)
        if match:
            verb = match.group(1)
            rest = match.group(2).strip()
            resource = state.last_command or state.last_resource
            if resource:
                rewritten = f"{verb} {resource}"
                if rest:
                    rewritten = f"{rewritten} {rest}"
                return self._resolved(original, rewritten, ReferenceKind.COMMAND, resource)

        # 1c. Elaboration follow-ups — "Explain more", "Go deeper", "Tell me more".
        for pattern, template in _ELABORATION_PATTERNS:
            if pattern.match(original):
                target, kind = self._followup_target(state)
                if target is None:
                    return unresolved
                rewritten = template.replace("{target}", target)
                return self._resolved(original, rewritten, kind, target)

        # 1d. Bare "why?" / "how?" follow-ups.
        if _BARE_WHY_RE.match(original) or _BARE_HOW_RE.match(original):
            target, kind = self._followup_target(state)
            if target is not None:
                return self._resolved(original, f"Explain {target}.", kind, target)

        # 2. Search results — "the first result", "the top file", ...
        phrase = _phrase_match(lowered, _SEARCH_PHRASES)
        if phrase and state.last_search_results:
            target = state.last_search_results[0]
            rewritten = _replace_first(original, phrase, target)
            return self._resolved(original, rewritten, ReferenceKind.SEARCH_RESULT, target)

        # 3. Named document / file references — "the previous file", "same file"
        phrase = _phrase_match(lowered, _DOCUMENT_PHRASES)
        if phrase:
            if state.active_document:
                rewritten = _replace_first(original, phrase, state.active_document)
                return self._resolved(original, rewritten, ReferenceKind.DOCUMENT, state.active_document)
            if state.active_code_file:
                rewritten = _replace_first(original, phrase, state.active_code_file)
                return self._resolved(original, rewritten, ReferenceKind.CODE_FILE, state.active_code_file)

        # 4. Project / directory / repository references
        phrase = _phrase_match(lowered, _PROJECT_PHRASES)
        if phrase and state.active_project:
            rewritten = _replace_first(original, phrase, state.active_project)
            return self._resolved(original, rewritten, ReferenceKind.PROJECT, state.active_project)
        phrase = _phrase_match(lowered, _DIRECTORY_PHRASES)
        if phrase and state.active_directory:
            rewritten = _replace_first(original, phrase, state.active_directory)
            return self._resolved(original, rewritten, ReferenceKind.DIRECTORY, state.active_directory)
        phrase = _phrase_match(lowered, _REPOSITORY_PHRASES)
        if phrase and state.active_repository:
            rewritten = _replace_first(original, phrase, state.active_repository)
            return self._resolved(original, rewritten, ReferenceKind.REPOSITORY, state.active_repository)

        # 5. Bare pronouns — "it", "this", "that" resolved by verb precedence.
        pronoun = _PRONOUN_RE.search(original)
        if pronoun:
            target = self._pronoun_target(state, original)
            if target is not None:
                kind, resource, display = target
                rewritten = _replace_first(original, pronoun.group(0), display)
                return self._resolved(original, rewritten, kind, resource)

        return unresolved

    @staticmethod
    def _resolved(
        original: str,
        rewritten: str,
        kind: ReferenceKind,
        resource: str,
    ) -> ReferenceResolution:
        return ReferenceResolution(
            resolved=True,
            kind=kind,
            resource=resource,
            display=resource,
            original_request=original,
            request=rewritten,
        )

    @staticmethod
    def _followup_target(
        state: ConversationState,
    ) -> tuple[str, ReferenceKind] | tuple[None, None]:
        """Deterministic target for "explain more"-style follow-ups.

        Preference order: the concrete active resource first, then a short
        generated response, then the previous command (the last topic the user
        raised), then the last parsed goal. Returns (None, None) when nothing
        was ever discussed.
        """
        for value, kind in (
            (state.active_document, ReferenceKind.DOCUMENT),
            (state.active_code_file, ReferenceKind.CODE_FILE),
            (state.last_resource, ReferenceKind.RESOURCE),
        ):
            if value:
                return value, kind
        if state.last_generated_text and len(state.last_generated_text) <= _MAX_FOLLOWUP_TEXT_LENGTH:
            return state.last_generated_text, ReferenceKind.GENERATED_TEXT
        if state.last_command:
            return state.last_command, ReferenceKind.COMMAND
        if state.last_goal:
            return state.last_goal, ReferenceKind.UNKNOWN
        return None, None

    @staticmethod
    def _pronoun_target(
        state: ConversationState,
        request: str,
    ) -> tuple[ReferenceKind, str, str] | None:
        first = request.split()[0].lower().rstrip(".,!?;:")
        if first in _SAVE_VERBS and state.last_generated_text:
            return (ReferenceKind.GENERATED_TEXT, state.last_generated_text, "the generated text")
        if first in _RUN_VERBS:
            if state.last_generated_text:
                return (ReferenceKind.GENERATED_TEXT, state.last_generated_text, "the generated script")
            if state.last_command:
                return (ReferenceKind.COMMAND, state.last_command, "the previous command")
        if first in _READ_VERBS:
            if state.active_document:
                return (ReferenceKind.DOCUMENT, state.active_document, state.active_document)
            if state.active_code_file:
                return (ReferenceKind.CODE_FILE, state.active_code_file, state.active_code_file)
        for resource, kind in (
            (state.active_document, ReferenceKind.DOCUMENT),
            (state.active_code_file, ReferenceKind.CODE_FILE),
            (state.last_generated_text, ReferenceKind.GENERATED_TEXT),
            (state.last_command, ReferenceKind.COMMAND),
            (state.last_resource, ReferenceKind.RESOURCE),
        ):
            if resource:
                return (kind, resource, resource)
        return None
