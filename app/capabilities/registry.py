"""P2.3 — Versioned Capability Contracts: registry.

Stores every version of a capability contract by ``kind:name`` and answers
versioning questions: what the latest version is, whether a proposed contract
is compatible with it, and what changed along the upgrade path.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from app.capabilities.compat import ContractError, compare_contracts
from app.capabilities.models import CapabilityContract, ContractComparison
from app.plugins.models import PluginKind


class ContractRegistry:
    """A versioned store of capability contracts.

    Each ``kind:name`` key keeps its full version history, sorted ascending
    by semantic version. Registering a duplicate version is rejected.
    """

    def __init__(
        self, contracts: Iterable[CapabilityContract] = ()
    ) -> None:
        self._entries: dict[
            tuple[str, str], list[CapabilityContract]
        ] = defaultdict(list)
        for contract in contracts:
            self.register(contract)

    @staticmethod
    def _key(kind: PluginKind | str, name: str) -> tuple[str, str]:
        return (str(kind.value if hasattr(kind, "value") else kind), name)

    def register(self, contract: CapabilityContract) -> None:
        key = self._key(contract.kind, contract.name)
        versions = [c.semver for c in self._entries[key]]
        if contract.semver in versions:
            raise ContractError(
                f"Contract already registered: {contract.key}@{contract.version}"
            )
        self._entries[key].append(contract)
        self._entries[key].sort(key=lambda c: c.semver)

    def get(
        self,
        kind: PluginKind | str,
        name: str,
        version: Optional[str] = None,
    ) -> Optional[CapabilityContract]:
        entries = self._entries.get(self._key(kind, name), [])
        if not entries:
            return None
        if version is None:
            return entries[-1]
        for contract in entries:
            if contract.version == version:
                return contract
        return None

    def latest(
        self, kind: PluginKind | str, name: str
    ) -> Optional[CapabilityContract]:
        return self.get(kind, name)

    def versions(
        self, kind: PluginKind | str, name: str
    ) -> list[str]:
        return [c.version for c in self._entries.get(self._key(kind, name), [])]

    def has(self, kind: PluginKind | str, name: str) -> bool:
        return self.get(kind, name) is not None

    def all(self) -> list[CapabilityContract]:
        return [
            contract
            for entries in sorted(self._entries.values(), key=lambda e: e[0].key)
            for contract in entries
        ]

    def is_compatible_with_latest(
        self, contract: CapabilityContract
    ) -> Optional[ContractComparison]:
        """Compare ``contract`` against the latest registered version.

        Returns None when no prior version is registered for the same key.
        """
        previous = self.latest(contract.kind, contract.name)
        if previous is None or previous.version == contract.version:
            return None
        return compare_contracts(previous, contract)
