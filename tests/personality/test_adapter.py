"""Tests for the temporary Phase 9.1 identity adapter."""

from app.personality import (
    SAMAKTHA_IDENTITY_PROFILE,
    IdentityProfile,
    identity_to_provider_context,
)


def test_adapter_renders_identity_header():
    text = identity_to_provider_context(SAMAKTHA_IDENTITY_PROFILE)
    assert "You are Samaktha." in text


def test_adapter_renders_every_profile_field():
    profile = SAMAKTHA_IDENTITY_PROFILE
    text = identity_to_provider_context(profile)
    assert "Mission:" in text and profile.mission in text
    assert "Description:" in text and profile.description in text
    assert "Capabilities:" in text
    for capability in profile.capabilities:
        assert f"- {capability}" in text
    assert "Limitations:" in text
    for limitation in profile.limitations:
        assert f"- {limitation}" in text
    assert "Philosophy:" in text and profile.philosophy in text


def test_adapter_never_mentions_provider_identity():
    text = identity_to_provider_context(SAMAKTHA_IDENTITY_PROFILE).lower()
    for forbidden in ("ai language model", "i am an ai", "chatgpt", "claude", "openai", "gemini"):
        assert forbidden not in text, forbidden


def test_adapter_is_deterministic():
    first = identity_to_provider_context(SAMAKTHA_IDENTITY_PROFILE)
    second = identity_to_provider_context(SAMAKTHA_IDENTITY_PROFILE)
    assert first == second


def test_adapter_custom_profile():
    profile = IdentityProfile(
        name="Unit",
        mission="a mission",
        description="a description",
        capabilities=["cap one", "cap two"],
        limitations=["lim one"],
        philosophy="a philosophy",
    )
    text = identity_to_provider_context(profile)
    assert "You are Unit." in text
    assert "- cap one" in text
    assert "- cap two" in text
    assert "- lim one" in text
