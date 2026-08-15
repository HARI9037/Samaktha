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

from app.api.schemas import ExecuteRequest, ExecuteResponse
from app.core.contracts import RuntimeContext
from app.core.orchestrator import SamakthaOrchestrator
from app.providers.config import ProviderStartupError
from app.runtime.report import ExecutionReport

router = APIRouter(tags=["execute"])

log = logging.getLogger(__name__)

DISCONNECT_POLL_S = 0.25


class _ClientDisconnected(Exception):
    """Raised internally when the client disconnects mid-execution."""


def get_orchestrator(request: Request) -> SamakthaOrchestrator:
    return request.app.state.orchestrator


def _settings(request: Request):
    return getattr(request.app.state, "settings", None)


def _structured(detail: dict) -> HTTPException:
    return HTTPException(status_code=detail.get("status", 500), detail={
        "code": detail.get("code", "internal"),
        "message": detail.get("message", "Internal server error"),
        "request_id": detail.get("request_id"),
    })


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
) -> ExecuteResponse:
    response_text = _extract_response(result)
    response = ExecuteResponse(
        status=result.status.value,
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


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    response_model_exclude_unset=True,
)
async def execute_request(
    payload: ExecuteRequest,
    request: Request,
    orchestrator: SamakthaOrchestrator = Depends(get_orchestrator),
) -> ExecuteResponse:
    settings = _settings(request)
    request_id = getattr(getattr(request, "state", None), "request_id", None) or str(uuid4())
    session_id = payload.session_id or "default"
    metrics = _metrics(request)
    start = time.perf_counter()

    if settings is None:
        timeout_s = 300.0
    else:
        timeout_s = settings.api_execute_timeout_seconds

    context = RuntimeContext(request_id=request_id, session_id=payload.session_id)
    context.metadata["enable_tracing"] = True
    try:
        task = asyncio.create_task(
            _run_orchestrator(
                orchestrator, payload.message, context, payload.conversation
            )
        )
        result = await _await_with_limits(request, task, timeout_s)
    except asyncio.TimeoutError:
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

    if metrics is not None:
        metrics.record_completed(time.perf_counter() - start)
    log.info(
        "[%s] executed session=%s status=%s duration_ms=%.0f",
        request_id, session_id, result.status.value,
        (time.perf_counter() - start) * 1000,
    )
    return _build_response(request, result, request_id, session_id)


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
) -> StreamingResponse:
    settings = _settings(request)
    timeout_s = settings.api_execute_timeout_seconds if settings else 300.0
    request_id = getattr(getattr(request, "state", None), "request_id", None) or str(uuid4())
    session_id = payload.session_id or "default"
    metrics = _metrics(request)
    start = time.perf_counter()

    context = RuntimeContext(request_id=request_id, session_id=payload.session_id)
    context.metadata["enable_tracing"] = True

    async def event_source():
        yield _sse("pipeline.started", {"request_id": request_id, "session_id": session_id})
        task = asyncio.create_task(
            _run_pipeline(orchestrator, payload.message, context, payload.conversation)
        )
        try:
            state = await asyncio.wait_for(task, timeout=timeout_s)
        except asyncio.TimeoutError:
            if metrics is not None:
                metrics.record_timeout()
            yield _sse("pipeline.failed", {
                "error": {"code": "timeout",
                          "message": f"Execution exceeded the {timeout_s:.0f}s timeout"},
            })
            return
        except Exception:  # noqa: BLE001 - structured error, no raw leakage
            if metrics is not None:
                metrics.record_failed()
            log.exception("[%s] streaming pipeline failed (session=%s)", request_id, session_id)
            yield _sse("pipeline.failed", {
                "error": {"code": "internal", "message": "Internal server error"},
            })
            return
        finally:
            if task is not None and not task.done():
                task.cancel()

        result = state.runtime_result
        if result is None:
            yield _sse("pipeline.failed", {
                "error": {"code": "internal", "message": "Pipeline finished without a result"},
            })
            return

        if metrics is not None:
            metrics.record_completed(time.perf_counter() - start)
        yield _sse("pipeline.completed", {
            "status": result.status.value,
            "task_id": result.task_id,
            "response": _extract_response(result),
            "error": result.error,
        })

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
