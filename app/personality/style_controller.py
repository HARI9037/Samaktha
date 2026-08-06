"""Phase 11.6 — deterministic StyleController.

Owns *wording variation* (response presentation only, never personality):
greeting variation, uncertainty variation, recall-preamble variation, closing
variation, and the connector that prevents repeated consecutive openings.
Every behavior is a pure deterministic function of (base text, turn); there is
no randomness, no LLM, and no mutable state beyond the read-only variant
tables, so identical inputs always produce identical output.

Ownership boundaries (Phase 11.6):
    - IntentEngine owns intent classification
    - PersonalityEngine owns identity/greeting/visibility decisions
    - ResponseFormatter owns response structure/formatting
    - StyleController owns wording variation only

This module never classifies, never builds personality, never formats
structure, and never touches CAP, GAMBIT, the Runtime, the Provider, or the
Memory Controller.
"""

from __future__ import annotations

# Base greeting texts match the ResponseFormatter's canonical greeting map;
# variant[0] is ALWAYS the base text so ``turn=1`` keeps legacy output stable.
_GREETING_VARIANTS: dict[str, tuple[str, ...]] = {
    "Good morning! How can I help you today?": (
        "Good morning! How can I help you today?",
        "Good morning — what can I do for you?",
        "Good morning! What would you like to work on?",
    ),
    "Good afternoon! How can I help you today?": (
        "Good afternoon! How can I help you today?",
        "Good afternoon — what can I do for you?",
        "Good afternoon! What would you like to work on?",
    ),
    "Good evening! How can I help you today?": (
        "Good evening! How can I help you today?",
        "Good evening — what can I do for you?",
        "Good evening! What would you like to work on?",
    ),
    "I'm doing well, thanks. How can I help you today?": (
        "I'm doing well, thanks. How can I help you today?",
        "Doing well, thank you. What can I help you with?",
    ),
    "Not much — how can I help you today?": (
        "Not much — how can I help you today?",
        "Not much. What can I do for you?",
    ),
    "Hey. Good to see you again.": (
        "Hey. Good to see you again.",
        "Hey, good to see you.",
        "Good to see you again!",
    ),
}

# variant[0] is the legacy uncertainty line; later variants give the same
# honest answer in fresher wording (still deterministic).
UNCERTAIN_MEMORY_VARIANTS = (
    "I don't have enough verified information.",
    "I don't know that yet.",
    "I don't have enough information to answer that.",
    "I can't determine that from what I know.",
)
CANT_DETERMINE_VARIANTS = (
    "I can't determine that from my available knowledge.",
    "I don't know that yet.",
    "I can't determine that from what I know.",
    "I don't have enough information to answer that.",
)
RECALL_PREAMBLE_VARIANTS = (
    "Here's what I remember:",
    "I remember these:",
    "From what you've told me:",
)
GOODBYE_VARIANTS = (
    "Goodbye! Feel free to call on me whenever you need help.",
    "Goodbye — I'm here whenever you need me.",
    "See you next time. I'll be here when you need help.",
)
THANKS_VARIANTS = (
    "You're welcome! Happy to help anytime.",
    "Anytime — glad I could help.",
    "You're welcome! That's what I'm here for.",
)

# Connectors that replace a repeated consecutive opening (Part 4).
OPENING_CONNECTORS = (
    "Additionally, ",
    "Building on that, ",
    "Adding to that, ",
    "To expand, ",
)


class StyleController:
    """Deterministic wording-variation facade. Stateless; safe to share."""

    @staticmethod
    def pick(variants: tuple[str, ...], turn: int | None) -> str:
        """Return ``variants[0]`` for legacy calls; otherwise rotate by turn.

        ``(turn - 1)`` indexing means the very first turn always yields the
        canonical text, so existing pinned outputs never change.
        """
        if not variants:
            return ""
        if turn is None:
            return variants[0]
        return variants[(turn - 1) % len(variants)]

    @staticmethod
    def opening_paragraph(text: str) -> str:
        """The first paragraph of a response (up to the first blank line)."""
        if not text:
            return ""
        return text.split("\n\n", 1)[0].strip()

    def vary_greeting(self, base: str, turn: int | None) -> str:
        variants = _GREETING_VARIANTS.get(base)
        if not variants:
            return base
        return self.pick(variants, turn)

    def vary_uncertainty(self, base: str, turn: int | None) -> str:
        if base == UNCERTAIN_MEMORY_VARIANTS[0]:
            return self.pick(UNCERTAIN_MEMORY_VARIANTS, turn)
        if base == CANT_DETERMINE_VARIANTS[0]:
            return self.pick(CANT_DETERMINE_VARIANTS, turn)
        return base

    def recall_preamble(self, turn: int | None) -> str:
        return self.pick(RECALL_PREAMBLE_VARIANTS, turn)

    def vary_closing(self, base: str, turn: int | None) -> str:
        if base == GOODBYE_VARIANTS[0]:
            return self.pick(GOODBYE_VARIANTS, turn)
        if base == THANKS_VARIANTS[0]:
            return self.pick(THANKS_VARIANTS, turn)
        return base

    def opening_connector(self, turn: int | None) -> str:
        return self.pick(OPENING_CONNECTORS, turn)

    def vary_opening(
        self,
        text: str,
        previous_opening: str | None,
        turn: int | None,
    ) -> str:
        """Prevent duplicate consecutive responses (Part 4).

        When the current response opens with the same paragraph as the previous
        response in this session, prefix it with a deterministic connector so
        the user never sees back-to-back identical openings. A pure function:
        no state is read or written.
        """
        if not text or not previous_opening:
            return text
        opening = self.opening_paragraph(text)
        if not opening or opening != previous_opening:
            return text
        return self.opening_connector(turn) + text


STYLE_CONTROLLER = StyleController()
