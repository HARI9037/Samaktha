from __future__ import annotations

from dataclasses import dataclass

from app.runtime_parallel.worker import ExecutionWorker, WorkerLifecycleState


@dataclass
class FailureRecoveryEngine:
    max_retries: int = 3
    backoff_base_ms: float = 0.0

    def should_retry(self, worker: ExecutionWorker, attempt: int) -> bool:
        return attempt <= self.max_retries and worker.status == WorkerLifecycleState.FAILED

    def backoff_ms(self, attempt: int) -> float:
        if self.backoff_base_ms <= 0:
            return 0.0
        return min(self.backoff_base_ms * (2 ** (attempt - 1)), 30_000.0)
