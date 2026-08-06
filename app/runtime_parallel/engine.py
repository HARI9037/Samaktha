from __future__ import annotations

from dataclasses import dataclass

from app.runtime_parallel.worker import ExecutionWorker


@dataclass
class FailureRecoveryEngine:
    max_retries: int = 3

    def should_retry(self, worker: ExecutionWorker, attempt: int) -> bool:
        return attempt <= self.max_retries and worker.status != worker.status.COMPLETED
