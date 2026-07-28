"""Tool Chain Executor for Samaktha Runtime.

Executes deterministic multi-step tool sequences (chains).
Validates dependencies and relies on ToolManager as the exclusive
gateway for tool execution.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.core.contracts.tools import (
    ToolChain,
    ToolExecutionResult,
    ToolFailurePolicy,
    ToolStep,
)
from app.runtime.tool_chain_metrics import ToolChainMetricsCollector

if TYPE_CHECKING:
    from app.core.contracts.runtime import RuntimeContext
    from app.tools.manager import ToolManager


class ToolChainExecutor:
    """Executes a deterministic chain of tools."""

    def __init__(
        self,
        tool_manager: "ToolManager",
        metrics: Optional[ToolChainMetricsCollector] = None,
    ) -> None:
        self._tool_manager = tool_manager
        self._metrics = metrics or ToolChainMetricsCollector()

    def get_metrics(self) -> dict:
        return self._metrics.get_snapshot()

    def _resolve_execution_order(self, steps: List[ToolStep]) -> List[List[ToolStep]]:
        """Resolve steps into ordered batches based on dependencies.
        
        Steps within the same batch can theoretically be executed in parallel,
        but are executed sequentially here for deterministic simplicity unless
        parallelism is explicitly handled later.
        """
        batches = []
        pending = list(steps)
        completed_ids = set()

        while pending:
            batch = []
            for step in pending:
                if all(dep in completed_ids for dep in step.depends_on):
                    batch.append(step)
            
            if not batch:
                raise ValueError("Cyclic dependency or missing dependency detected in ToolChain.")
                
            for step in batch:
                completed_ids.add(step.step_id)
                pending.remove(step)
                
            batches.append(batch)
            
        return batches

    async def execute_chain(
        self,
        chain: ToolChain,
        context: Optional["RuntimeContext"] = None,
    ) -> List[ToolExecutionResult]:
        """Execute the tool chain sequentially respecting dependencies."""
        self._metrics.record_chain_started()
        
        start_time = time.perf_counter()
        results: List[ToolExecutionResult] = []
        results_by_id: Dict[str, ToolExecutionResult] = {}
        
        if context and context.trace:
            context.trace.add_event(
                source="runtime.tool_chain",
                event_type="tool_chain.execution.started",
                chain_id=chain.chain_id,
            )

        try:
            if len(chain.steps) > chain.max_steps:
                raise ValueError(f"Chain length ({len(chain.steps)}) exceeds max_steps ({chain.max_steps})")

            batches = self._resolve_execution_order(chain.steps)
            
            for batch in batches:
                for step in batch:
                    # Collect inputs from dependent steps if parameters reference them.
                    # This could be implemented here natively using string formatting
                    # or left to the caller to provide explicit arguments.
                    # We pass the raw parameters directly for simplicity.
                    
                    result = await self._execute_step_with_retry(step, chain.failure_policy)
                    results.append(result)
                    results_by_id[step.step_id] = result
                    
                    if not result.success:
                        if chain.failure_policy == ToolFailurePolicy.STOP_ON_FAILURE:
                            raise RuntimeError(f"Step {step.step_id} failed and STOP_ON_FAILURE is set.")
                        # CONTINUE_ON_FAILURE ignores the failure, loop continues
            
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_chain_completed(duration_ms)
            
            if context and context.trace:
                context.trace.add_event(
                    source="runtime.tool_chain",
                    event_type="tool_chain.execution.completed",
                    chain_id=chain.chain_id,
                    duration_ms=duration_ms,
                )
            return results
            
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_chain_failed(duration_ms)
            
            if context and context.trace:
                context.trace.add_event(
                    source="runtime.tool_chain",
                    event_type="tool_chain.execution.failed",
                    chain_id=chain.chain_id,
                    error=str(exc),
                    duration_ms=duration_ms,
                )
            
            # Re-raise runtime errors to bubble up failure semantics
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"ToolChain execution failed: {exc}") from exc

    async def _execute_step_with_retry(
        self,
        step: ToolStep,
        policy: ToolFailurePolicy
    ) -> ToolExecutionResult:
        """Execute a single step, applying retry policy if necessary."""
        max_attempts = 3 if policy == ToolFailurePolicy.RETRY_FAILED_STEP else 1
        attempt = 0
        
        while attempt < max_attempts:
            attempt += 1
            step_start = time.perf_counter()
            
            raw_result = await self._tool_manager.execute_tool(
                tool_id=step.tool_name,
                arguments=step.parameters
            )
            
            duration_ms = (time.perf_counter() - step_start) * 1000
            
            if raw_result.ok:
                self._metrics.record_step_execution(success=True)
                return ToolExecutionResult(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    success=True,
                    output=raw_result.data,
                    duration_ms=duration_ms,
                )
            
            # Failed
            self._metrics.record_step_execution(success=False)
            
            if attempt < max_attempts:
                self._metrics.record_retry()
            else:
                return ToolExecutionResult(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    success=False,
                    output=None,
                    error=raw_result.error or "Unknown error",
                    duration_ms=duration_ms,
                )
        
        # Fallback for type checker, though loop logic ensures it returns above
        return ToolExecutionResult(
            step_id=step.step_id,
            tool_name=step.tool_name,
            success=False,
            output=None,
            error="Max retries reached",
            duration_ms=0.0,
        )
