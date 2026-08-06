"""Phase 11.3 — IntentEngine acceptance tests.

Verifies the deterministic conversational-request classifier:
    - every specified synonym for each intent resolves to the same enum value
    - punctuation, mixed casing, extra whitespace, and contractions all
      normalize away
    - "who are you" and "what are you" stay distinct intents
    - "what all things can you do" classifies as CAPABILITIES
    - activity questions ("what are you doing?") never classify as identity
    - unrecognized input classifies as UNKNOWN
    - the classifier is pure and deterministic
"""

from app.personality import IntentEngine, normalize_text
from app.personality.models import ConversationIntent

ENGINE = IntentEngine()


def classify(text: str) -> ConversationIntent:
    return ENGINE.classify(text)


def assert_all(intent: ConversationIntent, phrases: list[str]) -> None:
    for phrase in phrases:
        assert classify(phrase) == intent, f"{phrase!r} -> {classify(phrase)!r}"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize_text("  WHAT   can   you DO  ") == "what can you do"


def test_normalize_strips_punctuation():
    assert normalize_text("what can you do?!?") == "what can you do"
    assert normalize_text("Hello, world!") == "hello world"


def test_normalize_expands_contractions():
    assert normalize_text("what're you") == "what are you"
    assert normalize_text("i'm samaktha") == "i am samaktha"
    assert normalize_text("what can u do") == "what can you do"


def test_normalize_is_idempotent():
    once = normalize_text("WHAT'RE you doin'??")
    assert normalize_text(once) == once


# ---------------------------------------------------------------------------
# GREETING
# ---------------------------------------------------------------------------


def test_greeting_synonyms():
    assert_all(ConversationIntent.GREETING, [
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "good day",
        "how are you",
        "how r u",
        "whats up",
        "what's up",
        "sup",
        "hi there",
        "hello samaktha",
        "hey again",
    ])


def test_greeting_with_real_content_is_not_a_greeting():
    assert classify("hi, fix the bug") == ConversationIntent.UNKNOWN


def test_greeting_mixed_casing_and_punctuation():
    assert classify("HeLlO?!") == ConversationIntent.GREETING
    assert classify("GOOD MORNING,   friend") == ConversationIntent.GREETING


# ---------------------------------------------------------------------------
# GOODBYE
# ---------------------------------------------------------------------------


def test_goodbye_synonyms():
    assert_all(ConversationIntent.GOODBYE, [
        "bye",
        "goodbye",
        "good bye",
        "bye bye",
        "see you",
        "see you later",
        "see ya",
        "talk to you later",
        "farewell",
        "take care",
        "later",
    ])


# ---------------------------------------------------------------------------
# THANKS / CONFIRMATION / NEGATION
# ---------------------------------------------------------------------------


def test_thanks_synonyms():
    assert_all(ConversationIntent.THANKS, [
        "thanks",
        "thank you",
        "thank you so much",
        "thanks a lot",
        "thx",
        "much appreciated",
    ])


def test_confirmation_synonyms():
    assert_all(ConversationIntent.CONFIRMATION, [
        "yes",
        "yeah",
        "yep",
        "sure",
        "ok",
        "okay",
        "go ahead",
        "correct",
        "do it",
    ])


def test_negation_synonyms():
    assert_all(ConversationIntent.NEGATION, [
        "no",
        "nope",
        "nah",
        "not really",
        "no thanks",
        "cancel",
        "stop",
        "never mind",
    ])


# ---------------------------------------------------------------------------
# WHO_ARE_YOU vs WHAT_ARE_YOU vs CREATOR
# ---------------------------------------------------------------------------


def test_who_are_you_synonyms():
    assert_all(ConversationIntent.WHO_ARE_YOU, [
        "who are you",
        "who are u",
        "who r you",
        "who r u",
        "who exactly are you",
        "who are you really",
        "who am i talking to",
        "what is your name",
        "whats your name",
        "tell me your name",
        "may i know your name",
    ])


def test_who_are_you_introductions():
    assert_all(ConversationIntent.WHO_ARE_YOU, [
        "introduce yourself",
        "tell me about yourself",
        "describe yourself",
        "what should i know about you",
    ])


def test_creator_synonyms():
    assert_all(ConversationIntent.CREATOR, [
        "who made you",
        "who built you",
        "who created you",
        "who designed you",
        "who developed you",
        "who is your creator",
        "who is your maker",
    ])


