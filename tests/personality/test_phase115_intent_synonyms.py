"""Phase 11.5 — IntentEngine synonym-expansion and comparison regression tests.

Verifies the Phase 11.5 intent-coverage guarantees:
    - the expanded synonym tables resolve to the same enum value
    - normalization survives punctuation, capitalization, extra whitespace, and
      contractions for every intent family
    - every ConversationIntent value is reachable through its routing phrases
    - COMPARISON detects Samaktha-vs-external comparisons and extracts the
      canonical target, while file/task comparisons stay UNKNOWN
    - classify_detailed returns a structured IntentResult with a target only for
      COMPARISON
"""

from app.personality import IntentEngine
from app.personality.models import ConversationIntent

ENGINE = IntentEngine()


def classify(text: str) -> ConversationIntent:
    return ENGINE.classify(text)


def detailed(text: str):
    return ENGINE.classify_detailed(text)


def assert_all(intent: ConversationIntent, phrases: list[str]) -> None:
    for phrase in phrases:
        assert classify(phrase) == intent, f"{phrase!r} -> {classify(phrase)!r}"


# ---------------------------------------------------------------------------
# Expanded synonym tables (Part 1)
# ---------------------------------------------------------------------------


def test_expanded_greeting_synonyms():
    assert_all(ConversationIntent.GREETING, [
        "hiya",
        "howdy",
        "yo",
        "hola",
        "hey there",
        "good to see you",
        "nice to meet you",
        "how is everything",
        "how are things",
        "whats happening",
        "hello amigo",
        "greetings, pal",
    ])


def test_expanded_capabilities_synonyms():
    assert_all(ConversationIntent.CAPABILITIES, [
        "what all can you do",
        "what are your skills",
        "what are your strengths",
        "what are you capable of doing",
        "what can you do for me",
        "tell me what you can do",
        "what services do you offer",
        "what features do you have",
        "what are you good at",
    ])


def test_expanded_identity_synonyms():
    assert_all(ConversationIntent.WHO_ARE_YOU, [
        "what is your identity",
        "tell me who you are",
        "do you have a name",
        "what should i call you",
        "who am i speaking with",
    ])


def test_expanded_creator_synonyms():
    assert_all(ConversationIntent.CREATOR, [
        "who is your boss",
        "who owns you",
        "who made samaktha",
        "who built samaktha",
        "who is behind samaktha",
        "who created this project",
        "who is your programmer",
    ])


def test_expanded_version_synonyms():
    assert_all(ConversationIntent.VERSION, [
        "what version are you running",
        "what version are you on",
        "which version is this",
        "what build are you",
        "how old are you",
    ])


def test_expanded_architecture_synonyms():
    assert_all(ConversationIntent.ARCHITECTURE, [
        "what makes you tick",
        "what is inside you",
        "how are you put together",
        "what runs under the hood",
        "what is under the hood",
        "what is your stack",
        "what powers you",
        "how are you organized",
        "explain how you work",
    ])


def test_expanded_memory_recall_synonyms():
    assert_all(ConversationIntent.MEMORY_RECALL, [
        "what have i told you",
        "what do you remember about me",
        "what do you store about me",
        "recall what i told you",
        "what do you recall about acme",
    ])


def test_expanded_delete_memory_synonyms():
    assert_all(ConversationIntent.DELETE_MEMORY, [
        "wipe my memory",
        "reset my memory",
        "erase everything",
        "delete my data",
        "forget me",
        "forget everything about me",
        "clear everything",
        "reset my preferences",
    ])


def test_expanded_goodbye_synonyms():
    assert_all(ConversationIntent.GOODBYE, [
        "catch you later",
        "catch you soon",
        "talk to you soon",
        "talk soon",
        "see you around",
        "peace out",
        "ttyl",
        "good night",
        "bye for now",
        "so long",
    ])


def test_expanded_thanks_synonyms():
    assert_all(ConversationIntent.THANKS, [
        "cheers",
        "thanks a bunch",
        "thanks a million",
        "thank you kindly",
        "i appreciate it",
        "much obliged",
        "i owe you one",
    ])


# ---------------------------------------------------------------------------
# Normalization survives punctuation / casing / whitespace / contractions
# ---------------------------------------------------------------------------


