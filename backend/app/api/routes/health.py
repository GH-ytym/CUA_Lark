"""Health and readiness endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check() -> dict[str, str]:
    """Readiness probe with key runtime metadata."""
    settings = get_settings()
    return {
        "status": "ready",
        "app_name": settings.app_name,
        "env": settings.app_env,
        "timestamp": datetime.now(UTC).isoformat(),
    }
