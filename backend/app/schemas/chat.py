"""API schemas for command submission and orchestration introspection."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.enums import (
    CuaAbortReason,
    ExecutionStatus,
    ExecutorType,
    IntentType,
    LarkCliErrorCode,
)
from app.domain.models import MvpCapability, StateMachineSpec
from app.domain.models import StandardAction


class ExecuteCommandRequest(BaseModel):
    """Inbound command payload from sidebar."""

    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    conversation_type: str = Field(default="chat", max_length=32)
    context_hint: str = Field(default="", max_length=1000)
    confirmed_entity_id: str = Field(default="", max_length=128)


class ResolutionCandidate(BaseModel):
    """One candidate returned for user confirmation."""

    name: str
    entity_type: str
    entity_id: str
    score: float


class ExecuteCommandResponse(BaseModel):
    """Immediate ack returned after task creation."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    initial_status: ExecutionStatus = ExecutionStatus.QUEUED
    selected_executor: ExecutorType = ExecutorType.NONE
    parsed_intent: IntentType = IntentType.UNKNOWN
    intent_reason: str = ""
    action_plan: list[str] = Field(default_factory=list)
    parse_source: str = ""
    standard_action: StandardAction = Field(default_factory=StandardAction)
    structured_payload: dict[str, object] = Field(default_factory=dict)
    needs_confirmation: bool = False
    confirmation_message: str = ""
    resolution_candidates: list[ResolutionCandidate] = Field(default_factory=list)
    execution_status: ExecutionStatus = ExecutionStatus.QUEUED
    execution_summary: str = ""
    cli_error_code: str = ""
    cua_should_trigger: bool = False
    execution_payload: dict[str, object] = Field(default_factory=dict)
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MvpScopeResponse(BaseModel):
    """Frozen MVP capability list for sprint governance."""

    frozen: bool = True
    capabilities: list[MvpCapability]


class StateMachineResponse(BaseModel):
    """State-machine response wrapper."""

    spec: StateMachineSpec


class CuaBoundaryResponse(BaseModel):
    """Boundary rules exported from backend contract for B/C alignment."""

    cli_trigger_error_codes: list[LarkCliErrorCode]
    cua_abort_reasons: list[CuaAbortReason]


class ParsePreviewResponse(BaseModel):
    """Simple intent preview for day-3 parser iteration."""

    intent_type: IntentType
    reason: str
