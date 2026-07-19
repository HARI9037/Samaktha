from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.api.schemas import ExecuteRequest, ExecuteResponse
from app.core.contracts import RuntimeContext
from app.core.orchestrator import SamakthaOrchestrator

router = APIRouter(tags=["execute"])


def get_orchestrator(request: Request) -> SamakthaOrchestrator:
    return request.app.state.orchestrator


@router.post("/execute", response_model=ExecuteResponse)
async def execute_request(
    payload: ExecuteRequest,
    orchestrator: SamakthaOrchestrator = Depends(get_orchestrator),
) -> ExecuteResponse:
    result = await orchestrator.run(
        request=payload.message,
        runtime_context=RuntimeContext(request_id=str(uuid4())),
    )
    response = result.output.get("response")
    return ExecuteResponse(
        status=result.status.value,
        response=str(response) if response is not None else None,
        error=result.error,
    )
