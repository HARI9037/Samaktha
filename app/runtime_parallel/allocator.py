from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class ResourceAllocator:
    cpu_budget: int = 100
    memory_budget: int = 100
    token_budget: int = 100
    internet_budget: int = 0
    execution_timeout: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def allocate(self, worker_priority: int, cpu: int = 1, memory: int = 1, tokens: int = 1, internet: int = 0) -> bool:
        with self._lock:
            if self.cpu_budget < cpu or self.memory_budget < memory or self.token_budget < tokens or self.internet_budget < internet:
                return False
            self.cpu_budget -= cpu
            self.memory_budget -= memory
            self.token_budget -= tokens
            self.internet_budget -= internet
        return True

    def release(self, cpu: int = 1, memory: int = 1, tokens: int = 1, internet: int = 0) -> None:
        with self._lock:
            self.cpu_budget += cpu
            self.memory_budget += memory
            self.token_budget += tokens
            self.internet_budget += internet

    def available(self) -> dict[str, int]:
        with self._lock:
            return {
                "cpu": self.cpu_budget,
                "memory": self.memory_budget,
                "tokens": self.token_budget,
                "internet": self.internet_budget,
            }
