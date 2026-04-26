"""Agent routes for MVP scope, state machine, and task acceptance."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter

from app.domain.enums import (
    ALLOWED_TRANSITIONS,
    CuaAbortReason,
    ExecutionStatus,
    IntentType,
    LarkCliErrorCode,
)
from app.domain.models import MvpCapability, StateMachineSpec
from app.schemas.chat import (
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    CuaBoundaryResponse,
    MvpScopeResponse,
    ParsePreviewResponse,
    StateMachineResponse,
)
from app.services.intent_service import IntentService

router = APIRouter(prefix="/agent", tags=["agent"])
intent_service = IntentService()

MVP_CAPABILITIES: list[MvpCapability] = [
    MvpCapability(
        intent_type=IntentType.MESSAGE_SEND,
        cli_supported=True,
        description="Send reminders or notifications to target chats.",
    ),
    MvpCapability(
        intent_type=IntentType.CALENDAR_RESCHEDULE,
        cli_supported=True,
        description="Reschedule one calendar event with explicit source and target time.",
    ),
    MvpCapability(
        intent_type=IntentType.DOC_CREATE,
        cli_supported=True,
        description="Create docs from fixed templates or direct instruction.",
    ),
    MvpCapability(
        intent_type=IntentType.SHEET_UPDATE,
        cli_supported=True,
        description="Update one row or one cell using deterministic coordinates.",
    ),
]


def preview_intent(message: str) -> ParsePreviewResponse:
    """Rule-based intent preview for MVP frozen scope."""
    lowered = message.lower()
    if "会议" in message or "calendar" in lowered or "meeting" in lowered:
        return ParsePreviewResponse(intent_type=IntentType.CALENDAR_RESCHEDULE, reason="calendar keyword")
    if "文档" in message or "doc" in lowered:
        return ParsePreviewResponse(intent_type=IntentType.DOC_CREATE, reason="doc keyword")
    if "表格" in message or "sheet" in lowered or "单元格" in message:
        return ParsePreviewResponse(intent_type=IntentType.SHEET_UPDATE, reason="sheet keyword")
    if "发" in message or "消息" in message or "send" in lowered:
        return ParsePreviewResponse(intent_type=IntentType.MESSAGE_SEND, reason="message keyword")
    return ParsePreviewResponse(intent_type=IntentType.UNKNOWN, reason="no MVP pattern matched")


@router.get("/mvp-scope", response_model=MvpScopeResponse)
async def get_mvp_scope() -> MvpScopeResponse:
    """Return frozen MVP capability scope for sprint governance."""
    return MvpScopeResponse(frozen=True, capabilities=MVP_CAPABILITIES)


@router.get("/state-machine", response_model=StateMachineResponse)
async def get_state_machine() -> StateMachineResponse:
    """Return the designed task state machine."""
    spec = StateMachineSpec(
        initial_state=ExecutionStatus.QUEUED,
        terminal_states=[
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELED,
        ],
        transitions={status: sorted(list(next_states)) for status, next_states in ALLOWED_TRANSITIONS.items()},
    )
    return StateMachineResponse(spec=spec)


@router.get("/cua-boundary", response_model=CuaBoundaryResponse)
async def get_cua_boundary() -> CuaBoundaryResponse:
    """Expose CUA trigger and abort codes aligned with cua/trigger_rules.py."""
    return CuaBoundaryResponse(
        cli_trigger_error_codes=[
            LarkCliErrorCode.RATE_LIMIT,
            LarkCliErrorCode.API_UNSUPPORTED,
            LarkCliErrorCode.PERMISSION_DENIED,
            LarkCliErrorCode.API_ERROR,
            LarkCliErrorCode.RESULT_INVALID,
            LarkCliErrorCode.USER_REQUESTED,
            LarkCliErrorCode.HYBRID_TASK_REQUIRED,
        ],
        cua_abort_reasons=[
            CuaAbortReason.LOW_CONFIDENCE,
            CuaAbortReason.TIMEOUT,
            CuaAbortReason.INTERFACE_CHANGED,
            CuaAbortReason.MAX_RETRY_EXCEEDED,
            CuaAbortReason.SECURITY_RISK,
            CuaAbortReason.USER_INTERRUPTED,
            CuaAbortReason.MULTI_MONITOR_UNSUPPORTED,
        ],
    )


@router.post("/execute", response_model=ExecuteCommandResponse)
async def execute_command(payload: ExecuteCommandRequest) -> ExecuteCommandResponse:
    """Accept one command and return task acceptance payload."""
    parsed = await intent_service.parse(message=payload.message, context_hint=payload.context_hint)
    return ExecuteCommandResponse(
        task_id=str(uuid4()),
        initial_status=ExecutionStatus.QUEUED,
        selected_executor=parsed.selected_executor,
        parsed_intent=parsed.intent_type,
        intent_reason=parsed.reason,
        action_plan=parsed.action_plan,
        accepted_at=datetime.now(UTC),
    )
