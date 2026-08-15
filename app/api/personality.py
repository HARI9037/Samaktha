from fastapi import APIRouter, HTTPException, Request

from app.personality import PersonalityValidationError

router = APIRouter(tags=["personality"])


@router.get("/personality")
async def get_personality(request: Request) -> dict:
    """P2.8 — the currently active personality and all registered ones."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None or not hasattr(orchestrator, "get_personality"):
        raise HTTPException(status_code=503, detail="Personality support unavailable")
    return {
        "active": orchestrator.get_personality(),
        "available": orchestrator.list_personalities(),
    }


@router.put("/personality/{profile_id}")
async def switch_personality(profile_id: str, request: Request) -> dict:
    """P2.8 — switch the active personality (validated and persisted).

    Unknown profile ids return 404; the switch is applied to the shared
    orchestrator's deterministic personality engine and persisted so it
    survives restarts.
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None or not hasattr(orchestrator, "switch_personality"):
        raise HTTPException(status_code=503, detail="Personality support unavailable")
    try:
        return orchestrator.switch_personality(profile_id)
    except PersonalityValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
