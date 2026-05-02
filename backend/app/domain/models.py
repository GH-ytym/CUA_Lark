"""Domain models for task state and MVP capability freeze."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import (
    CapabilityId,
    CuaAbortReason,
    ExecutionStatus,
    ExecutorType,
    IntentType,
    LarkCliErrorCode,
)


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


class StandardAction(BaseModel):
    """Normalized action contract emitted by intent parsing."""

    capability_id: CapabilityId = CapabilityId.UNKNOWN
    payload: dict[str, object] = Field(default_factory=dict)
    executor_hint: ExecutorType = ExecutorType.NONE
    intent_type: IntentType = IntentType.UNKNOWN


class ExecutorResult(BaseModel):
    """Unified result shape returned by all executors."""

    executor: ExecutorType
    success: bool
    status: ExecutionStatus
    summary: str
    payload: dict[str, object] = Field(default_factory=dict)
    error_code: str = ""
    duration_ms: float = 0.0


class TaskStep(BaseModel):
    """One recorded orchestration step."""

    name: str
    status: ExecutionStatus
    summary: str = ""
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OrchestrationTask(BaseModel):
    """In-memory task record produced by the v1 orchestrator."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    user_id: str
    raw_message: str
    status: ExecutionStatus = ExecutionStatus.QUEUED
    intent_type: IntentType = IntentType.UNKNOWN
    standard_action: StandardAction = Field(default_factory=StandardAction)
    executor_result: ExecutorResult | None = None
    needs_confirmation: bool = False
    steps: list[TaskStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StateMachineSpec(BaseModel):
    """Serializable state machine definition for frontend/debug views."""

    initial_state: ExecutionStatus
    terminal_states: list[ExecutionStatus]
    transitions: dict[ExecutionStatus, list[ExecutionStatus]]
