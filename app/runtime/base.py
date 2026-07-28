from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask


class Runtime(ABC):
    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def run(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        raise NotImplementedError

    async def run_batch(
        self,
        context: RuntimeContext,
        tasks_and_routings: list[tuple[RuntimeTask, RoutingDecision]],
    ) -> list[RuntimeResult]:
        """Execute a batch of tasks concurrently.

        Subclasses may override this to use a dedicated execution pool.
        The default implementation uses asyncio.gather over run().
        """
        results = await asyncio.gather(
            *[self.run(context, task, routing) for task, routing in tasks_and_routings],
            return_exceptions=True,
        )
        final: list[RuntimeResult] = []
        for (task, _routing), res in zip(tasks_and_routings, results):
            if isinstance(res, Exception):
                from app.core.contracts.planning import TaskStatus
                final.append(
                    RuntimeResult(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        error=f"Unhandled runtime exception: {str(res)}",
                    )
                )
            else:
                final.append(res)
        return final
