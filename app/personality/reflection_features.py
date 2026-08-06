"""Phase 9.5 — Deterministic reflection feature extraction.

Projects the completed interaction (user message, assistant response, CAP
context view, visible memories) onto a fixed boolean/numeric feature vector
consumed by the ReflectionEngine.

Pure local logic: no storage access, no LLM, no ML, no randomness, no learning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.personality.models import (
    CapContextView,
    MemoryVisibilitySummary,
    VisibleMemory,
)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")
_EXTENSION_RE = re.compile(
    r"\.(?:py|js|ts|rs|go|cpp|c|java|kt|sh|json|yaml|yml|toml|xml|sql|md|html|css)\b",
    re.IGNORECASE,
)
_CODE_FENCE_RE = re.compile(r"```")
_CODE_MARKER_RE = re.compile(
    r"\b(?:def\s|class\s|import\s|return\s|print\(|function\(|=>)\b"
)


def _normalize(text: str) -> str:
    lowered = text.lower()
    lowered = _NON_WORD_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", lowered).strip()


def _any_present(
    normalized: str, tokens: frozenset[str], phrases: frozenset[str]
) -> bool:
    if set(_WHITESPACE_RE.split(normalized)) & tokens:
        return True
    return any(phrase in normalized for phrase in phrases)


def _is_question(normalized: str) -> bool:
    if "?" in normalized:
        return True
    return _any_present(normalized, _QUESTION_TOKENS, _QUESTION_PHRASES)


# ---------------------------------------------------------------------------
# Signal vocabularies (all phrases written in normalized form)
# ---------------------------------------------------------------------------

_TECHNICAL_TOKENS = frozenset({
    "bug", "error", "exception", "traceback", "stacktrace", "refactor",
    "refactoring", "test", "tests", "function", "class", "api", "endpoint",
    "compile", "compiler", "build", "deploy", "deployment", "debug",
    "debugging", "benchmark", "performance", "optimize", "optimise",
    "algorithm", "async", "thread", "docker", "git", "code", "script",
    "syntax", "regex", "query", "sql", "database", "index", "pipeline",
    "container", "kubernetes", "k8s", "merge", "branch", "commit", "flaky",
    "timeout", "segfault", "memory", "lock", "deadlock", "server", "json",
    "schema", "cache", "latency", "http",
})
_TECHNICAL_PHRASES = frozenset({
    "stack trace", "unit test", "unit tests", "memory leak", "pull request",
    "failing test", "broken build", "segmentation fault", "http 500",
})

_CREATIVE_TOKENS = frozenset({
    "poem", "poetry", "story", "logo", "artwork", "tagline", "slogan",
    "motto", "jingle", "brand", "branding", "painting", "plot", "script",
    "creative", "inspired", "catchy", "novel", "song", "lyrics", "idea",
    "ideas", "brainstorm", "brainstorming", "imagine", "options",
    "possibilities", "concepts", "alternatives", "scenarios",
})
_CREATIVE_PHRASES = frozenset({
    "short story", "fun name", "what if", "think of", "come up with",
    "lets explore", "explore options", "potential approaches",
    "creative thinking", "new ways",
})

_PLANNING_TOKENS = frozenset({
    "plan", "planning", "strategy", "strategic", "roadmap", "milestone",
    "milestones", "timeline", "schedule", "agenda", "sprint", "backlog",
    "budget", "phases", "sequence", "prioritize", "prioritise",
})
_PLANNING_PHRASES = frozenset({
    "next steps", "long term", "step by step", "game plan", "project plan",
})

_CODING_PHRASES = frozenset({
    "write a function", "write the function", "implement a function",
    "implement a class", "write a class", "write code", "implement code",
    "write some code", "write a script",
})

_UNCERTAINTY_TOKENS = frozenset({
    "maybe", "perhaps", "unsure", "uncertain", "possibly", "probably",
    "guess", "might", "doubt",
})
_UNCERTAINTY_PHRASES = frozenset({
    "not sure", "not certain", "could be", "might be", "i think", "i guess",
    "not really sure", "not confident", "i believe", "hard to say",
    "i don t know", "i dont know", "no idea",
})

_HEDGING_TOKENS = frozenset({
    "maybe", "perhaps", "possibly", "probably", "might", "uncertain",
    "unclear", "roughly", "approximately",
})
_HEDGING_PHRASES = frozenset({
    "i m not sure", "i am not sure", "i m not certain", "i am not certain",
    "not entirely sure", "could be", "might be", "hard to say",
    "i cannot be certain", "it depends", "i believe", "not guaranteed",
    "best guess", "i would guess",
})

_CLARIFICATION_PHRASES = frozenset({
    "could you clarify", "can you clarify", "please clarify",
    "could you elaborate", "can you elaborate", "please elaborate",
    "could you specify", "can you specify", "please specify",
    "could you provide", "can you provide", "please provide",
    "what do you mean", "what exactly", "can you explain", "could you explain",
    "more details", "more context", "to clarify", "let me clarify",
    "are you referring to", "what specifically",
})

_QUESTION_TOKENS = frozenset({
    "what", "how", "why", "which", "who", "when", "where",
})
_QUESTION_PHRASES = frozenset({
    "do you", "can you", "could you", "should i", "should we", "does it",
    "is there", "are there", "what about", "how about",
})

_GOAL_PHRASES = frozenset({
    "i want to", "i need to", "i would like to", "i d like to",
    "i m trying to", "i am trying to", "my goal is", "my goal is to",
    "please help me", "help me", "can you help me", "i am working on",
    "i m working on",
})

_COMMAND_VERBS = frozenset({
    "fix", "write", "create", "implement", "refactor", "add", "remove",
    "update", "change", "debug", "build", "deploy", "install", "setup",
    "configure", "generate", "convert", "migrate", "restart", "run",
    "optimize", "optimise", "review", "test", "sort", "format",
})

_DECISION_PHRASES = frozenset({
    "which is better", "which one", "should i", "should we",
    "what do you think", "best option", "recommend",
})


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReflectionFeatures:
    """Fixed, deterministic feature vector for one completed interaction."""

    user_word_count: int
    response_word_count: int
    is_greeting: bool
    is_identity_query: bool
    is_technical: bool
    is_creative: bool
    is_planning: bool
    is_coding: bool
    contains_code: bool
    contains_plan: bool
    contains_questions: bool
    user_uncertainty: bool
    response_hedging: bool
    clarification_requested: bool
    user_goal_detected: bool
    visible_memory_count: int
    memory_summarized: bool
    requires_approval: bool
    high_risk: bool
    sensitive: bool


def extract_reflection_features(
    *,
    message: str,
    response: str,
    cap_context: CapContextView | None = None,
    visible_memories: list[VisibleMemory] | None = None,
    visibility_summary: MemoryVisibilitySummary | None = None,
    is_greeting: bool = False,
    is_identity_query: bool = False,
) -> ReflectionFeatures:
    """Extract the deterministic feature vector for a completed interaction."""
    context = cap_context or CapContextView()

    user_normalized = _normalize(message)
    response_normalized = _normalize(response)
    user_words = _WHITESPACE_RE.split(user_normalized) if user_normalized else []
    response_words = (
        _WHITESPACE_RE.split(response_normalized) if response_normalized else []
    )
    user_tokens = frozenset(user_words)

    contains_code = bool(
        _CODE_FENCE_RE.search(message)
        or _CODE_MARKER_RE.search(message)
        or bool(_EXTENSION_RE.search(message))
    )
    is_technical = _any_present(
        user_normalized, _TECHNICAL_TOKENS, _TECHNICAL_PHRASES
    )
    is_creative = _any_present(
        user_normalized, _CREATIVE_TOKENS, _CREATIVE_PHRASES
    )
    is_planning = _any_present(
        user_normalized, _PLANNING_TOKENS, _PLANNING_PHRASES
    )
    is_coding = contains_code or _any_present(
        user_normalized, frozenset(), _CODING_PHRASES
    )

    is_command = (
        "please" in user_tokens
        or "plz" in user_tokens
        or "for me" in user_normalized
        or (bool(user_words) and user_words[0] in _COMMAND_VERBS)
    )
    user_goal_detected = (
        is_planning
        or is_command
        or _any_present(user_normalized, frozenset(), _GOAL_PHRASES)
        or _any_present(user_normalized, frozenset(), _DECISION_PHRASES)
    ) and not is_greeting and not is_identity_query

    return ReflectionFeatures(
        user_word_count=len(user_words),
        response_word_count=len(response_words),
        is_greeting=is_greeting,
        is_identity_query=is_identity_query,
        is_technical=is_technical,
        is_creative=is_creative,
        is_planning=is_planning,
        is_coding=is_coding,
        contains_code=contains_code,
        contains_plan=is_planning,
        contains_questions=_is_question(user_normalized),
        user_uncertainty=_any_present(
            user_normalized, _UNCERTAINTY_TOKENS, _UNCERTAINTY_PHRASES
        ),
        response_hedging=_any_present(
            response_normalized, _HEDGING_TOKENS, _HEDGING_PHRASES
        ),
        clarification_requested=_any_present(
            response_normalized, frozenset(), _CLARIFICATION_PHRASES
        ),
        user_goal_detected=user_goal_detected,
        visible_memory_count=len(visible_memories or []),
        memory_summarized=visibility_summary is not None,
        requires_approval=context.requires_approval,
        high_risk=context.high_risk,
        sensitive=context.sensitive,
    )
