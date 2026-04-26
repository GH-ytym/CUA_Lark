"""Domain models for task state and MVP capability freeze."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import CuaAbortReason, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode


class MvpCapability(BaseModel):
    """A single frozen MVP capability record."""

    intent_type: IntentType
    cli_supported: bool
    description: str


class ExecutionTask(BaseModel):
    """Persistent shape for one orchestration task."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    user_id: str
    raw_message: str
    intent_type: IntentType = IntentType.UNKNOWN
    executor: ExecutorType = ExecutorType.NONE
    status: ExecutionStatus = ExecutionStatus.QUEUED
    cli_error_code: LarkCliErrorCode | None = None
    cua_abort_reason: CuaAbortReason | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StateMachineSpec(BaseModel):
    """Serializable state machine definition for frontend/debug views."""

    initial_state: ExecutionStatus
    terminal_states: list[ExecutionStatus]
    transitions: dict[ExecutionStatus, list[ExecutionStatus]]
