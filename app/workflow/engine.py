from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

log = logging.getLogger(__name__)

from app.core.contracts import ExecutionPlan, PreparedContext, RouterRequest, RoutingDecision, RuntimeContext, RuntimeResult, ApprovedRuntimeTask
from app.core.contracts.planning import PlanTask, TaskKind, TaskStatus
from app.core.contracts.workflow import ExecutionGraph, TaskDependency
from app.core.contracts.policy import ExecutionPermit
from app.core.contracts.state import ExecutionStatus
from app.core.context_builder import ContextBuilder
from app.router.base import Router
from app.runtime.base import Runtime
from app.runtime.report import ExecutionReport, ExecutionTruthState
from app.workflow.models import WorkflowResult, WorkflowTask
from app.workflow.state import WorkflowState
from app.workflow.metrics import WorkflowMetricsCollector, WorkflowMetricsSnapshot
from app.workflow.pause import PauseManager


class ParallelWorkflowScheduler:
    """Manages parallel execution batches and dependency resolution."""

    def __init__(self, graph: ExecutionGraph) -> None:
        self.graph = graph
        self.completed_task_ids: set[str] = set()
        self.failed_task_ids: set[str] = set()

    def get_next_batch(self) -> list[PlanTask]:
        """Get the next batch of ready tasks."""
        return self.graph.get_ready_tasks(self.completed_task_ids, self.failed_task_ids)

    def mark_completed(self, task_id: str) -> None:
        self.completed_task_ids.add(task_id)

    def mark_failed(self, task_id: str) -> None:
        self.failed_task_ids.add(task_id)

    def get_blocked_tasks(self) -> list[PlanTask]:
        return self.graph.get_blocked_tasks(self.failed_task_ids)

    def is_finished(self) -> bool:
        blocked = {t.task_id for t in self.get_blocked_tasks()}
        total_handled = self.completed_task_ids | self.failed_task_ids | blocked
        return len(total_handled) >= len(self.graph.tasks)


