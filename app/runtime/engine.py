from __future__ import annotations

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.runtime.base import Runtime
from app.runtime.dispatcher import RuntimeDispatcher


class RuntimeEngine(Runtime):
    """Coordinates RuntimeTask execution through registered executors."""

    def __init__(self, dispatcher: RuntimeDispatcher) -> None:
        self._dispatcher = dispatcher
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def run(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        executor = self._dispatcher.dispatch(task.action_type)
        if executor is None:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=f"No runtime executor registered for action type: {task.action_type}",
            )
        return await executor.execute(context, task, routing)
