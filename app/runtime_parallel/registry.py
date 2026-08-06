from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WorkerMetadata:
    worker_type: str
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


class WorkerRegistry:
    def __init__(self) -> None:
        self._types: dict[str, WorkerMetadata] = {}

    def register_worker_type(self, name: str, metadata: WorkerMetadata) -> None:
        self._types[name] = metadata

    def unregister_worker_type(self, name: str) -> None:
        self._types.pop(name, None)

    def get(self, name: str) -> WorkerMetadata | None:
        return self._types.get(name)

    def list_worker_types(self) -> list[str]:
        return sorted(self._types)

