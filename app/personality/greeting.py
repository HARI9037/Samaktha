"""Phase 9.1 — Deterministic GreetingPolicy.

Detects pure greetings (standalone or followed only by minor filler/name).
Produces a structured GreetingDecision with no response text.
"""

from __future__ import annotations

import re

from app.personality.models import GreetingDecision, GreetingKind

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")

# Patterns are checked in order; the first match wins. Longer variants must
# precede shorter ones ("how are you doing" before "how are you").
_GREETING_PATTERNS: tuple[tuple[GreetingKind, re.Pattern[str]], ...] = (
    (GreetingKind.GOOD_MORNING, re.compile(r"\bgood morning\b")),
    (GreetingKind.GOOD_AFTERNOON, re.compile(r"\bgood afternoon\b")),
    (GreetingKind.GOOD_EVENING, re.compile(r"\bgood evening\b")),
    (GreetingKind.GENERIC, re.compile(r"\bgood day\b")),
    (GreetingKind.HELLO, re.compile(r"\bhello\b")),
    (GreetingKind.HI, re.compile(r"\bhi\b")),
    (GreetingKind.HEY, re.compile(r"\bhey\b")),
    (GreetingKind.GENERIC, re.compile(r"\bhiya\b|\bhowdy\b|\bgreetings\b|\byo\b")),
    (GreetingKind.WHATS_UP, re.compile(r"\bwhats up\b|\bwhat's up\b|\bsup\b")),
    (GreetingKind.HOW_ARE_YOU, re.compile(r"\bhow are you doing\b|\bhow r u doing\b|\bhow are u doing\b")),
    (GreetingKind.HOW_ARE_YOU, re.compile(r"\bhow are you\b|\bhow r u\b|\bhow r you\b|\bhow are u\b")),
    (GreetingKind.HOW_ARE_YOU, re.compile(r"\bhow's it going\b|\bhows it going\b|\bhow is it going\b")),
)

_FILLER_WORDS = frozenset({
    "there", "samaktha", "sam", "friend", "friends", "everyone", "all",
    "mate", "dear", "again", "you", "ya", "u", "mr", "mrs", "ms", "sir",
    "maam", "madam", "boss", "chief", "guys", "folks", "hi", "hello", "hey",
    "how", "are", "doing", "it", "going", "is",
})

_FILLER_PHRASES = frozenset({
    "how are you", "how are you doing", "how's it going", "hows it going",
    "how is it going", "whats up", "what's up", "how r u", "how r you",
    "how are u",
})


def _normalize(message: str) -> str:
    text = message.lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


class GreetingPolicy:
    """Pure deterministic greeting classifier."""

    def evaluate(self, message: str) -> GreetingDecision:
        normalized = _normalize(message)
        if not normalized:
            return GreetingDecision(is_greeting=False, confidence=0.0)
        for kind, pattern in _GREETING_PATTERNS:
            match = pattern.search(normalized)
            if not match:
                continue
            rest = (normalized[: match.start()] + " " + normalized[match.end():]).strip()
            if not rest:
                return GreetingDecision(
                    is_greeting=True,
                    kind=kind,
                    matched_phrase=match.group(0),
                    confidence=1.0,
                )
            if rest in _FILLER_PHRASES:
                return GreetingDecision(
                    is_greeting=True,
                    kind=kind,
                    matched_phrase=match.group(0),
                    confidence=0.95,
                )
            rest_words = set(_WHITESPACE_RE.split(rest))
            if rest_words and rest_words.issubset(_FILLER_WORDS):
                return GreetingDecision(
                    is_greeting=True,
                    kind=kind,
                    matched_phrase=match.group(0),
                    confidence=0.95,
                )
            # A greeting followed by real content ("hi, fix the bug") is not a
            # pure greeting turn.
            return GreetingDecision(is_greeting=False, confidence=0.0)
        return GreetingDecision(is_greeting=False, confidence=0.0)
