from __future__ import annotations

from app.router.models import ProviderModelRegistration


class RouterRegistry:
    """In-memory registry of provider model metadata."""

    def __init__(
        self,
        registrations: list[ProviderModelRegistration] | None = None,
    ) -> None:
        self._registrations: list[ProviderModelRegistration] = []
        for registration in registrations or []:
            self.register(registration)

    def register(self, registration: ProviderModelRegistration) -> None:
        self._registrations.append(registration)

    def candidates(self, capability: str) -> list[ProviderModelRegistration]:
        normalized = self._normalize(capability)
        return [
            registration
            for registration in self._registrations
            if normalized in {self._normalize(item) for item in registration.capabilities}
        ]

    def all(self) -> list[ProviderModelRegistration]:
        return list(self._registrations)

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().lower().replace("-", "_").replace(" ", "_")
