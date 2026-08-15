"""P2.8 — Personality registry.

Catalogs discoverable, validated :class:`IdentityProfile` personalities under
stable ``profile_id`` keys. The registry is pure structured data — it never
plans, never learns, and never touches storage; persistence is handled
separately by :mod:`app.personality.persistence`.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.personality.engine import SAMAKTHA_IDENTITY_PROFILE
from app.personality.models import IdentityProfile

DEFAULT_PERSONALITY_ID = "samaktha-core"


class PersonalityValidationError(ValueError):
    """Raised when a personality definition or switch is invalid."""


class PersonalityDefinition(BaseModel):
    """A registered, discoverable personality.

    ``profile_id`` is the stable key used by the lifecycle manager and the
    switching surface. The ``profile`` is the structured identity consumed by
    the deterministic ``PersonalityEngine``.
    """

    profile_id: str
    name: str
    description: str
    profile: IdentityProfile


class PersonalityRegistry:
    """Catalog of registered personalities keyed by ``profile_id``."""

    def __init__(self, definitions: Optional[list[PersonalityDefinition]] = None) -> None:
        self._definitions: dict[str, PersonalityDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: PersonalityDefinition) -> None:
        """Register a personality, validating its key and uniqueness."""
        self.validate(definition)
        if definition.profile_id in self._definitions:
            raise PersonalityValidationError(
                f"Personality {definition.profile_id!r} is already registered."
            )
        self._definitions[definition.profile_id] = definition

    def register_profile(
        self,
        profile_id: str,
        name: str,
        description: str,
        profile: IdentityProfile,
    ) -> PersonalityDefinition:
        """Build and register a definition from its parts."""
        definition = PersonalityDefinition(
            profile_id=profile_id,
            name=name,
            description=description,
            profile=profile,
        )
        self.register(definition)
        return definition

    def unregister(self, profile_id: str) -> bool:
        """Remove a registered personality; idempotent. Returns True if removed."""
        if profile_id in self._definitions:
            del self._definitions[profile_id]
            return True
        return False

    def get(self, profile_id: str) -> Optional[PersonalityDefinition]:
        """Return a definition or None when it is not registered."""
        return self._definitions.get(profile_id)

    def require(self, profile_id: str) -> PersonalityDefinition:
        """Return a definition or raise when it is not registered."""
        definition = self._definitions.get(profile_id)
        if definition is None:
            raise PersonalityValidationError(
                f"Unknown personality {profile_id!r}. "
                f"Available: {sorted(self._definitions)}."
            )
        return definition

    def contains(self, profile_id: str) -> bool:
        return profile_id in self._definitions

    def list(self) -> list[PersonalityDefinition]:
        """Return all definitions ordered by profile_id."""
        return [self._definitions[key] for key in sorted(self._definitions)]

    @staticmethod
    def validate(definition: PersonalityDefinition) -> None:
        """Validate a definition's key and identity profile.

        ``IdentityProfile`` already enforces required fields at construction;
        this adds the registry-level invariants.
        """
        if not definition.profile_id or not definition.profile_id.strip():
            raise PersonalityValidationError(
                "Personality profile_id must be a non-empty string."
            )
        if not definition.name or not definition.name.strip():
            raise PersonalityValidationError(
                f"Personality {definition.profile_id!r} needs a non-empty name."
            )
        profile = definition.profile
        for field in ("name", "mission", "description", "philosophy"):
            if not getattr(profile, field, "").strip():
                raise PersonalityValidationError(
                    f"Personality {definition.profile_id!r} profile field "
                    f"{field!r} must be non-empty."
                )


def default_personality_registry() -> PersonalityRegistry:
    """Registry seeded with the single production default personality."""
    return PersonalityRegistry(
        [
            PersonalityDefinition(
                profile_id=DEFAULT_PERSONALITY_ID,
                name="Samaktha Core",
                description=(
                    "The deterministic, governance-first default personality: "
                    "analytical, precise, professional, and direct."
                ),
                profile=SAMAKTHA_IDENTITY_PROFILE,
            )
        ]
    )
