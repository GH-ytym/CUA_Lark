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
from app.services.lark_cli_service import LarkCliService

router = APIRouter(prefix="/agent", tags=["agent"])
intent_service = IntentService()
lark_cli_service = LarkCliService()

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
    structured_payload = (
        parsed.structured_command.get("payload", {})
        if isinstance(parsed.structured_command, dict)
        and isinstance(parsed.structured_command.get("payload"), dict)
        else {}
    )
    if payload.confirmed_entity_id and parsed.intent_type == IntentType.MESSAGE_SEND:
        structured_payload = dict(structured_payload)
        candidates = structured_payload.get("resolution_candidates", [])
        if isinstance(candidates, list):
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                if str(item.get("entity_id", "")).strip() != payload.confirmed_entity_id:
                    continue
                if str(item.get("entity_type", "")).strip() == "chat":
                    structured_payload["chat_id"] = payload.confirmed_entity_id
                    structured_payload["user_id"] = ""
                else:
                    structured_payload["user_id"] = payload.confirmed_entity_id
                    structured_payload["chat_id"] = ""
                structured_payload["resolved_name"] = str(item.get("name", "")).strip()
                structured_payload["resolution_status"] = "resolved"
                structured_payload["resolution_method"] = "user_confirmation"
                parsed = parsed.model_copy(
                    update={
                        "structured_command": {
                            "intent_type": parsed.intent_type.value,
                            "payload": structured_payload,
                        }
                    }
                )
                break
    needs_confirmation = (
        parsed.intent_type == IntentType.MESSAGE_SEND
        and str(structured_payload.get("resolution_status", "")).strip() == "needs_confirmation"
    )
    confirmation_message = ""
    if needs_confirmation:
        confirmation_message = "请先确认要发送给谁，再继续执行。"
    execution_status = ExecutionStatus.QUEUED
    execution_summary = "任务已受理，等待后续执行。"
    cli_error_code = ""
    cua_should_trigger = False
    execution_payload: dict[str, object] = {}
    can_execute_now = (
        parsed.selected_executor.value == "cli"
        and not needs_confirmation
        and parsed.intent_type != IntentType.UNKNOWN
    )
    if can_execute_now:
        cli_result = lark_cli_service.execute(intent=parsed.intent_type, payload=structured_payload, dry_run=False)
        execution_payload = cli_result.payload
        execution_summary = cli_result.summary
        if cli_result.success:
            execution_status = ExecutionStatus.COMPLETED
        else:
            execution_status = ExecutionStatus.CLI_FAILED
            cli_error_code = cli_result.error_code.value if cli_result.error_code is not None else ""
            triggerable_codes = {
                LarkCliErrorCode.RATE_LIMIT.value,
                LarkCliErrorCode.API_UNSUPPORTED.value,
                LarkCliErrorCode.PERMISSION_DENIED.value,
                LarkCliErrorCode.API_ERROR.value,
                LarkCliErrorCode.RESULT_INVALID.value,
                LarkCliErrorCode.USER_REQUESTED.value,
                LarkCliErrorCode.HYBRID_TASK_REQUIRED.value,
            }
            cua_should_trigger = bool(
                cli_error_code and cli_error_code in triggerable_codes
            )
    return ExecuteCommandResponse(
        task_id=str(uuid4()),
        initial_status=ExecutionStatus.QUEUED,
        selected_executor=parsed.selected_executor,
        parsed_intent=parsed.intent_type,
        intent_reason=parsed.reason,
        action_plan=parsed.action_plan,
        parse_source=parsed.parse_source,
        structured_payload=structured_payload,
        needs_confirmation=needs_confirmation,
        confirmation_message=confirmation_message,
        resolution_candidates=structured_payload.get("resolution_candidates", []),
        execution_status=execution_status,
        execution_summary=execution_summary,
        cli_error_code=cli_error_code,
        cua_should_trigger=cua_should_trigger,
        execution_payload=execution_payload,
        accepted_at=datetime.now(UTC),
    )
