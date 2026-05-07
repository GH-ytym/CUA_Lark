"""Execution detail schemas exposed to frontend and integration tooling."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import ExecutionStatus, IntentType
from app.domain.models import ExecutorResult, PlannedActionItem, StandardAction, TaskStep


class ExecutionDetailResponse(BaseModel):
    """Serializable execution record for one task."""

    task_id: str
    session_id: str
    user_id: str
    raw_message: str
    status: ExecutionStatus
    intent_type: IntentType
    standard_action: StandardAction = Field(default_factory=StandardAction)
    planned_actions: list[PlannedActionItem] = Field(default_factory=list)
    needs_confirmation: bool = False
    executor_result: ExecutorResult | None = None
    steps: list[TaskStep] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExecutionStreamEvent(BaseModel):
    """One ordered SSE payload consumed by the React sidebar."""

    event: Literal["snapshot", "step", "status", "heartbeat", "terminal", "error"]
    task_id: str
    status: ExecutionStatus
    sequence: int
    summary: str = ""
    step: TaskStep | None = None
    detail: ExecutionDetailResponse | None = None
    emitted_at: datetime


class ExecutionActionResponse(BaseModel):
    """Response returned by C-side control actions such as cancel."""

    task_id: str
    status: ExecutionStatus
    canceled: bool = False
    summary: str
    detail: ExecutionDetailResponse
