from __future__ import annotations

from dataclasses import dataclass

from app.runtime_parallel.worker import WorkerResult


@dataclass
class ResultAggregator:
    def aggregate(self, results: list[WorkerResult]) -> list[WorkerResult]:
        unique: dict[str, WorkerResult] = {}
        for result in sorted(results, key=lambda r: (r.worker_id, not r.success, -r.confidence)):
            unique.setdefault(result.worker_id, result)
        return list(unique.values())

