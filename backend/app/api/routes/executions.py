"""Execution routes for task detail lookup."""

from fastapi import APIRouter, HTTPException

from app.api.routes.agent import orchestrator_service
from app.schemas.execution import ExecutionDetailResponse

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("/{task_id}", response_model=ExecutionDetailResponse)
async def get_execution_detail(task_id: str) -> ExecutionDetailResponse:
    """Return one execution task with recorded orchestration steps."""
    task = orchestrator_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return ExecutionDetailResponse.model_validate(task.model_dump())
