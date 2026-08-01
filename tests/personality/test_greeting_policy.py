"""Tests for the deterministic GreetingPolicy (Phase 9.1)."""

from app.personality.greeting import GreetingPolicy
from app.personality.models import GreetingKind


def _decision(message: str):
    return GreetingPolicy().evaluate(message)


def test_pure_greetings():
    cases = {
        "Hi": GreetingKind.HI,
        "Hello": GreetingKind.HELLO,
        "Hey": GreetingKind.HEY,
        "Good morning": GreetingKind.GOOD_MORNING,
        "Good evening": GreetingKind.GOOD_EVENING,
    }
    for message, expected_kind in cases.items():
        decision = _decision(message)
        assert decision.is_greeting, message
        assert decision.kind == expected_kind, message


def test_greeting_with_name_or_filler():
    for message in (
        "Hello Samaktha",
        "Hi there",
        "hey everyone",
        "good morning samaktha",
        "Hello, how are you?",
        "how are you doing",
        "whats up",
    ):
        decision = _decision(message)
        assert decision.is_greeting, message


def test_greeting_followed_by_content_is_not_pure_greeting():
    for message in (
        "Hello, please fix the bug.",
        "Hi, can you help me with this task?",
        "Good morning, what is the weather?",
    ):
        decision = _decision(message)
        assert not decision.is_greeting, message


def test_non_greetings():
    for message in (
        "Who are you?",
        "What can you do?",
        "Fix the bug",
        "Continue yesterday's work",
        "",
    ):
        decision = _decision(message)
        assert not decision.is_greeting, message


def test_no_response_text():
    decision = _decision("Hi")
    dumped = decision.model_dump()
    assert "content" not in dumped
    assert "response" not in dumped
    assert "text" not in dumped


def test_deterministic():
    assert _decision("Hi") == _decision("Hi")
