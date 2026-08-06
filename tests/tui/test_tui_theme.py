"""Tests for Samaktha TUI theme constants."""

from app.tui.theme import (
    SAMAKTHA_BLACK,
    SAMAKTHA_ERROR,
    SAMAKTHA_ORANGE,
    SAMAKTHA_SUCCESS,
    SAMAKTHA_TEXT,
    SAMAKTHA_WARNING,
    SAMAKTHA_CSS,
)


def test_primary_orange_is_correct():
    assert SAMAKTHA_ORANGE == "#F59E0B"


def test_background_is_pure_black():
    # Background in Phase 6 is dark
    assert SAMAKTHA_BLACK == "#0D1117"


def test_text_is_soft_white():
    # Soft white
    assert SAMAKTHA_TEXT.startswith("#F")


def test_success_is_green():
    # Should be a green hex
    assert "C5" in SAMAKTHA_SUCCESS or "22" in SAMAKTHA_SUCCESS


def test_warning_is_amber():
    assert SAMAKTHA_WARNING == "#F59E0B"


def test_error_is_red():
    assert SAMAKTHA_ERROR == "#EF4444"


def test_css_contains_primary_color():
    assert "#F59E0B" in SAMAKTHA_CSS


def test_css_contains_background():
    assert "#0D1117" in SAMAKTHA_CSS
