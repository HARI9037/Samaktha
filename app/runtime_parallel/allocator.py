from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceAllocator:
    cpu_budget: int = 100
    memory_budget: int = 100
    token_budget: int = 100
    internet_budget: int = 0
    execution_timeout: float = 0.0

    def allocate(self, worker_priority: int, cpu: int = 1, memory: int = 1, tokens: int = 1, internet: int = 0) -> bool:
        if self.cpu_budget < cpu or self.memory_budget < memory or self.token_budget < tokens or self.internet_budget < internet:
            return False
        self.cpu_budget -= cpu
        self.memory_budget -= memory
        self.token_budget -= tokens
        self.internet_budget -= internet
        return True

