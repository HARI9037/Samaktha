from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.runtime.base import Runtime
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.metrics import RuntimeMetricsCollector, RuntimeMetricsSnapshot


class RuntimeEngine(Runtime):
    """Coordinates RuntimeTask execution through registered executors."""

    def __init__(self, dispatcher: RuntimeDispatcher) -> None:
        self._dispatcher = dispatcher
        self._started = False
        self._metrics = RuntimeMetricsCollector()

    def get_metrics(self) -> RuntimeMetricsSnapshot:
        return self._metrics.get_metrics()

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
        self._metrics.record_dispatch()
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        executor = self._dispatcher.dispatch(task.action_type)
        if executor is None:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=f"No runtime executor registered for action type: {task.action_type}",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(perf_counter() - started) * 1000,
                metadata={"diagnostic": "executor_not_registered"},
            )
        result = await executor.execute(context, task, routing)
        finished_at = datetime.now(timezone.utc)
        return result.model_copy(update={
            "started_at": result.started_at or started_at,
            "finished_at": result.finished_at or finished_at,
            "duration_ms": result.duration_ms or (perf_counter() - started) * 1000,
            "metadata": {
                **result.metadata,
                "runtime_action_type": task.action_type,
                "runtime_request_id": context.request_id,
            },
        })
