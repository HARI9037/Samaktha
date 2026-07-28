"""Tests for Phase 6.5 Personality Profiles."""

from app.agent.personality_profiles import (
    ALL_PROFILES,
    PersonalityProfile,
    PersonalityProfileManager,
    PROFILE_CORE,
    PROFILE_ASSISTANT,
    PROFILE_EXPERT,
)


def test_all_profiles_are_personality_profile():
    for key, profile in ALL_PROFILES.items():
        assert isinstance(profile, PersonalityProfile), f"{key} is not a PersonalityProfile"


def test_all_profiles_have_required_fields():
    required = ["greeting", "thinking_label", "completion_label",
                "approval_prompt", "error_label", "idle_label"]
    for key, profile in ALL_PROFILES.items():
        for field in required:
            value = getattr(profile, field)
            assert isinstance(value, str) and len(value) > 0, \
                f"Profile '{key}' missing or empty field '{field}'"


def test_profile_manager_defaults_to_core():
    mgr = PersonalityProfileManager()
    assert mgr.active == PROFILE_CORE


def test_profile_manager_switch():
    mgr = PersonalityProfileManager()
    assert mgr.set_profile("assistant") is True
    assert mgr.active == PROFILE_ASSISTANT


def test_profile_manager_switch_expert():
    mgr = PersonalityProfileManager()
    mgr.set_profile("expert")
    assert mgr.active == PROFILE_EXPERT


def test_profile_manager_invalid_key():
    mgr = PersonalityProfileManager()
    result = mgr.set_profile("nonexistent_profile")
    assert result is False
    assert mgr.active == PROFILE_CORE  # Still on default


def test_profile_manager_list_profiles():
    mgr = PersonalityProfileManager()
    profiles = mgr.list_profiles()
    assert "core" in profiles
    assert "assistant" in profiles
    assert "expert" in profiles


def test_no_backend_in_profiles():
    """Profiles must be pure data — no execution, planning, or reasoning fields."""
    for key, profile in ALL_PROFILES.items():
        profile_dict = profile._asdict()
        forbidden_keys = ["execute", "plan", "reason", "tool", "chain", "memory"]
        for field in profile_dict:
            for forbidden in forbidden_keys:
                assert forbidden not in field, \
                    f"Profile '{key}' has a suspicious field: '{field}'"
