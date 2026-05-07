from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult, StandardAction
from app.services.cli_failure_diagnosis_service import CliFailureDiagnosisService
from shared.error_codes import UnifiedErrorCode


def test_normalize_llm_payload_accepts_current_ui_context_aliases() -> None:
    diagnosis = CliFailureDiagnosisService._normalize_llm_payload(  # noqa: SLF001
        {
            "failure_reason": "need_current_ui_context",
            "fallback_to_cua": True,
        }
    )

    assert diagnosis is not None
    assert diagnosis.category == "requires_ui_context"
    assert diagnosis.should_fallback_to_cua is True
    assert diagnosis.raw_payload["failure_reason"] == "need_current_ui_context"


def test_invalid_input_with_current_ui_reference_falls_back_to_cua() -> None:
    service = CliFailureDiagnosisService()
    action = StandardAction(
        capability_id=CapabilityId.IM_MESSAGE_SEND,
        payload={"text": "hello", "resolution_reason": "missing_message_target"},
        executor_hint=ExecutorType.CLI,
        intent_type=IntentType.MESSAGE_SEND,
    )
    result = ExecutorResult(
        executor=ExecutorType.CLI,
        success=False,
        status=ExecutionStatus.CLI_FAILED,
        summary="message recipient is missing",
        payload={},
        error_code=int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT),
    )

    diagnosis = service._rule_based_diagnosis(  # noqa: SLF001
        action=action,
        result=result,
        raw_message="点击“消息”栏，给最上面的那个联系人发消息：hello",
    )

    assert diagnosis.category == "requires_ui_context"
    assert diagnosis.should_fallback_to_cua is True