def test_normalization_variants_for_each_family():
    expectations = {
        ConversationIntent.GREETING: "WHAT'S   up?!",
        ConversationIntent.GOODBYE: "Catch ya later!",
        ConversationIntent.CAPABILITIES: "What ALL things can YOU do??",
        ConversationIntent.ARCHITECTURE: "What makes you tick?!",
        ConversationIntent.VERSION: "Which VERSION are you?",
        ConversationIntent.WHO_ARE_YOU: "Who're you?!",
        ConversationIntent.CREATOR: "Who MADE you?",
        ConversationIntent.WHAT_ARE_YOU: "What're you?!",
        ConversationIntent.MEMORY_RECALL: "What do you REMEMBER about ACME?",
        ConversationIntent.DELETE_MEMORY: "Please  WIPE  my memory!!",
        ConversationIntent.THANKS: "Thank   you,  SO much!",
        ConversationIntent.COMPARISON: "Compare samaktha to ChatGPT!!",
    }
    for intent, variant in expectations.items():
        assert classify(variant) == intent, f"{variant!r} -> {classify(variant)!r}"


def test_contraction_variants():
    assert classify("what're you") == ConversationIntent.WHAT_ARE_YOU
    assert classify("whats up") == ConversationIntent.GREETING
    assert classify("u r amazing, thanks") == ConversationIntent.THANKS
    assert classify("i'm curious who built you") == ConversationIntent.CREATOR


# ---------------------------------------------------------------------------
# Routing: every ConversationIntent value is reachable
# ---------------------------------------------------------------------------


def test_every_conversation_intent_is_reachable():
    routes = {
        ConversationIntent.UNKNOWN: "refactor parser.py",
        ConversationIntent.GREETING: "hi",
        ConversationIntent.GOODBYE: "bye",
        ConversationIntent.WHO_ARE_YOU: "who are you",
        ConversationIntent.WHAT_ARE_YOU: "what are you",
        ConversationIntent.CREATOR: "who made you",
        ConversationIntent.CAPABILITIES: "what can you do",
        ConversationIntent.HELP: "help",
        ConversationIntent.MEMORY_RECALL: "what do you remember",
        ConversationIntent.DELETE_MEMORY: "forget everything",
        ConversationIntent.ARCHITECTURE: "how do you work",
        ConversationIntent.VERSION: "what version are you",
        ConversationIntent.THANKS: "thanks",
        ConversationIntent.CONFIRMATION: "yes",
        ConversationIntent.NEGATION: "no",
        ConversationIntent.COMPARISON: "samaktha vs chatgpt",
    }
    assert set(routes) == set(ConversationIntent), "routing table is not exhaustive"
    for intent, phrase in routes.items():
        assert classify(phrase) == intent, f"{phrase!r} -> {classify(phrase)!r}"


# ---------------------------------------------------------------------------
# COMPARISON detection and target extraction (Part 2)
# ---------------------------------------------------------------------------


def test_comparison_with_known_agent():
    assert classify("compare samaktha to chatgpt") == ConversationIntent.COMPARISON
    assert classify("samaktha vs claude") == ConversationIntent.COMPARISON
    assert classify("are you better than gemini") == ConversationIntent.COMPARISON
    assert classify("how does samaktha compare to copilot") == ConversationIntent.COMPARISON
    assert classify("which is better chatgpt or claude") == ConversationIntent.COMPARISON


def test_comparison_extracts_canonical_known_target():
    cases = {
        "compare samaktha to chatgpt": "ChatGPT",
        "samaktha vs openai": "ChatGPT",
        "claude versus samaktha": "Claude",
        "are you better than anthropic": "Claude",
        "which is better google or samaktha": "Gemini",
        "samaktha vs github copilot": "GitHub Copilot",
        "compare samaktha and mistral": "Mistral",
        "are you better than deepseek": "DeepSeek",
    }
    for phrase, expected in cases.items():
        result = detailed(phrase)
        assert result.intent == ConversationIntent.COMPARISON, phrase
        assert result.comparison_target == expected, phrase


def test_comparison_with_unknown_agent_keeps_target_for_uncertainty():
    result = detailed("compare samaktha to bazbo corp")
    assert result.intent == ConversationIntent.COMPARISON
    assert result.comparison_target == "bazbo corp"


def test_comparison_without_identifiable_target():
    result = detailed("how does samaktha compare")
    assert result.intent == ConversationIntent.COMPARISON
    assert result.comparison_target is None


def test_file_comparison_is_not_conversational():
    assert classify("compare file a and file b") == ConversationIntent.UNKNOWN
    assert classify("compare the two documents") == ConversationIntent.UNKNOWN
    assert classify("what is the difference between these folders") == ConversationIntent.UNKNOWN


def test_comparison_detection_is_deterministic():
    first = detailed("Compare samaktha to ChatGPT!")
    second = detailed("Compare samaktha to ChatGPT!")
    assert first == second
    assert first.intent == ConversationIntent.COMPARISON
    assert first.comparison_target == "ChatGPT"


def test_classify_detailed_is_pure_for_non_comparison():
    for phrase in ("hello", "what can you do", "refactor parser.py"):
        result = detailed(phrase)
        assert result.comparison_target is None, phrase
        assert result.intent == classify(phrase), phrase
