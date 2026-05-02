"""API route registry."""

from fastapi import APIRouter

from app.api.routes import agent, debug, executions, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(agent.router)
api_router.include_router(executions.router)
api_router.include_router(debug.router)
