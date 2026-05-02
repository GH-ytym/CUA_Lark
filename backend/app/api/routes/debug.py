"""Debug routes for traceability during sprint integration."""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/echo")
async def debug_echo(request: Request) -> dict[str, str]:
    """Return request metadata to validate middleware wiring."""
    request_id = getattr(request.state, "request_id", "missing")
    principal = getattr(request.state, "principal", "anonymous")
    return {"request_id": request_id, "principal": principal}
