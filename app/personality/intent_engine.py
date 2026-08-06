"""Phase 11.3 + 11.5 — Deterministic IntentEngine.

Classifies conversational requests into a :class:`ConversationIntent` before
the ResponseFormatter renders the answer. The formatter switches ONLY on this
intent; it never inspects raw text.

Pipeline: User -> GoalParser -> Workflow -> Runtime -> Provider ->
IntentEngine -> ResponseFormatter -> Final Output.

The IntentEngine handles conversational intents exclusively. It never touches
GoalParser task intents, CAP, GAMBIT, the workflow engine, the runtime, memory,
or the provider. Classification is pure deterministic string logic: lowercase,
punctuation removal, whitespace normalization, contraction normalization, then
exact synonym matching. No embeddings, no LLM, no fuzzy matching.

Phase 11.5 adds the COMPARISON intent and the canonical target extraction that
feeds the formatter's no-hallucination comparison policy: known external agents
map to a canonical display name; unidentifiable parties are passed through so
the formatter can answer with the uncertainty policy instead of inventing facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.personality.greeting import GreetingPolicy
from app.personality.models import ConversationIntent

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")

# Contraction/slang normalization. Longer keys are replaced first so "u're"
# wins over "u". Applied before punctuation stripping so apostrophes survive
# long enough to be expanded.
_CONTRACTION_MAP = {
    "u're": "you are",
    "ure": "you are",
    "what're": "what are",
    "what's": "what is",
    "whats": "what is",
    "who're": "who are",
    "whore": "who are",
    "who's": "who is",
    "whos": "who is",
    "how's": "how is",
    "hows": "how is",
    "i'm": "i am",
    "im": "i am",
    "you're": "you are",
    "youre": "you are",
    "can't": "can not",
    "cant": "can not",
    "cannot": "can not",
    "don't": "do not",
    "dont": "do not",
    "doesn't": "does not",
    "doesnt": "does not",
    "won't": "will not",
    "wont": "will not",
    "u": "you",
    "ur": "your",
    "r": "are",
    "ya": "you",
}

_CONTRACTION_PATTERNS = tuple(
    (re.compile(rf"\b{re.escape(key)}\b"), value)
    for key, value in sorted(_CONTRACTION_MAP.items(), key=lambda kv: -len(kv[0]))
)

# When "who/what are you" is followed by a verb the user is asking about an
# activity, not about Samaktha ("what are you doing?"). A leading word from
# this set vetoes the identity classification.
_TRAILING_DISALLOWED = frozenset({
    "doing", "working", "talking", "reading", "watching", "thinking",
    "planning", "building", "making", "creating", "writing", "testing",
    "coding", "preparing", "fixing", "waiting", "looking", "hearing",
    "playing", "learning", "studying", "listening", "designing", "editing",
    "debugging", "running", "drawing", "cooking", "wearing", "carrying",
    "holding", "driving", "typing", "saying", "intending", "trying", "going",
    "made", "capable", "able", "up", "on", "about", "for", "into",
})

# Greeting fallback: GreetingPolicy handles the common forms, but it strips
# apostrophes before matching, so contracted variants ("what's up",
# "how's it going") are detected here on the contraction-normalized text. The
# greeting must be essentially the whole message (only minor filler remains).
_GREETING_PHRASES = (
    "good morning",
    "good afternoon",
    "good evening",
    "good day",
    "how are you doing",
    "how is it going",
    "how is everything",
    "how are things",
    "what is happening",
    "how are you",
    "what is up",
    "hello",
    "hiya",
    "howdy",
    "greetings",
    "good to see you",
    "nice to meet you",
    "hey",
    "sup",
    "hola",
    "yo",
    "hi",
)

_GREETING_FILLER = frozenset({
    "there", "samaktha", "sam", "friend", "friends", "again", "you", "ya",
    "u", "mate", "dear", "everyone", "all", "then", "with", "today",
    "tonight", "guys", "folks", "amigo", "dude", "pal", "buddy", "maam",
    "sir",
})

_GOODBYE_PHRASES = (
    "goodbye",
    "good bye",
    "bye bye",
    "bye",
    "bye for now",
    "talk to you later",
    "talk to you soon",
    "talk soon",
    "see you later",
    "see you around",
    "see you",
    "catch you later",
    "catch you soon",
    "cya",
    "farewell",
    "take care",
    "so long",
    "good night",
    "ttyl",
    "peace out",
    "later",
)

_NEGATION_PHRASES = (
    "no thanks",
    "no thank you",
    "not really",
    "no way",
    "never mind",
    "definitely not",
    "i do not think so",
    "no",
    "nope",
    "nah",
    "cancel",
    "stop",
)

_THANKS_PHRASES = (
    "thank you very much",
    "thank you so much",
    "thank you kindly",
    "thanks a lot",
    "thanks a bunch",
    "thanks a million",
    "thanks",
    "thank you",
    "thx",
    "appreciated",
    "much appreciated",
    "much obliged",
    "i appreciate it",
    "i owe you one",
    "appreciate it",
    "cheers",
)

_CONFIRMATION_PHRASES = (
    "yes please",
    "yes sure",
    "sure",
    "okay",
    "ok",
    "go ahead",
    "correct",
    "that is right",
    "yes",
    "yeah",
    "yep",
    "please do",
    "do it",
)

_CAPABILITIES_PHRASES = (
    "what all things can you do",
    "what all things can u do",
    "what all can you do",
    "what are your capabilities",
    "what are your abilities",
    "what are your skills",
    "what are your strengths",
    "what are you capable of",
    "what are you capable of doing",
    "what capabilities do you have",
    "list your capabilities",
    "list your abilities",
    "what are you able to do",
    "what can you do for me",
    "what can you help me with",
    "what can you help with",
    "how can you help me",
    "tell me what you can do",
    "what do you offer",
    "what do you do",
    "what services do you offer",
    "what features do you have",
    "what are you good at",
    "what can you do",
)

_ARCHITECTURE_PHRASES = (
    "how do you work",
    "how do you function",
    "how do you operate",
    "how are you built",
    "how are you designed",
    "how are you architected",
    "how are you structured",
    "how are you organized",
    "how are you put together",
    "how does samaktha work",
    "how is your architecture",
    "what is your architecture",
    "what is your design",
    "what is your makeup",
    "what is your stack",
    "what makes you tick",
    "what is inside you",
    "what is under the hood",
    "what runs under the hood",
    "what powers you",
    "what are you made of",
    "explain your architecture",
    "explain your internals",
    "explain your inner workings",
    "explain how you work",
    "explain the architecture",
    "take me through your internals",
    "take me through internals",
)

_VERSION_PHRASES = (
    "what version of samaktha are you",
    "what version of samaktha is this",
    "what version are you",
    "what version are you running",
    "what version are you on",
    "which version are you",
    "which version is this",
    "what build are you",
    "how old are you",
    "what is your version",
    "whats your version",
    "your version",
)

_WHO_ARE_YOU_PHRASES = (
    "who exactly are you",
    "who are you really",
    "who am i talking to",
    "who am i speaking with",
    "who am i talking with",
    "what is your name",
    "whats your name",
    "what is your identity",
    "tell me your name",
    "tell me who you are",
    "do you have a name",
    "what should i call you",
    "what should i know about you",
    "may i know your name",
    "can i know your name",
    "who are you",
    "who are u",
    "who r you",
    "who r u",
    "introduce yourself",
    "introduce your self",
    "tell me about yourself",
    "tell me about you",
    "tell me a bit about yourself",
    "tell me something about yourself",
    "describe yourself",
    "describe who you are",
    "give me an introduction of yourself",
)

_CREATOR_PHRASES = (
    "who is your creator",
    "who is your developer",
    "who is your maker",
    "who is your programmer",
    "who is your boss",
    "who owns you",
    "who created samaktha",
    "who made samaktha",
    "who built samaktha",
    "who is behind samaktha",
    "who created this project",
    "who made you",
    "who built you",
    "who created you",
    "who designed you",
    "who developed you",
    "who programmed you",
)

_WHAT_ARE_YOU_PHRASES = (
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
)

_HELP_PHRASES = (
    "can you help me",
    "could you help me",
    "i need your help",
    "i need help",
    "please help",
    "help me",
    "help",
)

_HELP_FILLER = frozenset({
    "please", "now", "you", "can", "could", "maybe", "us", "me",
})

_MEMORY_RECALL_PHRASES = (
    "what did we discuss yesterday",
    "what did we discuss in the previous session",
    "what did we discuss in the last session",
    "summarize previous session",
    "summarize the previous session",
    "what were we working on",
    "continue where we left off",
    "continue previous conversation",
    "remind me what we discussed",
    "previous conversation",
    "last session",
    "what do you remember about",
    "what do you remember from",
    "what do you remember",
    "what do you remember about me",
    "what do you know about me",
    "what do you know about",
    "what do you know",
    "what have i told you",
    "what do you store about me",
    "do you remember",
    "tell me what you remember",
    "tell me what you know",
    "what do you recall",
    "recall what i told you",
    "what do you recall about",
    "what is my favorite",
    "what are my favorite",
    "what are my",
    "what is my",
)

_DELETE_MEMORY_PHRASES = (
    "delete all my memories",
    "delete all memories",
    "delete all my preferences",
    "delete my memories",
    "delete my preferences",
    "delete my memory",
    "delete my data",
    "delete that from your memory",
    "delete this session",
    "erase your memory",
    "erase your memory of",
    "erase my memory",
    "erase everything",
    "forget all my preferences",
    "forget everything",
    "forget everything about me",
    "forget my preferences",
    "forget my",
    "forget that",
    "forget about",
    "forget me",
    "clear your memory",
    "clear my memory",
    "clear my memories",
    "clear everything",
    "wipe my memory",
    "reset my memory",
    "reset my preferences",
    "remove my preferences",
    "remove my preference",
    "remove my memory",
    "remove my memories",
    "remove my",
)


# ---------------------------------------------------------------------------
# COMPARISON — Phase 11.5. Deterministic comparison detection plus target
# extraction. Comparison is only a conversational intent when at least one side
# is Samaktha ("samaktha", "you", "your") or a Samaktha-known external agent;
# otherwise it is a task ("compare file a and file b") and stays UNKNOWN so the
# GoalParser can route it as real work.
# ---------------------------------------------------------------------------

_COMPARISON_MARKERS = (
    re.compile(r"\bcompare\b"),
    re.compile(r"\bvs\b"),
    re.compile(r"\bversus\b"),
    re.compile(r"\bdifference between\b"),
    re.compile(r"\bwhich is better\b"),
    re.compile(r"\bwho is better\b"),
    re.compile(r"\bare you better than\b"),
    re.compile(r"\bbetter than\b"),
    re.compile(r"\bhow do you compare\b"),
    re.compile(r"\bhow does samaktha compare\b"),
    re.compile(r"\bhow would you compare\b"),
    re.compile(r"\bstack up against\b"),
    re.compile(r"\bhow do you stack up\b"),
)

_SAMAKTHA_SIDE_RE = re.compile(r"\bsamaktha\b|\byou\b|\byour\b|\byours\b")

# Normalized alias -> canonical display name. Lives here (the classifier) so the
# formatter never does raw-text matching of its own; the formatter receives only
# the canonical name and looks it up in its own verified-facts registry.
_KNOWN_AGENT_ALIASES = {
    "chatgpt": "ChatGPT",
    "openai": "ChatGPT",
    "open ai": "ChatGPT",
    "gpt": "ChatGPT",
    "claude": "Claude",
    "anthropic": "Claude",
    "gemini": "Gemini",
    "google": "Gemini",
    "copilot": "GitHub Copilot",
    "github copilot": "GitHub Copilot",
    "llama": "Llama",
    "meta llama": "Llama",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
}

# Words that carry no identity in a comparison sentence; stripped during
# unknown-target extraction so only the compared party remains.
_COMPARISON_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "to", "with", "vs", "versus", "of",
    "which", "who", "what", "is", "are", "am", "be", "was", "were",
    "you", "your", "yours", "me", "i", "we", "us", "samaktha", "sam",
    "better", "best", "than", "compare", "comparing", "compared",
    "difference", "between", "how", "does", "do", "would", "did",
    "stack", "up", "against", "much", "many", "think", "feel",
})


def normalize_text(text: str) -> str:
    """Normalize raw user input for deterministic matching.

    Lowercases, expands contractions, strips punctuation, collapses
    whitespace, and trims. Deterministic and idempotent.
    """
    lowered = text.lower()
    for pattern, value in _CONTRACTION_PATTERNS:
        lowered = pattern.sub(value, lowered)
    stripped = _NON_WORD_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _boundary(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(phrase)}\b")


def _phrase_patterns(phrases: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((phrase, _boundary(phrase)) for phrase in phrases)


@dataclass(frozen=True)
class IntentResult:
    """Deterministic classification result for one user message.

    Carries the ConversationIntent plus, for COMPARISON requests, the canonical
    name of the compared external agent (or None when none is identifiable).
    Pure structured data — never response text.
    """

    intent: ConversationIntent
    comparison_target: str | None = None


class IntentEngine:
    """Pure deterministic conversational-request classifier.

    A fresh instance is stateless and safe to share across requests.
    """

    def __init__(self) -> None:
        self._greeting_policy = GreetingPolicy()
        self._greeting_fallback = _phrase_patterns(_GREETING_PHRASES)
        self._goodbye = _phrase_patterns(_GOODBYE_PHRASES)
        self._negation = _phrase_patterns(_NEGATION_PHRASES)
        self._thanks = _phrase_patterns(_THANKS_PHRASES)
        self._confirmation = _phrase_patterns(_CONFIRMATION_PHRASES)
        self._capabilities = _phrase_patterns(_CAPABILITIES_PHRASES)
        self._architecture = _phrase_patterns(_ARCHITECTURE_PHRASES)
        self._version = _phrase_patterns(_VERSION_PHRASES)
        self._who_are_you = _phrase_patterns(_WHO_ARE_YOU_PHRASES)
        self._creator = _phrase_patterns(_CREATOR_PHRASES)
        self._what_are_you = _phrase_patterns(_WHAT_ARE_YOU_PHRASES)
        self._help = _phrase_patterns(_HELP_PHRASES)
        self._memory_recall = _phrase_patterns(_MEMORY_RECALL_PHRASES)
        self._delete_memory = _phrase_patterns(_DELETE_MEMORY_PHRASES)

    def classify(self, text: str) -> "ConversationIntent":
        """Classify one conversational request into a ConversationIntent."""
        normalized = normalize_text(text)
        if not normalized:
            return ConversationIntent.UNKNOWN

        if self._is_greeting(text, normalized):
            return ConversationIntent.GREETING

        for intent, patterns in (
            (ConversationIntent.GOODBYE, self._goodbye),
            (ConversationIntent.NEGATION, self._negation),
            (ConversationIntent.THANKS, self._thanks),
            (ConversationIntent.CONFIRMATION, self._confirmation),
            (ConversationIntent.CAPABILITIES, self._capabilities),
            (ConversationIntent.ARCHITECTURE, self._architecture),
            (ConversationIntent.VERSION, self._version),
            (ConversationIntent.WHO_ARE_YOU, self._who_are_you),
            (ConversationIntent.CREATOR, self._creator),
            (ConversationIntent.WHAT_ARE_YOU, self._what_are_you),
            (ConversationIntent.HELP, self._help),
            (ConversationIntent.MEMORY_RECALL, self._memory_recall),
            (ConversationIntent.DELETE_MEMORY, self._delete_memory),
        ):
            matched = self._first_match(patterns, normalized, intent)
            if matched is not None:
                return matched
        if self._is_comparison(normalized):
            return ConversationIntent.COMPARISON
        return ConversationIntent.UNKNOWN

    def classify_detailed(self, text: str) -> IntentResult:
        """Classify one request into an IntentResult.

        Like :meth:`classify`, but also extracts the canonical comparison target
        when the request is a COMPARISON. The formatter receives only the
        canonical target name — never raw text — and looks it up in its own
        verified-facts registry.
        """
        intent = self.classify(text)
        comparison_target = None
        if intent == ConversationIntent.COMPARISON:
            comparison_target = self._extract_comparison_target(normalize_text(text))
        return IntentResult(intent=intent, comparison_target=comparison_target)

    def _is_greeting(self, raw: str, normalized: str) -> bool:
        if self._greeting_policy.evaluate(raw).is_greeting:
            return True
        for _phrase, pattern in self._greeting_fallback:
            match = pattern.search(normalized)
            if not match:
                continue
            rest = (normalized[: match.start()] + " " + normalized[match.end():]).strip()
            if not rest or set(_WHITESPACE_RE.split(rest)).issubset(_GREETING_FILLER):
                return True
        return False

    def _is_comparison(self, normalized: str) -> bool:
        """Comparison markers plus a Samaktha side (or a known external agent)."""
        if not any(marker.search(normalized) for marker in _COMPARISON_MARKERS):
            return False
        mentions_samaktha = _SAMAKTHA_SIDE_RE.search(normalized) is not None
        mentions_known_agent = any(
            _boundary(alias).search(normalized) for alias in _KNOWN_AGENT_ALIASES
        )
        return mentions_samaktha or mentions_known_agent

    def _extract_comparison_target(self, normalized: str) -> str | None:
        """Return the canonical name of the compared agent, or None.

        Known agents win first (longest alias first so "github copilot" beats
        "copilot"). Otherwise the compared party is recovered by removing
        comparison stopwords; only the first two meaningful tokens are kept so a
        conversational fragment never bleeds into the response.
        """
        for alias in sorted(_KNOWN_AGENT_ALIASES, key=len, reverse=True):
            if _boundary(alias).search(normalized):
                return _KNOWN_AGENT_ALIASES[alias]
        remaining = [
            token
            for token in _WHITESPACE_RE.split(normalized)
            if token not in _COMPARISON_STOPWORDS
        ]
        if not remaining:
            return None
        return " ".join(remaining[:2])

    def _first_match(self, patterns, normalized, intent) -> ConversationIntent | None:
        for _phrase, pattern in patterns:
            match = pattern.search(normalized)
            if not match:
                continue
            if intent in (ConversationIntent.WHO_ARE_YOU, ConversationIntent.WHAT_ARE_YOU):
                remainder = (normalized[: match.start()] + " " + normalized[match.end():]).strip()
                if remainder and _WHITESPACE_RE.split(remainder, 1)[0] in _TRAILING_DISALLOWED:
                    continue
            if intent == ConversationIntent.HELP:
                remainder = (normalized[: match.start()] + " " + normalized[match.end():]).strip()
                if remainder:
                    words = _WHITESPACE_RE.split(remainder)
                    if not set(words).issubset(_HELP_FILLER):
                        continue
            return intent
        return None


_DEFAULT_ENGINE = IntentEngine()


def classify_input(text: str) -> ConversationIntent:
    """Classify raw input using the default IntentEngine instance."""
    return _DEFAULT_ENGINE.classify(text)
