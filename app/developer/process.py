from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BackgroundJob:
    job_id: str
    command: str
    status: str = "pending"
    logs: list[str] = field(default_factory=list)
    exit_code: int | None = None


class ProcessRegistry:
    def __init__(self) -> None:
        self.jobs: dict[str, BackgroundJob] = {}

    def register(self, job: BackgroundJob) -> None:
        self.jobs[job.job_id] = job


class LogStreamer:
    def stream(self, job: BackgroundJob) -> list[str]:
        return list(job.logs)


class JobController:
    def cancel(self, job: BackgroundJob) -> None:
        job.status = "cancelled"


class ProcessManager:
    def __init__(self) -> None:
        self.registry = ProcessRegistry()

