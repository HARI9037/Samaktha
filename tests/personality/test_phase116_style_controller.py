"""Phase 11.6 — deterministic StyleController (wording variation, Part 5).

Verifies the Phase 11.6 wording-variation guarantees:
    - greeting variation rotates deterministically by turn
    - uncertainty, recall-preamble, and closing variation rotate deterministically
    - the first turn (and ``turn=None``) always yield the canonical base text,
      so legacy outputs never change
    - duplicate-opening prevention prefixes a deterministic connector
    - everything is a pure function: no randomness, no state, no LLM
"""

from app.personality import (
    CANT_DETERMINE_TEXT,
    GOODBYE_TEXT,
    GREETING_HEY_TEXT,
    THANKS_TEXT,
    UNCERTAIN_MEMORY_TEXT,
    StyleController,
)

SC = StyleController()


# ---------------------------------------------------------------------------
# Greeting variation
# ---------------------------------------------------------------------------


def test_greeting_turn_one_is_canonical_text() -> None:
    assert SC.vary_greeting(GREETING_HEY_TEXT, 1) == GREETING_HEY_TEXT
    assert SC.vary_greeting(GREETING_HEY_TEXT, None) == GREETING_HEY_TEXT


def test_greeting_rotates_deterministically() -> None:
    second = SC.vary_greeting(GREETING_HEY_TEXT, 2)
    third = SC.vary_greeting(GREETING_HEY_TEXT, 3)
    assert second == "Hey, good to see you."
    assert third == "Good to see you again!"
    assert second != third


def test_greeting_cycles_after_variants_are_exhausted() -> None:
    # (7 - 1) % 3 == 0, so turn 7 wraps back to the canonical text.
    assert SC.vary_greeting(GREETING_HEY_TEXT, 7) == GREETING_HEY_TEXT


def test_greeting_unknown_base_is_unchanged() -> None:
    assert SC.vary_greeting("Something unrelated", 5) == "Something unrelated"


def test_greeting_variation_is_deterministic() -> None:
    assert SC.vary_greeting(GREETING_HEY_TEXT, 4) == SC.vary_greeting(
        GREETING_HEY_TEXT, 4
    )


# ---------------------------------------------------------------------------
# Uncertainty / recall / closing variation
# ---------------------------------------------------------------------------


def test_uncertainty_variants_rotate_by_turn() -> None:
    assert SC.vary_uncertainty(UNCERTAIN_MEMORY_TEXT, 1) == UNCERTAIN_MEMORY_TEXT
    assert SC.vary_uncertainty(UNCERTAIN_MEMORY_TEXT, 2) == "I don't know that yet."
    assert SC.vary_uncertainty(UNCERTAIN_MEMORY_TEXT, 3) == (
        "I don't have enough information to answer that."
    )
    assert SC.vary_uncertainty(UNCERTAIN_MEMORY_TEXT, 4) == (
        "I can't determine that from what I know."
    )
    assert SC.vary_uncertainty(CANT_DETERMINE_TEXT, 1) == CANT_DETERMINE_TEXT
    assert SC.vary_uncertainty(CANT_DETERMINE_TEXT, 2) == "I don't know that yet."


def test_uncertainty_unknown_base_is_unchanged() -> None:
    assert SC.vary_uncertainty("bogus", 2) == "bogus"


def test_recall_preamble_rotates_by_turn() -> None:
    assert SC.recall_preamble(1) == "Here's what I remember:"
    assert SC.recall_preamble(2) == "I remember these:"
    assert SC.recall_preamble(3) == "From what you've told me:"
    assert SC.recall_preamble(None) == "Here's what I remember:"


def test_closing_variants_rotate_by_turn() -> None:
    assert SC.vary_closing(GOODBYE_TEXT, 1) == GOODBYE_TEXT
    assert SC.vary_closing(GOODBYE_TEXT, 2) == (
        "Goodbye — I'm here whenever you need me."
    )
    assert SC.vary_closing(THANKS_TEXT, 1) == THANKS_TEXT
    assert SC.vary_closing(THANKS_TEXT, 2) == "Anytime — glad I could help."


# ---------------------------------------------------------------------------
# Duplicate-opening prevention
# ---------------------------------------------------------------------------


def test_opening_paragraph_split() -> None:
    assert SC.opening_paragraph("first\n\nsecond") == "first"
    assert SC.opening_paragraph("single") == "single"
    assert SC.opening_paragraph("") == ""


def test_vary_opening_leaves_distinct_openings_untouched() -> None:
    text = "Fresh content here."
    assert SC.vary_opening(text, None, 2) == text
    assert SC.vary_opening(text, "something else", 2) == text


def test_vary_opening_prefixes_repeated_opening_deterministically() -> None:
    text = "Here is the summary.\n\nMore detail."
    assert SC.vary_opening(text, "Here is the summary.", 1) == "Additionally, " + text
    assert SC.vary_opening(text, "Here is the summary.", 2) == "Building on that, " + text
    assert SC.vary_opening(text, "Here is the summary.", 3) == "Adding to that, " + text


def test_vary_opening_compares_only_the_first_paragraph() -> None:
    text = "Here is the summary.\n\nDifferent tail."
    previous = "Here is the summary.\n\nOther tail."
    assert SC.vary_opening(text, SC.opening_paragraph(previous), 2) == (
        "Building on that, " + text
    )


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_pick_none_turn_always_returns_base() -> None:
    assert SC.pick(("a", "b", "c"), None) == "a"


def test_pick_rotates_without_mutation() -> None:
    variants = ("a", "b", "c")
    assert SC.pick(variants, 1) == "a"
    assert SC.pick(variants, 2) == "b"
    assert SC.pick(variants, 3) == "c"
    assert SC.pick(variants, 4) == "a"
    assert variants == ("a", "b", "c")
