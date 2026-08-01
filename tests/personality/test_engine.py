"""Tests for the deterministic PersonalityEngine facade (Phase 9.1)."""

from app.personality import PersonalityEngine
from app.personality.models import IdentityIntent

FORBIDDEN_PROVIDER_IDENTITIES = (
    "AI language model",
    "I am an AI",
    "ChatGPT",
    "Claude",
    "OpenAI",
    "Gemini",
    "LLM",
)


def test_evaluate_identity_query():
    result = PersonalityEngine().evaluate("Who are you?")
    assert result.identity.is_identity_query
    assert result.identity.intent == IdentityIntent.WHO_ARE_YOU
    assert not result.greeting.is_greeting
    assert result.profile.name == "Samaktha"


def test_evaluate_greeting():
    result = PersonalityEngine().evaluate("Hi")
    assert result.greeting.is_greeting
    assert not result.identity.is_identity_query


def test_evaluate_what_can_you_do():
    result = PersonalityEngine().evaluate("What can you do?")
    assert result.identity.is_identity_query
    assert result.identity.intent == IdentityIntent.WHAT_CAN_YOU_DO


def test_profile_fields_are_structured_data():
    profile = PersonalityEngine().profile
    assert profile.name == "Samaktha"
    assert profile.mission.strip()
    assert profile.description.strip()
    assert profile.capabilities
    assert profile.limitations
    assert profile.philosophy.strip()


def test_profile_never_mentions_provider_identity():
    profile = PersonalityEngine().profile
    text = profile.model_dump_json().lower()
    for forbidden in FORBIDDEN_PROVIDER_IDENTITIES:
        assert forbidden.lower() not in text, forbidden


def test_evaluation_has_no_provider_fields():
    result = PersonalityEngine().evaluate("Who are you?")
    flat = str(result.model_dump()).lower()
    for field in ("provider", "model_id", "prompt", "response"):
        assert field not in flat, field


def test_deterministic():
    engine = PersonalityEngine()
    assert engine.evaluate("Who are you?") == engine.evaluate("Who are you?")
    assert engine.evaluate("Hi") == engine.evaluate("Hi")
