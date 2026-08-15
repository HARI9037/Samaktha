from __future__ import annotations

from dataclasses import dataclass, field

from app.runtime_parallel.worker import ExecutionWorker, WorkerLifecycleState


@dataclass
class WorkerManager:
    workers: dict[str, ExecutionWorker] = field(default_factory=dict)

    def create_worker(self, worker: ExecutionWorker) -> ExecutionWorker:
        self.workers[worker.worker_id] = worker
        worker.status = WorkerLifecycleState.CREATED
        return worker

    def destroy_worker(self, worker_id: str) -> None:
        self.workers.pop(worker_id, None)

    def lookup(self, worker_id: str) -> ExecutionWorker | None:
        return self.workers.get(worker_id)

    def count(self, status: WorkerLifecycleState) -> int:
        return sum(1 for worker in self.workers.values() if worker.status == status)

    def active_count(self) -> int:
        active = {WorkerLifecycleState.CREATED, WorkerLifecycleState.ASSIGNED, WorkerLifecycleState.RUNNING, WorkerLifecycleState.WAITING}
        return sum(1 for worker in self.workers.values() if worker.status in active)

    def cleanup(self) -> None:
        archived = [wid for wid, worker in self.workers.items() if worker.status in {WorkerLifecycleState.COMPLETED, WorkerLifecycleState.FAILED, WorkerLifecycleState.CANCELLED}]
        for wid in archived:
            self.workers[wid].status = WorkerLifecycleState.ARCHIVED

