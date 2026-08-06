"""Phase 9.3 — Deterministic behavior feature extraction.

Projects the user message, a CAP context view, conversation metadata, and the
visible memories onto a fixed set of boolean/numeric features that the policy
evaluators consume.

Pure local logic: no storage access, no LLM, no randomness, no prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.personality.models import CapContextView, ConversationMetadataView, VisibleMemory

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")
_EXTENSION_RE = re.compile(
    r"\.(?:py|js|ts|rs|go|cpp|c|java|kt|sh|json|yaml|yml|toml|xml|sql|md|html|css)\b",
    re.IGNORECASE,
)


def _normalize(message: str) -> str:
    text = message.lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _any_present(
    normalized: str, tokens: frozenset[str], phrases: frozenset[str]
) -> bool:
    if set(_WHITESPACE_RE.split(normalized)) & tokens:
        return True
    return any(phrase in normalized for phrase in phrases)


# ---------------------------------------------------------------------------
# Signal vocabularies (all phrases are written in normalized form)
# ---------------------------------------------------------------------------

_SERIOUS_TOKENS = frozenset({
    "urgent", "critical", "incident", "broken", "crash", "crashed", "failed",
    "failure", "production", "outage", "security", "vulnerability", "exploit",
    "breach", "attack", "risk", "risky", "deadline", "emergency", "dangerous",
    "corrupted", "restore", "asap", "lost",
})
_SERIOUS_PHRASES = frozenset({
    "data loss", "critical path", "critical issue", "production down",
})

_CASUAL_TOKENS = frozenset({
    "hey", "dude", "bro", "buddy", "mate", "lol", "lmao", "haha", "hehe",
    "cool", "awesome", "nice", "sweet", "yep", "yeah", "yah", "nah", "nope",
    "ok", "okay", "btw", "tbh", "kidding", "fun", "funny", "chill", "relax",
    "gonna", "wanna", "lemme", "yo", "howdy", "thx", "ty", "cheers", "casual",
    "whatever", "totally", "super",
})
_CASUAL_PHRASES = frozenset({
    "no worries", "sure thing", "pretty cool", "just kidding", "having fun",
})

_TECHNICAL_TOKENS = frozenset({
    "bug", "error", "exception", "traceback", "stacktrace", "refactor",
    "refactoring", "tests", "test", "function", "class", "api", "endpoint",
    "compile", "compiler", "build", "deploy", "deployment", "debug",
    "debugging", "benchmark", "performance", "optimize", "optimise",
    "algorithm", "async", "thread", "docker", "git", "code", "script",
    "syntax", "regex", "query", "sql", "database", "index", "pipeline",
    "container", "kubernetes", "k8s", "merge", "branch", "commit", "flaky",
    "timeout", "segfault", "memory", "lock", "deadlock",
})
_TECHNICAL_PHRASES = frozenset({
    "stack trace", "unit test", "unit tests", "memory leak", "pull request",
    "failing test", "broken build", "segmentation fault",
})

_BRAINSTORM_TOKENS = frozenset({
    "brainstorm", "brainstorming", "ideas", "idea", "imagine", "options",
    "possibilities", "concepts", "alternatives", "scenarios",
})
_BRAINSTORM_PHRASES = frozenset({
    "what if", "think of", "come up with", "lets explore", "explore options",
    "potential approaches", "creative thinking", "new ways",
})

_CREATIVE_TOKENS = frozenset({
    "poem", "poetry", "story", "logo", "artwork", "tagline", "slogan",
    "motto", "jingle", "brand", "branding", "painting", "plot", "script",
    "creative", "inspired", "catchy", "novel",
})
_CREATIVE_PHRASES = frozenset({"short story", "fun name"})

_STRATEGIC_TOKENS = frozenset({
    "plan", "strategy", "strategic", "roadmap", "approach", "prioritize",
    "prioritise", "milestones", "goals", "objectives", "timeline",
    "organize", "organise", "architecture", "phases", "sequence",
})
_STRATEGIC_PHRASES = frozenset({"long term", "next steps", "trade off"})

_UNCERTAINTY_TOKENS = frozenset({
    "maybe", "perhaps", "unsure", "uncertain", "possibly", "probably",
    "guess", "might", "doubt",
})
_UNCERTAINTY_PHRASES = frozenset({
    "not sure", "not certain", "could be", "might be", "i think", "i guess",
    "not really sure", "not confident", "i believe",
})

_FUTURE_TOKENS = frozenset({
    "predict", "prediction", "forecast", "future", "estimate", "expected",
})
_FUTURE_PHRASES = frozenset({
    "will it", "will this", "will the", "will my", "will our", "will there",
    "when will", "how long will", "going to happen", "likely to",
    "do you think will", "how will", "will happen", "next month", "next week",
    "next quarter",
})

_BRIEF_TOKENS = frozenset({"tldr", "briefly", "concisely", "brief"})
_BRIEF_PHRASES = frozenset({
    "in short", "short answer", "quick summary", "in one sentence",
    "short version", "summarize quickly", "tl dr", "summarize in one",
})

_COMMAND_VERBS = frozenset({
    "fix", "write", "create", "implement", "refactor", "add", "remove",
    "update", "change", "debug", "build", "deploy", "install", "setup",
    "configure", "generate", "convert", "migrate", "restart", "run",
    "optimize", "optimise", "review", "test", "sort", "format",
})

_DECISION_TOKENS = frozenset({
    "recommend", "recommendation", "compare", "comparison", "choose",
    "choice", "suggest", "suggestion", "opinion", "prefer", "preferred",
})
_DECISION_PHRASES = frozenset({
    "which is better", "which one", "should i", "should we", "what do you think",
    "would you", "best option", "trade off",
})

_RECALL_PHRASES = frozenset({
    "what do you remember", "recap this session", "recap the session",
    "session summary", "what happened in this session", "summarize this session",
    "summarize the session",
})


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BehaviorFeatures:
    """Fixed, deterministic feature vector for one interaction."""

    message: str
    normalized: str
    word_count: int
    is_question: bool
    is_command: bool
    decision_seeking: bool
    serious: bool
    casual: bool
    technical: bool
    brainstorming: bool
    creative: bool
    strategic: bool
    uncertainty: bool
    future_prediction: bool
    brief_request: bool
    is_greeting: bool
    is_identity_query: bool
    memory_recall: bool
    workflow_phase: str | None
    requires_approval: bool
    high_risk: bool
    sensitive: bool
    visible_memory_count: int
    first_interaction: bool


def _is_command(tokens: frozenset[str], words: list[str], normalized: str) -> bool:
    if "please" in tokens or "plz" in tokens:
        return True
    if "for me" in normalized:
        return True
    if words and words[0] in _COMMAND_VERBS:
        return True
    return False


def _phase_matches(phase: str, needles: tuple[str, ...]) -> bool:
    return any(needle in phase for needle in needles)


def extract_features(
    *,
    message: str,
    cap_context: CapContextView | None = None,
    conversation_metadata: ConversationMetadataView | None = None,
    visible_memories: list[VisibleMemory] | None = None,
    is_greeting: bool = False,
    is_identity_query: bool = False,
) -> BehaviorFeatures:
    """Extract the deterministic feature vector for one interaction."""
    context = cap_context or CapContextView()
    metadata = conversation_metadata or ConversationMetadataView()
    phase = (context.workflow_phase or "").lower().strip()

    normalized = _normalize(message)
    words = _WHITESPACE_RE.split(normalized) if normalized else []
    tokens = frozenset(words)

    technical = (
        _any_present(normalized, _TECHNICAL_TOKENS, _TECHNICAL_PHRASES)
        or bool(_EXTENSION_RE.search(message))
        or _phase_matches(
            phase, ("execution", "implementation", "coding", "build", "deploy", "debug")
        )
    )
    strategic = (
        _any_present(normalized, _STRATEGIC_TOKENS, _STRATEGIC_PHRASES)
        or _phase_matches(phase, ("plan", "strategy", "design", "architecture"))
    )
    serious = (
        _any_present(normalized, _SERIOUS_TOKENS, _SERIOUS_PHRASES)
        or _phase_matches(phase, ("recovery", "incident", "emergency"))
    )

    return BehaviorFeatures(
        message=message,
        normalized=normalized,
        word_count=len(words),
        is_question=bool(message.strip().rstrip(".").endswith("?")),
        is_command=_is_command(tokens, words, normalized),
        decision_seeking=_any_present(normalized, _DECISION_TOKENS, _DECISION_PHRASES),
        serious=serious,
        casual=_any_present(normalized, _CASUAL_TOKENS, _CASUAL_PHRASES),
        technical=technical,
        brainstorming=_any_present(
            normalized, _BRAINSTORM_TOKENS, _BRAINSTORM_PHRASES
        ),
        creative=_any_present(normalized, _CREATIVE_TOKENS, _CREATIVE_PHRASES),
        strategic=strategic,
        uncertainty=_any_present(normalized, _UNCERTAINTY_TOKENS, _UNCERTAINTY_PHRASES),
        future_prediction=_any_present(
            normalized, _FUTURE_TOKENS, _FUTURE_PHRASES
        ),
        brief_request=_any_present(normalized, _BRIEF_TOKENS, _BRIEF_PHRASES),
        is_greeting=is_greeting,
        is_identity_query=is_identity_query,
        memory_recall=context.is_memory_recall
        or any(phrase in normalized for phrase in _RECALL_PHRASES),
        workflow_phase=phase or None,
        requires_approval=context.requires_approval,
        high_risk=context.high_risk,
        sensitive=context.sensitive,
        visible_memory_count=len(visible_memories or []),
        first_interaction=metadata.session_message_count == 1,
    )
