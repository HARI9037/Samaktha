"""P2.8 — Personality lifecycle.

Tracks the single active personality, validates switches against the registry,
and persists the selection when a :class:`PersonalityPersistence` is attached.

The manager is stateful but intentionally small: activate/deactivate/current
are the whole lifecycle. It never evaluates messages and never touches the
provider; the deterministic ``PersonalityEngine`` consumes its current profile.
"""

from __future__ import annotations

from typing import Optional

from app.personality.models import IdentityProfile
from app.personality.persistence import PersonalityPersistence
from app.personality.registry import (
    DEFAULT_PERSONALITY_ID,
    PersonalityDefinition,
    PersonalityRegistry,
    PersonalityValidationError,
)


class PersonalityLifecycleManager:
    """Owns which registered personality is currently active."""

    def __init__(
        self,
        registry: PersonalityRegistry,
        default_profile_id: str = DEFAULT_PERSONALITY_ID,
        persistence: Optional[PersonalityPersistence] = None,
    ) -> None:
        self._registry = registry
        self._default_profile_id = default_profile_id
        self._persistence = persistence
        # Re-activate a persisted selection, else fall back to the default.
        persisted = persistence.load() if persistence is not None else None
        if persisted is not None and registry.contains(persisted):
            self._active_profile_id = persisted
        else:
            self._active_profile_id = self._resolve_default()

    def _resolve_default(self) -> str:
        """Return a valid default profile id, tolerant of bad configuration."""
        if self._registry.contains(self._default_profile_id):
            return self._default_profile_id
        if self._registry.contains(DEFAULT_PERSONALITY_ID):
            return DEFAULT_PERSONALITY_ID
        available = self._registry.list()
        if not available:
            raise PersonalityValidationError(
                "Personality registry is empty; cannot resolve a default."
            )
        return available[0].profile_id

    @property
    def default_profile_id(self) -> str:
        return self._default_profile_id

    @property
    def active_profile_id(self) -> str:
        return self._active_profile_id

    @property
    def registry(self) -> PersonalityRegistry:
        return self._registry

    def current(self) -> PersonalityDefinition:
        """Return the active definition (falls back to the default)."""
        definition = self._registry.get(self._active_profile_id)
        if definition is None:
            definition = self._registry.require(self._resolve_default())
        return definition

    def current_profile(self) -> IdentityProfile:
        """Return the active identity profile."""
        return self.current().profile

    def activate(self, profile_id: str) -> PersonalityDefinition:
        """Switch the active personality (validating against the registry).

        Raises ``PersonalityValidationError`` for unknown ids. The selection
        is persisted when a persistence backend is attached.
        """
        definition = self._registry.require(profile_id)
        self._active_profile_id = definition.profile_id
        if self._persistence is not None:
            self._persistence.save(definition.profile_id)
        return definition

    def deactivate(self) -> PersonalityDefinition:
        """Reset the active personality to the default."""
        definition = self._registry.require(self._resolve_default())
        self._active_profile_id = definition.profile_id
        if self._persistence is not None:
            self._persistence.save(definition.profile_id)
        return definition

    def available(self) -> list[PersonalityDefinition]:
        """All registered personalities, ordered by profile_id."""
        return self._registry.list()
