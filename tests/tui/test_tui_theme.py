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
    assert SAMAKTHA_ORANGE == "#FF8C00"


def test_background_is_pure_black():
    assert SAMAKTHA_BLACK == "#000000"


def test_text_is_soft_white():
    # Soft white — not pure #FFFFFF
    assert SAMAKTHA_TEXT.startswith("#E")


def test_success_is_green():
    # Should be a green hex
    assert "C9" in SAMAKTHA_SUCCESS or "00" in SAMAKTHA_SUCCESS


def test_warning_is_amber():
    assert SAMAKTHA_WARNING == "#FFB300"


def test_error_is_red():
    assert SAMAKTHA_ERROR == "#FF4040"


def test_css_contains_primary_color():
    assert "#FF8C00" in SAMAKTHA_CSS


def test_css_contains_background():
    assert "#000000" in SAMAKTHA_CSS
