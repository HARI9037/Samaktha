"""Deterministic speech-only personality profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PersonalityProfile(str, Enum):
    CORE = "core"
    ASSISTANT = "assistant"
    EXPERT = "expert"
    MINIMAL = "minimal"


@dataclass(frozen=True)
class SpeechPersonality:
    confirmations: tuple[str, ...]
    max_sentence_words: int
    filler: str = ""

    def adjust(self, text: str, emotion) -> str:
        return text


PROFILES = {
    PersonalityProfile.CORE: SpeechPersonality(("Sure.", "Absolutely.", "Of course.", "No problem."), 24),
    PersonalityProfile.ASSISTANT: SpeechPersonality(("Absolutely! Let me check.", "Sure.", "Of course."), 22),
    PersonalityProfile.EXPERT: SpeechPersonality(("Checking.", "Understood.", "I’ll verify that."), 32),
    PersonalityProfile.MINIMAL: SpeechPersonality(("One moment.", "Sure.", "Done."), 12),
}


class PersonalityEngine:
    def __init__(self, profile: PersonalityProfile | str = PersonalityProfile.CORE) -> None:
        self._profile = PersonalityProfile(profile)
        self._index = 0

    @property
    def profile(self) -> PersonalityProfile:
        return self._profile

    @profile.setter
    def profile(self, value: PersonalityProfile | str) -> None:
        self._profile = PersonalityProfile(value)
        self._index = 0

    @property
    def settings(self) -> SpeechPersonality:
        return PROFILES[self.profile]

    def confirmation(self) -> str:
        values = self.settings.confirmations
        value = values[self._index % len(values)]
        self._index += 1
        return value

    def adjust(self, text: str, emotion) -> str:
        return text


class GreetingEngine:
    def __init__(self) -> None:
        self._last: str | None = None

    def greeting(self, hour: int, returning: bool = False) -> str:
        if returning:
            value = "Welcome back."
        elif hour < 12:
            value = "Good morning."
        elif hour >= 23:
            value = "You're up late."
        else:
            value = "Good afternoon."
        if value == self._last:
            return "Hello."
        self._last = value
        return value
