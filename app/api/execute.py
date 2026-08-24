"""P1.5 — HTTP execution layer.

``/execute`` runs the canonical orchestrator pipeline with:
- session continuity (optional ``session_id`` + conversation),
- timeout handling and client-disconnect cancellation,
- request/task correlation ids,
- structured errors (no raw 500 leakage),
- HTTP metrics integration.

``/execute/stream`` is a Server-Sent-Events endpoint over the same canonical
``run_pipeline`` path, streaming lifecycle events and the final result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    ApprovalDecisionRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStateResponse,
    SessionCreateRequest,
    SessionCreateResponse,
)
from app.core.contracts import RuntimeContext
from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
from app.core.orchestrator import SamakthaOrchestrator
from app.providers.config import ProviderStartupError
from app.runtime.report import ExecutionReport
from app.core.contracts.state import ExecutionStatus
from app.core.execution_coordinator import (
    ExecutionAccessError,
    ExecutionConflictError,
    ExecutionCoordinator,
    ExecutionNotFoundError,
)

router = APIRouter(tags=["execute"])

log = logging.getLogger(__name__)

DISCONNECT_POLL_S = 0.25


class _ClientDisconnected(Exception):
    """Raised internally when the client disconnects mid-execution."""


def get_orchestrator(request: Request) -> SamakthaOrchestrator:
    return request.app.state.orchestrator


def get_execution_coordinator(request: Request) -> ExecutionCoordinator:
    coordinator = getattr(request.app.state, "execution_coordinator", None)
    orchestrator = get_orchestrator(request)
    if coordinator is None or coordinator._orchestrator is not orchestrator:
        coordinator = ExecutionCoordinator(orchestrator)
        request.app.state.execution_coordinator = coordinator
    return coordinator


def _settings(request: Request):
    return getattr(request.app.state, "settings", None)


def _structured(detail: dict) -> HTTPException:
    return HTTPException(status_code=detail.get("status", 500), detail={
        "code": detail.get("code", "internal"),
        "message": detail.get("message", "Internal server error"),
        "request_id": detail.get("request_id"),
    })


def _resolve_api_session(orchestrator, supplied_session_id: str | None) -> str:
    """Resolve the local principal's session without accepting arbitrary IDs."""

    manager = getattr(orchestrator, "_session_manager", None)
    if manager is None:
        return supplied_session_id or "default"
    if supplied_session_id:
        try:
            manager.resolve_session(
                supplied_session_id,
                principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                create_if_missing=False,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="session access denied") from exc
        return supplied_session_id
    if not manager.session_exists("default"):
        manager.create_session(
            session_id="default",
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
        )
    else:
        manager.load_session(
            "default", principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
    return "default"


async def _await_with_limits(
    request: Request | None,
    coro: "asyncio.Task",
    timeout_s: float,
) -> "object":
    """Await ``coro`` with a hard timeout and disconnect-driven cancellation."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            coro.cancel()
            await _consume_cancel(coro)
            raise asyncio.TimeoutError
        _, pending = await asyncio.wait(
            {coro}, timeout=min(DISCONNECT_POLL_S, remaining)
        )
        if not pending:
            return coro.result()
        if request is not None and await request.is_disconnected():
            coro.cancel()
            await _consume_cancel(coro)
            raise _ClientDisconnected


async def _consume_cancel(coro: "asyncio.Task") -> None:
    if coro.done():
        try:
            coro.result()
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - cleanup only
            pass
        return
    try:
        await coro
    except asyncio.CancelledError:
        pass
    except Exception:  # noqa: BLE001 - cleanup only
        pass


def _extract_response(result) -> str | None:
    output = result.output or {}
    for key in ("content", "response"):
        value = output.get(key)
        if value is not None:
            return str(value)
    return None


def _metrics(request: Request):
    return getattr(request.app.state, "http_metrics", None)


def _run_orchestrator(orchestrator, message, context, conversation):
    """Invoke ``orchestrator.run``, passing conversation only when supplied
    so minimal orchestrators without the kwarg keep working."""
    if conversation is not None:
        return orchestrator.run(
            request=message, runtime_context=context, conversation=conversation
        )
    return orchestrator.run(request=message, runtime_context=context)


def _build_response(
    request: Request,
    result,
    request_id: str,
    session_id: str,
    execution_id: str | None = None,
) -> ExecuteResponse:
    response_text = _extract_response(result)
    response = ExecuteResponse(
        status=result.status.value,
        execution_id=execution_id or request_id,
        request_id=request_id,
        session_id=session_id,
        task_id=result.task_id,
        response=response_text,
        error=result.error,
    )
    report = (result.metadata or {}).get("execution_report")
    if report is not None:
        response.diagnostics = ExecutionReport(**report)
    return response


def _state_response(state) -> ExecutionStateResponse:
    return ExecutionStateResponse(
        execution_id=state.execution_id,
        status=state.status.value,
        principal_id=state.principal_id or DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id=state.session_id or "default",
        pending_approval=state.status == ExecutionStatus.AWAITING_APPROVAL,
        result_available=state.result_available,
        created_at=state.created_at.isoformat(),
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
        completed_at=state.completed_at.isoformat() if state.completed_at else None,
        error=state.error,
    )


def _coordinator_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExecutionNotFoundError):
        return HTTPException(status_code=404, detail="execution not found")
    if isinstance(exc, ExecutionAccessError):
        return HTTPException(status_code=403, detail="execution access denied")
    if isinstance(exc, ExecutionConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="session not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail="session access denied")
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/executions", response_model=ExecutionStateResponse)
async def start_execution(
    payload: ExecuteRequest,
    wait: bool = False,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> ExecutionStateResponse:
    try:
        state = await coordinator.start_execution(
            payload.message,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id=payload.session_id,
            conversation=payload.conversation,
            source="api",
            wait=wait,
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    return _state_response(state)


@router.get("/executions/{execution_id}", response_model=ExecutionStateResponse)
async def inspect_execution(
    execution_id: str,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> ExecutionStateResponse:
    try:
        return _state_response(coordinator.inspect_execution(
            execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        ))
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc


@router.get("/executions/{execution_id}/approval")
async def inspect_approval(
    execution_id: str,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    try:
        approval = coordinator.pending_approval(
            execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    if approval is None:
        raise HTTPException(status_code=404, detail="pending approval not found")
    sensitive = {"permit", "execution_permit", "integrity_digest", "secret"}
    approval["metadata"] = {
        key: value for key, value in approval.get("metadata", {}).items()
        if key not in sensitive
    }
    return approval


@router.post("/executions/{execution_id}/approval", response_model=ExecutionStateResponse)
async def submit_execution_approval(
    execution_id: str,
    payload: ApprovalDecisionRequest,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> ExecutionStateResponse:
    try:
        state = await coordinator.submit_approval(
            execution_id,
            payload.approval_id,
            payload.decision,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            reasons=payload.reasons,
            source="api",
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    return _state_response(state)


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionStateResponse)
async def cancel_execution(
    execution_id: str,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> ExecutionStateResponse:
    try:
        state = await coordinator.cancel_execution(
            execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    return _state_response(state)


@router.get("/executions/{execution_id}/events")
async def execution_events(
    execution_id: str,
    after: int = 0,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    try:
        events = coordinator.events(
            execution_id,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            after=after,
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    return {"execution_id": execution_id, "events": [e.model_dump(mode="json") for e in events]}


@router.get("/executions/{execution_id}/result")
async def execution_result(
    execution_id: str,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
):
    try:
        state = coordinator.inspect_execution(
            execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
        result = coordinator.result(
            execution_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    if not state.terminal or result is None:
        raise HTTPException(status_code=409, detail="execution result is not available")
    return {
        "execution_id": execution_id,
        "status": state.status.value,
        "result": result.model_dump(mode="json"),
        "report": (result.metadata or {}).get("execution_report"),
    }


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(
    payload: SessionCreateRequest,
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> SessionCreateResponse:
    try:
        session_id = coordinator.create_session(
            DEFAULT_LOCAL_PRINCIPAL_ID, payload.session_id
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    return SessionCreateResponse(session_id=session_id)


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    response_model_exclude_unset=True,
)
async def execute_request(
    payload: ExecuteRequest,
    request: Request,
    orchestrator: SamakthaOrchestrator = Depends(get_orchestrator),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> ExecuteResponse:
    if not isinstance(coordinator, ExecutionCoordinator):
        # Compatibility for direct Python callers that bypass FastAPI's
        # dependency injection. HTTP always receives the app coordinator.
        coordinator = ExecutionCoordinator(orchestrator)
    settings = _settings(request)
    request_id = getattr(getattr(request, "state", None), "request_id", None) or str(uuid4())
    try:
        session_id = coordinator.resolve_session(
            DEFAULT_LOCAL_PRINCIPAL_ID, payload.session_id
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    metrics = _metrics(request)
    start = time.perf_counter()

    if settings is None:
        timeout_s = 300.0
    else:
        timeout_s = settings.api_execute_timeout_seconds

    try:
        await coordinator.start_execution(
            payload.message,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id=session_id,
            conversation=payload.conversation,
            source="api.compat",
            wait=False,
            execution_id=request_id,
        )
        task = asyncio.create_task(
            coordinator.wait_execution(
                request_id,
                principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                raise_exception=True,
            )
        )
        await _await_with_limits(request, task, timeout_s)
        result = coordinator.result(
            request_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
    except asyncio.TimeoutError:
        await coordinator.timeout_execution(
            request_id,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            error=f"Execution exceeded the {timeout_s:.0f}s timeout",
        )
        if metrics is not None:
            metrics.record_timeout()
        log.warning(
            "[%s] execution timed out after %.1fs (session=%s)",
            request_id, timeout_s, session_id,
        )
        raise _structured(
            {"status": 504, "code": "timeout",
             "message": f"Execution exceeded the {timeout_s:.0f}s timeout",
             "request_id": request_id}
        ) from None
    except _ClientDisconnected:
        await coordinator.cancel_execution(
            request_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
        if metrics is not None:
            metrics.record_cancelled()
        log.info("[%s] client disconnected during execution (session=%s)", request_id, session_id)
        raise HTTPException(status_code=499, detail={
            "code": "client_disconnected",
            "message": "Client disconnected before execution completed",
            "request_id": request_id,
        }) from None
    except ProviderStartupError as exc:
        if metrics is not None:
            metrics.record_failed()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - structured error, no raw leakage
        if metrics is not None:
            metrics.record_failed()
        log.exception("[%s] execute failed (session=%s)", request_id, session_id)
        raise _structured(
            {"status": 500, "code": "internal",
             "message": "Internal server error", "request_id": request_id}
        ) from exc

    if result is None:
        state = coordinator.inspect_execution(
            request_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
        )
        raise _structured({
            "status": 500,
            "code": "missing_result",
            "message": state.error or "Execution finished without a result",
            "request_id": request_id,
        })
    if metrics is not None:
        metrics.record_completed(time.perf_counter() - start)
    log.info(
        "[%s] executed session=%s status=%s duration_ms=%.0f",
        request_id, session_id, result.status.value,
        (time.perf_counter() - start) * 1000,
    )
    return _build_response(
        request, result, request_id, session_id, execution_id=request_id
    )


def _run_pipeline(orchestrator, message, context, conversation):
    if conversation is not None:
        return orchestrator.run_pipeline(
            request=message, runtime_context=context, conversation=conversation
        )
    return orchestrator.run_pipeline(request=message, runtime_context=context)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/execute/stream")
async def execute_stream(
    payload: ExecuteRequest,
    request: Request,
    orchestrator: SamakthaOrchestrator = Depends(get_orchestrator),
    coordinator: ExecutionCoordinator = Depends(get_execution_coordinator),
) -> StreamingResponse:
    settings = _settings(request)
    timeout_s = settings.api_execute_timeout_seconds if settings else 300.0
    request_id = getattr(getattr(request, "state", None), "request_id", None) or str(uuid4())
    try:
        session_id = coordinator.resolve_session(
            DEFAULT_LOCAL_PRINCIPAL_ID, payload.session_id
        )
    except Exception as exc:
        raise _coordinator_http_error(exc) from exc
    metrics = _metrics(request)
    start = time.perf_counter()

    async def event_source():
        yield _sse("pipeline.started", {
            "request_id": request_id,
            "execution_id": request_id,
            "session_id": session_id,
        })
        await coordinator.start_execution(
            payload.message,
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id=session_id,
            conversation=payload.conversation,
            source="api.stream.compat",
            streaming=True,
            wait=False,
            execution_id=request_id,
        )
        cursor = 0
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            if await request.is_disconnected():
                await coordinator.cancel_execution(
                    request_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
                )
                return
            if asyncio.get_running_loop().time() >= deadline:
                await coordinator.timeout_execution(
                    request_id,
                    principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                    error=f"Execution exceeded the {timeout_s:.0f}s timeout",
                )
            events = coordinator.events(
                request_id,
                principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
                after=cursor,
            )
            for event in events:
                cursor += 1
                yield _sse(
                    event.data.event_type.value,
                    event.model_dump(mode="json"),
                )
            state = coordinator.inspect_execution(
                request_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
            )
            if state.terminal or state.status == ExecutionStatus.AWAITING_APPROVAL:
                if metrics is not None and state.status == ExecutionStatus.COMPLETED:
                    metrics.record_completed(time.perf_counter() - start)
                result = coordinator.result(
                    request_id, principal_id=DEFAULT_LOCAL_PRINCIPAL_ID
                )
                if state.status == ExecutionStatus.COMPLETED and result is not None:
                    yield _sse("pipeline.completed", {
                        "execution_id": request_id,
                        "status": result.status.value,
                        "task_id": result.task_id,
                        "response": _extract_response(result),
                        "error": result.error,
                    })
                elif state.status in {
                    ExecutionStatus.FAILED,
                    ExecutionStatus.CANCELLED,
                    ExecutionStatus.TIMED_OUT,
                }:
                    yield _sse("pipeline.failed", {
                        "execution_id": request_id,
                        "error": {
                            "code": state.status.value,
                            "message": state.error or state.status.value,
                        },
                    })
                return
            await asyncio.sleep(0.01)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
