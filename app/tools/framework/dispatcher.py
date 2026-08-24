"""ToolDispatcher: the execution engine of the tool ecosystem.

Responsibilities:
  * resolving a tool through the registry (never hardcoded),
  * availability gating via the health monitor,
  * input and permission validation,
  * execution with timeouts, retries and cooperative cancellation,
  * parallel and dependency-ordered execution,
  * producing execution reports and diagnostics.

The dispatcher never raises: every invocation returns a ToolResult.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Iterable, Optional

from app.tools.base import ToolResult
from app.tools.framework.errors import (
    ToolCancelledError,
    ToolDependencyError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolUnavailableError,
    ToolValidationError,
)
from app.tools.framework.health import ToolHealthMonitor
from app.tools.framework.memory import ToolMemoryStore, ToolUsageRecord
from app.tools.framework.models import (
    ToolContext,
    ToolExecutionReport,
    ToolPermission,
    ToolPolicy,
)
from app.tools.framework.validator import ToolValidator

logger = logging.getLogger(__name__)

ResolveFn = Callable[[str], Optional[tuple[Any, Any]]]


class ToolCall:
    """A single dispatcher invocation: tool id plus arguments."""

    __slots__ = ("tool_id", "arguments")

    def __init__(self, tool_id: str, arguments: dict[str, Any] | None = None) -> None:
        self.tool_id = tool_id
        self.arguments = arguments or {}


class ToolDispatcher:
    def __init__(
        self,
        resolve: ResolveFn,
        validator: ToolValidator | None = None,
        health_monitor: ToolHealthMonitor | None = None,
        diagnostics: Any = None,
        memory: ToolMemoryStore | None = None,
    ) -> None:
        self._resolve = resolve
        self.validator = validator or ToolValidator()
        self.health_monitor = health_monitor or ToolHealthMonitor()
        self.diagnostics = diagnostics
        self.memory = memory
        self._retry_backoff = 0.25
        self._reports: list[ToolExecutionReport] = []

    def reports(self) -> list[ToolExecutionReport]:
        return list(self._reports)

    def last_report(self) -> Optional[ToolExecutionReport]:
        return self._reports[-1] if self._reports else None

    def clear_reports(self) -> None:
        self._reports.clear()

    # -- single execution ---------------------------------------------------

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any] | None = None,
        context: ToolContext | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> ToolResult:
        arguments = arguments or {}
        provided_context = context is not None
        context = context or ToolContext()
        request_id = context.request_id or uuid.uuid4().hex[:12]

        resolved = self._resolve(tool_id)
        if resolved is None:
            return self._fail(
                request_id, tool_id, "", "unavailable",
                ToolNotFoundError(f"Tool not found: {tool_id}"),
                arguments, context,
            )

        tool, info = resolved
        capability = str(getattr(info, "category", "")) or ""
        self._trace(request_id, "tool_selected", tool_id, capability)

        if not await self.health_monitor.is_available(tool, tool_id):
            return self._fail(
                request_id, tool_id, capability, "unavailable",
                ToolUnavailableError(f"Tool '{tool_id}' is unavailable"),
                arguments, context,
            )

        policy = self._policy_for(info)
        # Permission gating applies only when the caller supplied a context.
        # The legacy boundary (ToolManager.execute_tool) runs ungated because
        # CAP already approved the action before the plan reached the runtime.
        if provided_context:
            missing = self.validator.missing_permissions(policy, context)
            if missing:
                denied = ", ".join(p.value for p in missing)
                return self._fail(
                    request_id, tool_id, capability, "permission_denied",
                    ToolPermissionError(f"Missing permission(s): {denied}"),
                    arguments, context,
                )
        self._trace(request_id, "permission_checked", tool_id, capability, ok=True)

        schema = getattr(info, "input_schema", None) or {}
        errors = self.validator.validate_arguments(tool_id, arguments, schema)
        if errors:
            return self._fail(
                request_id, tool_id, capability, "validation_error",
                ToolValidationError("; ".join(errors)),
                arguments, context,
            )

        timeout = self._timeout_for(policy, context)
        retries = int(getattr(policy, "max_retries", 0))
        action = str(arguments.get("action", ""))
        side_effect_actions = set(getattr(info, "side_effect_actions", ()) or ())
        if action in side_effect_actions and not policy.idempotent_mutation:
            retries = 0
        started = time.monotonic()
        result, status, retry_count, error = await self._run_with_policy(
            tool, tool_id, capability, arguments, timeout, retries, cancel_event
        )
        duration_ms = round((time.monotonic() - started) * 1000, 3)

        self._record_report(
            request_id, tool_id, capability, arguments, status,
            duration_ms, retry_count, error, result,
        )
        self._trace(
            request_id, "result", tool_id, capability,
            ok=result.ok, detail=result.error or "",
        )
        self._record_usage(tool_id, arguments, duration_ms, status, context)
        return result

    async def _run_with_policy(
        self,
        tool: Any,
        tool_id: str,
        capability: str,
        arguments: dict[str, Any],
        timeout: float,
        retries: int,
        cancel_event: asyncio.Event | None,
    ) -> tuple[ToolResult, str, int, Optional[str]]:
        attempt = 0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return (
                    ToolResult(ok=False, error="Execution cancelled"),
                    "cancelled", attempt, "Execution cancelled",
                )
            try:
                if cancel_event is not None:
                    task = asyncio.ensure_future(tool.run(arguments))
                    done, pending = await asyncio.wait(
                        {task}, timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        task.cancel()
                        raise ToolTimeoutError(
                            f"Tool '{tool_id}' exceeded {timeout:.1f}s timeout"
                        )
                    result = done.pop().result()
                else:
                    result = await asyncio.wait_for(
                        tool.run(arguments), timeout=timeout
                    )
                if not isinstance(result, ToolResult):
                    result = ToolResult(ok=True, data={"output": result})
                return result, ("ok" if result.ok else "failed"), attempt, result.error
            except ToolTimeoutError as exc:
                if attempt < retries:
                    attempt += 1
                    await asyncio.sleep(self._retry_backoff)
                    continue
                return ToolResult(ok=False, error=str(exc)), "timeout", attempt, str(exc)
            except asyncio.TimeoutError as exc:
                timeout_error = ToolTimeoutError(
                    f"Tool '{tool_id}' exceeded {timeout:.1f}s timeout"
                )
                if attempt < retries:
                    attempt += 1
                    await asyncio.sleep(self._retry_backoff)
                    continue
                return (
                    ToolResult(ok=False, error=str(timeout_error)),
                    "timeout", attempt, str(timeout_error),
                )
            except ToolError as exc:
                return ToolResult(ok=False, error=str(exc)), "failed", attempt, str(exc)
            except asyncio.CancelledError:
                # Task cancellation is the coordinator/runtime propagation
                # mechanism and must not be swallowed as an ordinary result.
                raise
            except Exception as exc:  # noqa: BLE001 - tools must not raise
                logger.exception("Unexpected error in tool '%s'", tool_id)
                message = f"Tool '{tool_id}' failed: {exc}"
                return (
                    ToolResult(ok=False, error=message),
                    "failed", attempt, message,
                )

    # -- parallel & ordered execution ---------------------------------------

    async def execute_many(
        self,
        calls: Iterable[ToolCall],
        context: ToolContext | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> list[ToolResult]:
        return list(
            await asyncio.gather(
                *(self.execute(c.tool_id, c.arguments, context, cancel_event) for c in calls)
            )
        )

    async def execute_ordered(
        self,
        calls: list[ToolCall],
        dependencies: dict[int, list[int]] | None = None,
        context: ToolContext | None = None,
    ) -> list[ToolResult]:
        """Execute calls in dependency order (each call index waits for its
        prerequisite indices). Independent levels run in parallel."""
        deps = dependencies or {}
        n = len(calls)
        pending = set(range(n))
        results: dict[int, ToolResult] = {}
        remaining = {i: set(deps.get(i, [])) for i in range(n)}

        for i in deps:
            for prerequisite in deps[i]:
                if prerequisite < 0 or prerequisite >= n or prerequisite == i:
                    raise ToolDependencyError(f"Invalid dependency for call {i}")

        while pending:
            done_results = set(results)
            ready = [
                i for i in pending if remaining[i] <= done_results
            ]
            if not ready:
                raise ToolDependencyError("Dependency cycle detected")
            done = await self.execute_many(
                [calls[i] for i in ready], context=context
            )
            for index, result in zip(ready, done):
                results[index] = result
                pending.discard(index)
        return [results[i] for i in range(n)]

    # -- helpers --------------------------------------------------------------

    def _policy_for(self, info: Any) -> ToolPolicy:
        policy = getattr(info, "policy", None)
        if isinstance(policy, ToolPolicy):
            return policy
        return ToolPolicy()

    def _timeout_for(self, policy: ToolPolicy, context: ToolContext) -> float:
        return context.timeout_s or policy.default_timeout_s or 30.0

    def _fail(
        self,
        request_id: str,
        tool_id: str,
        capability: str,
        status: str,
        error: Exception,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        self._record_report(
            request_id, tool_id, capability, arguments, status,
            0.0, 0, str(error), ToolResult(ok=False, error=str(error)),
        )
        self._trace(request_id, "result", tool_id, capability, ok=False, detail=str(error))
        return ToolResult(ok=False, error=str(error))

    def _record_report(
        self,
        request_id: str,
        tool_id: str,
        capability: str,
        arguments: dict[str, Any],
        status: str,
        duration_ms: float,
        retry_count: int,
        error: Optional[str],
        result: ToolResult,
    ) -> None:
        report = ToolExecutionReport(
            tool_id=tool_id,
            capability=capability,
            action=str(arguments.get("action", "")),
            status=status,
            duration_ms=duration_ms,
            retries=retry_count,
            error=error,
            output=result.data if result.ok else None,
        )
        self._reports.append(report)
        logger.info(
            "tool %s status=%s duration_ms=%.1f request=%s",
            tool_id, status, duration_ms, request_id,
        )

    def _trace(self, request_id: str, stage: str, tool_id: str, capability: str,
               ok: bool = True, detail: str = "") -> None:
        if self.diagnostics is not None:
            self.diagnostics.record(
                request_id, stage, tool_id=tool_id,
                capability=capability, ok=ok, detail=detail,
            )

    def _record_usage(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        duration_ms: float,
        status: str,
        context: ToolContext,
    ) -> None:
        if self.memory is not None:
            self.memory.record_usage(
                ToolUsageRecord(
                    tool_id=tool_id,
                    action=str(arguments.get("action", "")),
                    duration_ms=duration_ms,
                    status=status,
                    user_id=context.user_id,
                )
            )