class WorkflowEngine:
    """Parallel workflow executor using a dependency graph."""
    
    def __init__(self, pause_manager: PauseManager | None = None) -> None:
        self._metrics = WorkflowMetricsCollector()
        self._context_builder = ContextBuilder()
        self._pause_manager = pause_manager or PauseManager()

    def get_metrics(self) -> WorkflowMetricsSnapshot:
        return self._metrics.get_metrics()

    async def execute(
        self,
        execution_plan: ExecutionPlan,
        runtime: Runtime,
        router: Router,
        context: RuntimeContext | None = None,
        prepared_context: PreparedContext | None = None,
    ) -> WorkflowResult:
        log.debug("WorkflowEngine.execute is called. resume_state=%s", context.metadata.get('resume_state') if context else None)
        runtime_context = context or RuntimeContext(
            request_id=execution_plan.plan_id)
            
        # Build execution graph
        tasks = execution_plan.tasks
        dependencies = [
            TaskDependency(task_id=task.task_id, depends_on=task.dependencies)
            for task in tasks
        ]
        graph = ExecutionGraph(tasks=tasks, dependencies=dependencies)
        
        if context and context.trace:
            context.trace.add_event(
                source="workflow",
                event_type="workflow.started",
                total_steps=len(tasks),
            )
            
        resume_state = context.metadata.get("resume_state") if context else None
        
        if resume_state and isinstance(resume_state, WorkflowState):
            log.debug("The paused WorkflowState is restored. current_step=%s", resume_state.current_step)
            state = resume_state
            state.status = ExecutionStatus.RUNNING
        else:
            state = WorkflowState(
                workflow_id=execution_plan.plan_id,
                status=ExecutionStatus.RUNNING,
                total_steps=len(tasks),
                started_at=datetime.now(timezone.utc),
            )
        started = perf_counter()

        if not tasks:
            return self._fail_workflow(
                state, "No workflow tasks were produced for execution.", started, execution_plan.plan_id, context
            )

        if graph.detect_cycles():
            return self._fail_workflow(
                state, "Cycle detected in execution plan dependencies.", started, execution_plan.plan_id, context
            )

        scheduler = ParallelWorkflowScheduler(graph)
        scheduler.completed_task_ids = set(state.completed_task_ids)
        scheduler.failed_task_ids = set(state.failed_task_ids)
        
        # Build tasks applying any resume overrides
        pending_pause = self._pause_manager.get_pending_pause(execution_plan.plan_id)
        resume_overrides = pending_pause.resume_overrides if pending_pause else {}
        workflow_tasks = {
            t.task_id: t
            for t in self._workflow_tasks(
                execution_plan, resume_overrides, prepared_context
            )
        }
        if pending_pause:
            self._pause_manager.resolve_pause(execution_plan.plan_id)
        
        outputs: list[Any] = []
        while not scheduler.is_finished():
            batch = scheduler.get_next_batch()
            log.debug("scheduler get_next_batch returns: %s", [t.task_id for t in batch])
            if not batch:
                # We have tasks left but none are ready, and it's not finished. This is a scheduling failure.
                self._metrics.record_scheduling_failure()
                return self._fail_workflow(
                    state, "Scheduling failure: deadlocked or unresolved dependencies.", started, execution_plan.plan_id, context
                )
                
            self._metrics.record_parallel_batch(len(batch))
            
            if context and context.trace:
                context.trace.add_event(
                    source="workflow",
                    event_type="workflow.parallel.started",
                    number_of_tasks=len(batch),
                )
                
            batch_started = perf_counter()

            # Planning, verification, and reflection are internal workflow
            # steps. Only the explicit runtime task may invoke a provider.
            internal_tasks = [
                task for task in batch
                if task.kind != TaskKind.EXECUTE_VIA_RUNTIME
            ]
            batch_results = [
                RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    output={},
                    metadata={"internal_workflow_task": task.kind.value},
                )
                for task in internal_tasks
            ]
            for result in batch_results:
                state.results.append(result)
                state.current_step += 1
                state.completed_steps += 1
                scheduler.mark_completed(result.task_id)

            # Emit TASK_STARTED for all runtime batch tasks
            if context and context.event_bus:
                from app.core.events import RuntimeEventType
                for bt in batch:
                    context.event_bus.publish(
                        RuntimeEventType.TASK_STARTED, "workflow", "started",
                        workflow_id=execution_plan.plan_id,
                        trace_id=context.request_id if context else None,
                        task_id=bt.task_id,
                        payload={"title": bt.title, "kind": bt.kind.value}
                    )

            batch = [
                task for task in batch
                if task.kind == TaskKind.EXECUTE_VIA_RUNTIME
            ]
            if not batch:
                continue
            
            log.debug("The scheduler advances past the paused task with runtime batch: %s", [t.task_id for t in batch])
            
            # Route and prepare RuntimeTasks concurrently
            routings = await asyncio.gather(*[
                self._route_task(router, execution_plan, workflow_tasks[bt.task_id])
                for bt in batch
            ], return_exceptions=True)
            
            # Handle routing exceptions if any
            batch_results = []
            valid_tasks_for_runtime = []
            for bt, routing_res in zip(batch, routings):
                if isinstance(routing_res, Exception):
                    batch_results.append(RuntimeResult(
                        task_id=bt.task_id,
                        status=TaskStatus.FAILED,
                        error=f"Routing failed: {str(routing_res)}",
                    ))
                else:
                    valid_tasks_for_runtime.append((workflow_tasks[bt.task_id].runtime_task, routing_res))

            # Dispatch the ready batch.  RuntimeEngine.run_batch uses RuntimeExecutionPool
            # for true concurrency; any other Runtime falls back to asyncio.gather on run().
            runtime_tasks_and_routings = [(rt, routing) for rt, routing in valid_tasks_for_runtime]

            if runtime_tasks_and_routings:
                pipeline_ref = runtime_context.metadata.get("_pipeline_state_ref")
                if pipeline_ref is not None:
                    pipeline_ref.workflow_state = state.model_copy(deep=True)
                pool_results = await runtime.run_batch(runtime_context, runtime_tasks_and_routings)
                batch_results.extend(pool_results)
            
            batch_successful = 0
            batch_failed = 0
            
            for result in batch_results:
                outputs.append(result)
                state.results.append(result)
                state.current_step += 1
                
                if result.status == TaskStatus.COMPLETED:
                    state.completed_steps += 1
                    state.completed_task_ids.add(result.task_id)
                    scheduler.mark_completed(result.task_id)
                    batch_successful += 1
                    if context and context.event_bus:
                        context.event_bus.publish(
                            RuntimeEventType.TASK_COMPLETED, "workflow", "completed",
                            workflow_id=execution_plan.plan_id,
                            trace_id=context.request_id if context else None,
                            task_id=result.task_id,
                            payload={"duration_ms": result.duration_ms}
                        )
                    # Canonical P3 context augmentation: only a completed
                    # Runtime tool result may become provider evidence.
                    wt = workflow_tasks.get(result.task_id)
                    if (
                        prepared_context is not None
                        and wt
                        and wt.runtime_task.action_type == "tool"
                    ):
                        self._context_builder.append_runtime_evidence(
                            prepared_context, [result]
                        )
                        for pending_wt in workflow_tasks.values():
                            rt = pending_wt.runtime_task
                            if (
                                rt.action_type in ("text_generation", "provider")
                                and rt.task_id not in scheduler.completed_task_ids
                                and rt.task_id not in scheduler.failed_task_ids
                            ):
                                rt.inputs["prepared_context"] = prepared_context
                elif result.status == TaskStatus.PAUSED:
                    state.status = ExecutionStatus.PAUSED
                    
                    if result.pause:
                        self._pause_manager.register_pause(
                            plan_id=execution_plan.plan_id,
                            task_id=result.task_id,
                            pause=result.pause,
                        )
                        
                    duration = (perf_counter() - started) * 1000
                    return WorkflowResult(
                        success=False,
                        workflow_state=state,
                        outputs=outputs,
                        errors=list(state.errors),
                        execution_report=self._execution_report(
                            execution_plan.plan_id, state, started, len(scheduler.get_blocked_tasks())
                        ),
                    )
                else:
                    state.failed_step = state.current_step
                    state.failed_task_ids.add(result.task_id)
                    scheduler.mark_failed(result.task_id)
                    batch_failed += 1
                    if result.error:
                        state.errors.append(result.error)
                    if context and context.event_bus:
                        context.event_bus.publish(
                            RuntimeEventType.TASK_FAILED, "workflow", "failed",
                            workflow_id=execution_plan.plan_id,
                            trace_id=context.request_id if context else None,
                            task_id=result.task_id,
                            payload={"error": result.error or "unknown"}
                        )
                
            log.info("WorkflowEngine: batch result — task_id=%s status=%s error=%s output_keys=%s", result.task_id, result.status, result.error, list(result.output.keys()) if isinstance(result.output, dict) else type(result.output).__name__)

            pipeline_ref = runtime_context.metadata.get("_pipeline_state_ref")
            checkpoint = runtime_context.metadata.get("reliability_checkpoint")
            if pipeline_ref is not None and callable(checkpoint):
                pipeline_ref.workflow_state = state.model_copy(deep=True)
                checkpoint(pipeline_state=pipeline_ref, recovery_safe=True)
                    
            if context and context.trace:
                context.trace.add_event(
                    source="workflow",
                    event_type="workflow.parallel.completed",
                    execution_duration=(perf_counter() - batch_started) * 1000,
                    successful_tasks=batch_successful,
                    failed_tasks=batch_failed,
                    number_of_tasks=len(batch),
                )
                
            # Note: We do NOT fail the whole workflow immediately on a single task failure in a batch.
            # We continue scheduling. Dependents will be blocked.
            # Wait, if `state.status` is failed, does it fail the whole workflow?
            # Phase 4 says "Failure Handling: Dependency failure propagation. Tasks depending on A should receive blocked status."
            # So workflow continues for other independent tasks.
        
        # After loop, process blocked tasks
        blocked_tasks = scheduler.get_blocked_tasks()
        for blocked_task in blocked_tasks:
            result = RuntimeResult(
                task_id=blocked_task.task_id,
                status=TaskStatus.BLOCKED_BY_DEPENDENCY,
                error="Blocked by dependency failure",
            )
            outputs.append(result)
            state.results.append(result)
            state.current_step += 1

        is_success = len(scheduler.failed_task_ids) == 0 and len(blocked_tasks) == 0
        state.status = ExecutionStatus.COMPLETED if is_success else ExecutionStatus.FAILED
        state.finished_at = datetime.now(timezone.utc)
        
        duration = (perf_counter() - started) * 1000
        self._metrics.record_execution(success=is_success, duration_ms=duration)
        
        if context and context.trace:
            context.trace.add_event(
                source="workflow",
                event_type="workflow.completed" if is_success else "workflow.failed",
                duration_ms=duration,
            )
            
        return WorkflowResult(
            success=is_success,
            workflow_state=state,
            outputs=outputs,
            errors=list(state.errors),
            execution_report=self._execution_report(
                execution_plan.plan_id, state, started, len(blocked_tasks)
            ),
        )

    async def run(
        self,
        execution_plan: ExecutionPlan,
        runtime: Runtime,
        router: Router,
        context: RuntimeContext | None = None,
    ) -> WorkflowResult:
        return await self.execute(execution_plan=execution_plan, runtime=runtime, router=router, context=context)

    async def _route_task(self, router: Router, execution_plan: ExecutionPlan, workflow_task: WorkflowTask) -> RoutingDecision:
        action_type = workflow_task.runtime_task.action_type
        if action_type not in ("text_generation", "code_generation", "provider"):
            # Tool tasks do not need provider routing; bypass the router.
            return RoutingDecision(
                provider_id="",
                model_id="",
                reasoning_summary=f"Bypassed provider routing for tool task: {action_type}",
                constraints=[],
                metadata={"bypassed_routing": True}
            )
        routing_request = self._routing_request_for(execution_plan, workflow_task)
        return await router.route(routing_request)

    def _fail_workflow(self, state: WorkflowState, error: str, started: float, plan_id: str, context: RuntimeContext | None) -> WorkflowResult:
        state.status = ExecutionStatus.FAILED
        state.finished_at = datetime.now(timezone.utc)
        state.errors.append(error)
        duration = (perf_counter() - started) * 1000
        self._metrics.record_execution(success=False, duration_ms=duration)
        if context and context.trace:
            context.trace.add_event(
                source="workflow",
                event_type="workflow.failed",
                duration_ms=duration,
                error=error,
            )
        return WorkflowResult(
            success=False,
            workflow_state=state,
            outputs=[],
            errors=list(state.errors),
            execution_report=self._execution_report(plan_id, state, started, 0),
        )

    @staticmethod
    def _routing_request_for(execution_plan: ExecutionPlan, workflow_task: WorkflowTask) -> RouterRequest:
        router_request = workflow_task.runtime_task.metadata.get(
            "router_request")
        if isinstance(router_request, RouterRequest):
            return router_request
        return execution_plan.router_request

    @staticmethod
    def _execution_report(
        plan_id: str,
        state: WorkflowState,
        started: float,
        blocked_tasks: int,
    ) -> ExecutionReport:
        failed_count = sum(1 for res in state.results if res.status == TaskStatus.FAILED)
        result_dicts = [
            result.model_dump() if hasattr(result, "model_dump") else result
            for result in state.results
        ]
        executed_tasks = [
            str(result.get("task_id"))
            for result in result_dicts
            if isinstance(result, dict)
            and result.get("metadata", {}).get("internal_workflow_task") is None
            and result.get("status") in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}
        ]
        skipped_tasks = [
            str(result.get("task_id"))
            for result in result_dicts
            if isinstance(result, dict)
            and result.get("status") == TaskStatus.BLOCKED_BY_DEPENDENCY.value
        ]
        tool_results = [
            result for result in result_dicts
            if isinstance(result, dict)
            and result.get("metadata", {}).get("runtime_action_type") == "tool"
        ]
        provider_results = [
            result for result in result_dicts
            if isinstance(result, dict)
            and result.get("metadata", {}).get("runtime_action_type") in {"text_generation", "provider", "code_generation"}
        ]
        worker_information = [
            {
                "task_id": result.get("task_id"),
                "worker_id": result.get("metadata", {}).get("worker_id"),
            }
            for result in result_dicts
            if isinstance(result, dict) and result.get("metadata", {}).get("worker_id")
        ]
        authorization_by_task: dict[str, dict[str, Any]] = {}
        for result in result_dicts:
            if not isinstance(result, dict):
                continue
            metadata = result.get("metadata", {})
            if not metadata.get("permit_id"):
                continue
            authorization_by_task[str(result.get("task_id"))] = {
                "task_id": result.get("task_id"),
                "permit_id": metadata.get("permit_id"),
                "operation_digest": metadata.get("operation_digest"),
                "decision": metadata.get("authorization_decision"),
                "source": metadata.get("authorization_source"),
                "policy_reference": metadata.get("policy_reference"),
                "governance_record_id": metadata.get("record_id"),
                "execution_status": result.get("status"),
            }
        authorizations = list(authorization_by_task.values())
        if state.status == ExecutionStatus.PAUSED:
            execution_state = ExecutionTruthState.WAITING_APPROVAL
            approval_status = "waiting_approval"
        elif state.status == ExecutionStatus.COMPLETED:
            execution_state = ExecutionTruthState.SUCCEEDED
            approval_status = (
                "approved"
                if authorizations
                and all(item["decision"] == "allow" for item in authorizations)
                else "unknown"
            )
        elif state.status == ExecutionStatus.FAILED:
            execution_state = ExecutionTruthState.FAILED
            approval_status = (
                "blocked"
                if any(item["decision"] != "allow" for item in authorizations)
                or any("approval" in err.lower() for err in state.errors)
                else "approved"
            )
        elif state.status == ExecutionStatus.RUNNING:
            execution_state = ExecutionTruthState.EXECUTING
            approval_status = "approved"
        else:
            execution_state = ExecutionTruthState.PLANNED
            approval_status = "unknown"
        return ExecutionReport(
            plan_id=plan_id,
            success=state.status == ExecutionStatus.COMPLETED,
            execution_state=execution_state,
            executed_tasks=executed_tasks,
            skipped_tasks=skipped_tasks,
            tool_results=tool_results,
            provider_results=provider_results,
            approval_status=approval_status,
            worker_information=worker_information,
            retry_count=sum(
                int(result.get("metadata", {}).get("retry_count", 0) or 0)
                for result in result_dicts
                if isinstance(result, dict)
            ),
            started_at=state.started_at,
            finished_at=state.finished_at,
            duration_ms=int((perf_counter() - started) * 1000),
            completed_tasks=state.completed_steps,
            failed_tasks=failed_count,
            blocked_tasks=blocked_tasks,
            results=result_dicts,
            errors=list(state.errors),
            metadata={
                "workflow_id": state.workflow_id,
                "total_steps": state.total_steps,
                "authorizations": authorizations,
            },
        )

    @staticmethod
    def _workflow_tasks(
        execution_plan: ExecutionPlan,
        resume_overrides: dict[str, dict[str, Any]] | None = None,
        prepared_context: PreparedContext | None = None,
    ) -> list[WorkflowTask]:
        resume_overrides = resume_overrides or {}
        task_by_id = {task.task_id: task for task in execution_plan.tasks}
        workflow_tasks: list[WorkflowTask] = []
        for task in execution_plan.tasks:
            overrides = resume_overrides.get(task.task_id, {})
            
            # CAP is the sole permit issuer. Resume data may never patch it.
            permit_data = task.metadata.get("permit")
            
            # Combine args
            task_args = {**task.metadata.get("args", {})}
            if task.execution_action_type == "tool" and task.metadata.get("action"):
                task_args.setdefault("action", task.metadata["action"])
            if "args" in overrides:
                task_args.update(overrides["args"])
                
            workflow_tasks.append(
                WorkflowTask(
                    task_id=task.task_id,
                    name=task.title,
                    description=task.description,
                    agent_id=task.metadata.get("agent_id"),
                    worker_requirement=task.worker_requirement,
                    preferred_worker=task.preferred_worker,
                    runtime_task=ApprovedRuntimeTask(
                        task_id=task.task_id,
                        title=task.title,
                        description=task.description,
                        action_type=task.execution_action_type,
                        worker_requirement=task.worker_requirement,
                        preferred_worker=task.preferred_worker,
                        permit=ExecutionPermit(**permit_data) if permit_data else None,
                        inputs={
                            "prompt": (
                                execution_plan.goal.raw_request
                                if task.kind == TaskKind.EXECUTE_VIA_RUNTIME
                                else task.description
                            ),
                            "plan_task_id": task.task_id,
                            "plan_task_kind": task.kind.value,
                            **task_args,
                        } | (
                            {"prepared_context": prepared_context}
                            if prepared_context is not None
                            and task.execution_action_type in {
                                "text_generation", "code_generation", "provider"
                            }
                            else {}
                        ) | (
                            {"system_prompt": task.metadata["system_prompt"]}
                            if task.metadata.get("system_prompt")
                            else {}
                        ),
                        dependencies=task.dependencies,
                        metadata={
                            **deepcopy(task.metadata),
                            "plan_id": execution_plan.plan_id,
                            "plan_task_id": task.task_id,
                            "plan_task_kind": task.kind.value,
                            "router_request": task.router_request,
                            "agent_id": task.metadata.get("agent_id"),
                        },
                    ),
                )
            )
            log.info("WorkflowEngine: task — id=%s action_type=%s inputs_keys=%s tool=%s", task.task_id, task.execution_action_type, list(task_args.keys()), task.metadata.get("tool"))
            log.debug("Constructed RuntimeTask %s, metadata keys: %s", task.task_id, list(workflow_tasks[-1].runtime_task.metadata.keys()))
        return workflow_tasks
