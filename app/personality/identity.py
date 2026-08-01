"""Phase 9.1 — Deterministic IdentityPolicy.

Classifies whether the user is asking about Samaktha itself. Pure
deterministic string logic; never generates prompts or response text.
"""

from __future__ import annotations

import re

from app.personality.models import IdentityDecision, IdentityIntent

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")

# Phrases are checked in order; the first match wins. More specific groups
# come first so broader phrases cannot shadow them.
_IDENTITY_PHRASES: tuple[tuple[IdentityIntent, tuple[str, ...]], ...] = (
    (IdentityIntent.INTRODUCE_YOURSELF, (
        "introduce yourself",
        "introduce your self",
        "tell me about yourself",
        "tell me about you",
        "tell me a bit about yourself",
        "tell me something about yourself",
        "describe yourself",
        "describe who you are",
        "give me an introduction of yourself",
        "what should i know about you",
    )),
    (IdentityIntent.WHAT_CAN_YOU_DO, (
        "what can you do",
        "what can u do",
        "what can you help me with",
        "what can you help with",
        "what do you do",
        "what are your capabilities",
        "what are you capable of",
        "what are you able to do",
        "what capabilities do you have",
        "what are your abilities",
        "list your capabilities",
        "your capabilities",
        "your abilities",
    )),
    (IdentityIntent.WHO_ARE_YOU, (
        "who are you",
        "who are u",
        "who r you",
        "who r u",
        "who exactly are you",
        "who are you really",
        "who am i talking to",
        "what is your name",
        "whats your name",
        "what is ur name",
        "tell me your name",
        "may i know your name",
        "can i know your name",
    )),
    (IdentityIntent.WHAT_ARE_YOU, (
        "what are you",
        "what are u",
        "what r you",
        "what r u",
        "are you a robot",
        "are you a bot",
        "are you an ai",
        "are you an ai bot",
        "are you a chatbot",
        "are you a machine",
        "are you a human",
        "are you an assistant",
        "are you real",
    )),
)

# When "who/what are you" is followed by a verb, the user is asking about an
# activity, not about Samaktha ("what are you doing?", "who are you talking
# to?"). A leading word from this set vetoes identity detection.
_TRAILING_DISALLOWED = frozenset({
    "doing", "working", "talking", "reading", "watching", "thinking",
    "planning", "building", "making", "creating", "writing", "testing",
    "coding", "preparing", "fixing", "waiting", "looking", "hearing",
    "playing", "learning", "studying", "listening", "designing", "editing",
    "debugging", "running", "drawing", "cooking", "wearing", "carrying",
    "holding", "driving", "typing", "saying", "intending", "trying", "going",
    "up", "on", "about", "for", "into",
})


def _normalize(message: str) -> str:
    text = message.lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _leading_word(text: str) -> str:
    if not text:
        return ""
    return _WHITESPACE_RE.split(text, 1)[0]


class IdentityPolicy:
    """Pure deterministic identity-query classifier."""

    def evaluate(self, message: str) -> IdentityDecision:
        normalized = _normalize(message)
        if not normalized:
            return IdentityDecision(is_identity_query=False, confidence=0.0)
        for intent, phrases in _IDENTITY_PHRASES:
            for phrase in phrases:
                if phrase not in normalized:
                    continue
                if intent in (IdentityIntent.WHAT_ARE_YOU, IdentityIntent.WHO_ARE_YOU):
                    remainder = normalized.replace(phrase, " ", 1).strip()
                    if _leading_word(remainder) in _TRAILING_DISALLOWED:
                        return IdentityDecision(is_identity_query=False, confidence=0.0)
                word_count = len(normalized.split())
                phrase_words = len(phrase.split())
                confidence = 1.0 if word_count <= phrase_words + 2 else 0.9
                return IdentityDecision(
                    is_identity_query=True,
                    intent=intent,
                    matched_phrase=phrase,
                    confidence=confidence,
                )
        return IdentityDecision(is_identity_query=False, confidence=0.0)
