from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.contracts.policy import (
    PermissionDecision,
    PermissionRecord,
    PermissionScope,
)


class PermissionStore(ABC):
    """Interface for remembered permission decisions."""

    @abstractmethod
    async def get(
        self,
        subject_id: str,
        resource: str,
        scope: PermissionScope,
    ) -> PermissionDecision:
        raise NotImplementedError

    @abstractmethod
    async def set(self, record: PermissionRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    async def revoke(
        self,
        subject_id: str,
        resource: str,
        scope: PermissionScope,
    ) -> None:
        raise NotImplementedError


class InMemoryPermissionStore(PermissionStore):
    """In-memory permission store with a persistence-ready interface."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, PermissionScope], PermissionDecision] = {}

    async def get(
        self,
        subject_id: str,
        resource: str,
        scope: PermissionScope,
    ) -> PermissionDecision:
        key = self._key(subject_id, resource, scope)
        return self._records.get(key, PermissionDecision.UNKNOWN)

    async def set(self, record: PermissionRecord) -> None:
        key = self._key(record.subject_id, record.resource, record.scope)
        self._records[key] = record.decision

    async def revoke(
        self,
        subject_id: str,
        resource: str,
        scope: PermissionScope,
    ) -> None:
        self._records.pop(self._key(subject_id, resource, scope), None)

    @staticmethod
    def _key(
        subject_id: str,
        resource: str,
        scope: PermissionScope,
    ) -> tuple[str, str, PermissionScope]:
        return (subject_id, resource.strip().lower(), scope)
