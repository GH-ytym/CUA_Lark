"""Execution routes for task detail lookup and sidebar progress streams."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import StreamingResponse

from app.api.routes.agent import orchestrator_service
from app.domain.enums import ExecutionStatus
from app.schemas.execution import ExecutionActionResponse, ExecutionDetailResponse, ExecutionStreamEvent
from app.services.stream_service import ExecutionStreamFormatter

router = APIRouter(prefix="/executions", tags=["executions"])
stream_formatter = ExecutionStreamFormatter()


@router.get("/{task_id}", response_model=ExecutionDetailResponse)
async def get_execution_detail(task_id: str) -> ExecutionDetailResponse:
    """Return one execution task with recorded orchestration steps."""
    task = orchestrator_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return stream_formatter.detail_from_task(task)


@router.post("/{task_id}/cancel", response_model=ExecutionActionResponse)
async def cancel_execution(task_id: str) -> ExecutionActionResponse:
    """Cancel one in-memory task when it has not reached a terminal state."""
    before = orchestrator_service.get_task(task_id)
    before_status = before.status if before is not None else None
    task = orchestrator_service.cancel_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    detail = stream_formatter.detail_from_task(task)
    was_terminal = before_status in {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
    }
    canceled = task.status == ExecutionStatus.CANCELED and not was_terminal
    return ExecutionActionResponse(
        task_id=task.task_id,
        status=task.status,
        canceled=canceled,
        summary="任务已取消。" if canceled else "任务已结束，无法取消。",
        detail=detail,
    )


@router.get("/{task_id}/stream")
async def stream_execution_detail(task_id: str, request: Request) -> StreamingResponse:
    """Stream ordered task status events for the React sidebar."""
    if orchestrator_service.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    async def event_generator():
        sent_steps = 0
        sequence = 1
        snapshot_sent = False

        while True:
            task = orchestrator_service.get_task(task_id)
            if task is None:
                break

            if not snapshot_sent:
                yield _format_sse_event(stream_formatter.snapshot_event(task=task, sequence=sequence))
                snapshot_sent = True
                sequence += 1

            while sent_steps < len(task.steps):
                step = task.steps[sent_steps]
                yield _format_sse_event(
                    stream_formatter.step_event(task=task, step=step, sequence=sequence)
                )
                sent_steps += 1
                sequence += 1

            if stream_formatter.is_terminal(task.status):
                yield _format_sse_event(stream_formatter.terminal_event(task=task, sequence=sequence))
                break

            if await request.is_disconnected():
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse_event(payload: ExecutionStreamEvent) -> str:
    encoded = json.dumps(jsonable_encoder(payload), ensure_ascii=False)
    return f"id: {payload.sequence}\nevent: {payload.event}\ndata: {encoded}\n\n"
