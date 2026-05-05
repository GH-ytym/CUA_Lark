"""Execution routes for task detail lookup."""

from fastapi import APIRouter, HTTPException

from app.api.routes.agent import orchestrator_service
from app.domain.enums import ExecutionStatus
from app.schemas.execution import CancelExecutionResponse, ExecutionDetailResponse

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("/{task_id}", response_model=ExecutionDetailResponse)
async def get_execution_detail(task_id: str) -> ExecutionDetailResponse:
    """Return one execution task with recorded orchestration steps."""
    task = orchestrator_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return ExecutionDetailResponse.model_validate(task.model_dump())


@router.post("/{task_id}/cancel", response_model=CancelExecutionResponse)
async def cancel_execution(task_id: str) -> CancelExecutionResponse:
    """Cancel one non-terminal in-memory task."""
    before = orchestrator_service.get_task(task_id)
    before_status = before.status if before is not None else None
    task = orchestrator_service.cancel_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    was_terminal = before_status in {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
    }
    return CancelExecutionResponse(
        task_id=task.task_id,
        status=task.status,
        canceled=task.status == ExecutionStatus.CANCELED and not was_terminal,
        summary="task canceled" if task.status == ExecutionStatus.CANCELED and not was_terminal else "task already terminal",
    )
