"""Agent routes for MVP scope, state machine, and task acceptance."""

from fastapi import APIRouter

from app.domain.enums import (
    ALLOWED_TRANSITIONS,
    ExecutionStatus,
    IntentType,
)
from app.domain.models import MvpCapability, StateMachineSpec
from app.schemas.chat import (
    ErrorCodeCatalogEntry,
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    CuaBoundaryResponse,
    MvpScopeResponse,
    ParsePreviewResponse,
    StateMachineResponse,
)
from app.services.orchestrator import OrchestratorService
from shared.error_codes import CUA_ABORT_ERROR_CODES, error_code_catalog_payload

router = APIRouter(prefix="/agent", tags=["agent"])
orchestrator_service = OrchestratorService()
intent_service = orchestrator_service.intent_service
lark_cli_service = orchestrator_service.cli_service

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
    """Expose the CUA abort codes and shared error catalog."""
    return CuaBoundaryResponse(
        cua_abort_error_codes=list(CUA_ABORT_ERROR_CODES),
        error_code_catalog=[
            ErrorCodeCatalogEntry.model_validate(item)
            for item in error_code_catalog_payload()
        ],
    )


@router.post("/execute", response_model=ExecuteCommandResponse)
async def execute_command(payload: ExecuteCommandRequest) -> ExecuteCommandResponse:
    """Accept one command and return task acceptance payload."""
    return await orchestrator_service.execute_command(payload)
