"""Tests for the deterministic IdentityPolicy (Phase 9.1)."""

from app.personality.identity import IdentityPolicy
from app.personality.models import IdentityIntent


def _decision(message: str):
    return IdentityPolicy().evaluate(message)


def test_who_are_you():
    decision = _decision("Who are you?")
    assert decision.is_identity_query
    assert decision.intent == IdentityIntent.WHO_ARE_YOU
    assert decision.confidence > 0


def test_who_are_you_variants():
    for message in (
        "who are you",
        "who r u",
        "who am i talking to",
        "what is your name?",
        "whats your name",
        "tell me your name",
    ):
        decision = _decision(message)
        assert decision.is_identity_query, message
        assert decision.intent == IdentityIntent.WHO_ARE_YOU, message


def test_what_are_you():
    decision = _decision("What are you?")
    assert decision.is_identity_query
    assert decision.intent == IdentityIntent.WHAT_ARE_YOU


def test_introduce_yourself():
    for message in (
        "Tell me about yourself.",
        "Introduce yourself",
        "Describe yourself",
        "Tell me about you",
    ):
        decision = _decision(message)
        assert decision.is_identity_query, message
        assert decision.intent == IdentityIntent.INTRODUCE_YOURSELF, message


def test_what_can_you_do():
    decision = _decision("What can you do?")
    assert decision.is_identity_query
    assert decision.intent == IdentityIntent.WHAT_CAN_YOU_DO


def test_what_can_you_do_variants():
    for message in (
        "what are your capabilities",
        "what do you do",
        "what can you help me with",
        "what are you capable of",
    ):
        decision = _decision(message)
        assert decision.is_identity_query, message
        assert decision.intent == IdentityIntent.WHAT_CAN_YOU_DO, message


def test_not_identity_queries():
    for message in (
        "Hi",
        "Hello",
        "What are you doing?",
        "What are you working on?",
        "What are you up to?",
        "Who are you working with?",
        "Which IDE do I use?",
        "Continue yesterday's work",
        "How are you?",
        "Please fix the bug",
    ):
        decision = _decision(message)
        assert not decision.is_identity_query, message


def test_identity_embedded_in_sentence():
    decision = _decision("Hi there, who are you?")
    assert decision.is_identity_query
    assert decision.intent == IdentityIntent.WHO_ARE_YOU


def test_empty_message():
    decision = _decision("   ")
    assert not decision.is_identity_query


def test_no_response_text():
    decision = _decision("Who are you?")
    dumped = decision.model_dump()
    assert "content" not in dumped
    assert "response" not in dumped
    assert "text" not in dumped


def test_deterministic():
    first = _decision("Who are you?")
    second = _decision("Who are you?")
    assert first == second