def test_what_are_you_synonyms():
    assert_all(ConversationIntent.WHAT_ARE_YOU, [
        "what are you",
        "what are u",
        "what r you",
        "what r u",
        "are you a robot",
        "are you a bot",
        "are you an ai",
        "are you a chatbot",
        "are you a machine",
        "are you a human",
        "are you an assistant",
        "are you real",
    ])


def test_who_are_you_and_what_are_you_are_distinct():
    assert classify("who are you") == ConversationIntent.WHO_ARE_YOU
    assert classify("what are you") == ConversationIntent.WHAT_ARE_YOU


def test_identity_with_trailing_activity_is_not_identity():
    assert classify("what are you doing") == ConversationIntent.UNKNOWN
    assert classify("who are you going to call") == ConversationIntent.UNKNOWN
    assert classify("what are you working on") == ConversationIntent.UNKNOWN


def test_what_are_you_made_of_is_architecture():
    assert classify("what are you made of") == ConversationIntent.ARCHITECTURE


# ---------------------------------------------------------------------------
# CAPABILITIES and HELP
# ---------------------------------------------------------------------------


def test_capabilities_synonyms():
    assert_all(ConversationIntent.CAPABILITIES, [
        "what can you do",
        "what can u do",
        "what all can you do",
        "what all things can you do",
        "what all things can u do",
        "what are your capabilities",
        "what are your abilities",
        "what are you capable of",
        "what are you able to do",
        "what capabilities do you have",
        "list your capabilities",
        "list your abilities",
        "what do you do",
        "what can you help me with",
        "what can you help with",
        "how can you help me",
    ])


def test_what_all_things_can_you_do_is_capabilities():
    assert classify("what all things can you do") == ConversationIntent.CAPABILITIES
    assert classify("what all things can you do??") == ConversationIntent.CAPABILITIES
    assert classify("WHAT ALL THINGS CAN YOU DO") == ConversationIntent.CAPABILITIES


def test_help_synonyms():
    assert_all(ConversationIntent.HELP, [
        "help",
        "help me",
        "help me please",
        "can you help me",
        "could you help me",
        "i need help",
        "i need your help",
        "please help",
    ])


def test_help_with_real_content_is_not_help():
    assert classify("help me fix the bug") == ConversationIntent.UNKNOWN


# ---------------------------------------------------------------------------
# MEMORY_RECALL and DELETE_MEMORY
# ---------------------------------------------------------------------------


def test_memory_recall_synonyms():
    assert_all(ConversationIntent.MEMORY_RECALL, [
        "what do you remember",
        "what do you remember about acme",
        "do you remember",
        "what do you know",
        "what do you know about me",
        "what is my favorite ide",
        "what are my preferences",
    ])


def test_delete_memory_synonyms():
    assert_all(ConversationIntent.DELETE_MEMORY, [
        "forget my IDE preference",
        "forget everything",
        "forget all my preferences",
        "forget my preferences",
        "forget that",
        "delete my memory",
        "delete all my memories",
        "delete all my preferences",
        "delete this session",
        "erase your memory",
        "please erase my memory",
        "clear your memory",
        "clear my memory",
        "remove my preferences",
        "remove my tool preference",
    ])


def test_tool_delete_is_not_memory_delete():
    assert classify("delete that file") == ConversationIntent.UNKNOWN
    assert classify("delete the logs") == ConversationIntent.UNKNOWN


# ---------------------------------------------------------------------------
# ARCHITECTURE and VERSION
# ---------------------------------------------------------------------------


def test_architecture_synonyms():
    assert_all(ConversationIntent.ARCHITECTURE, [
        "how do you work",
        "how do you function",
        "how do you operate",
        "how are you built",
        "how are you designed",
        "how are you architected",
        "how does samaktha work",
        "what is your architecture",
        "explain your architecture",
        "explain your internals",
        "take me through your internals",
    ])


def test_version_synonyms():
    assert_all(ConversationIntent.VERSION, [
        "what version are you",
        "which version are you",
        "what is your version",
        "what version of samaktha are you",
        "your version",
    ])


# ---------------------------------------------------------------------------
# UNKNOWN and determinism
# ---------------------------------------------------------------------------


def test_unknown_inputs():
    assert_all(ConversationIntent.UNKNOWN, [
        "",
        "   ",
        "refactor parser.py",
        "list the desktop contents",
        "open the file",
        "what is 2 plus 2",
        "please write a unit test",
        "who is the president",
    ])


def test_classifier_is_pure_and_deterministic():
    sample = "What ALL things Can You Do??"
    first = classify(sample)
    second = classify(sample)
    assert first == second == ConversationIntent.CAPABILITIES
