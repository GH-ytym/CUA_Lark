import asyncio

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import ExecutorResult, StandardAction
from app.schemas.chat import ExecuteCommandRequest
from app.services.intent_service import IntentDecision
from app.services.orchestrator import OrchestratorService


def request(message: str = "给项目群发今晚发布", confirmed_entity_id: str = "") -> ExecuteCommandRequest:
    return ExecuteCommandRequest(
        message=message,
        session_id="s1",
        user_id="u1",
        conversation_type="chat",
        context_hint="",
        confirmed_entity_id=confirmed_entity_id,
    )


def decision(payload: dict[str, object]) -> IntentDecision:
    return IntentDecision(
        intent_type=IntentType.MESSAGE_SEND,
        reason="对象已解析，可直接发送",
        action_plan=["定位接收对象", "发送消息", "回执"],
        selected_executor=ExecutorType.CLI,
        parse_source="rules_resolve_first",
        standard_action=StandardAction(
            capability_id=CapabilityId.IM_MESSAGE_SEND,
            payload=payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        ),
        structured_command={"intent_type": IntentType.MESSAGE_SEND.value, "payload": payload},
    )


def test_orchestrator_creates_task_and_executes_cli() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "项目群",
        "chat_id": "oc_proj",
        "user_id": "",
        "text": "今晚发布",
        "resolution_status": "resolved",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return decision(payload)

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={"domain": "message", "dry_run": False, "steps": [{"exit_code": 0}], "error": None},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request()))
    task = service.get_task(response.task_id)

    assert response.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.execution_summary == "executed 1 cli invocation(s)"
    assert task is not None
    assert [step.name for step in task.steps] == ["task_created", "intent_parsed", "cli_started", "cli_finished"]


def test_orchestrator_keeps_confirmation_queued() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "王",
        "chat_id": "",
        "user_id": "",
        "text": "你好",
        "resolution_status": "needs_confirmation",
        "resolution_candidates": [
            {"name": "王建国", "entity_type": "contact", "entity_id": "ou_a", "score": 0.91},
        ],
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return decision(payload)

    def should_not_execute(*_: object, **__: object) -> ExecutorResult:
        raise AssertionError("CLI should not run before user confirms")

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = should_not_execute  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("给王发你好")))

    assert response.needs_confirmation is True
    assert response.execution_status == ExecutionStatus.QUEUED
    assert response.resolution_candidates[0].entity_id == "ou_a"


def test_orchestrator_maps_cli_failure_to_cua_trigger() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "项目群",
        "chat_id": "oc_proj",
        "user_id": "",
        "text": "今晚发布",
        "resolution_status": "resolved",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return decision(payload)

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary="cli command failed",
            error_code="permission_denied",
            payload={
                "domain": "message",
                "dry_run": False,
                "steps": [{"exit_code": 2}],
                "error": {"code": "permission_denied"},
            },
        )

    def fake_cua_execute_fallback(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="cua fallback executed",
            payload={"mode": "cua_fallback", "cua_response": {"success": True}},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]
    service.cua_service.execute_fallback = fake_cua_execute_fallback  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request()))
    task = service.get_task(response.task_id)

    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.cli_error_code == "permission_denied"
    assert response.cua_should_trigger is True
    assert response.execution_summary == "cua fallback executed"
    assert response.execution_payload["mode"] == "cua_fallback"
    assert task is not None
    assert [step.name for step in task.steps] == [
        "task_created",
        "intent_parsed",
        "cli_started",
        "cli_finished",
        "cua_started",
        "cua_finished",
    ]


def test_orchestrator_marks_failed_when_cua_fallback_fails() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "项目群",
        "chat_id": "oc_proj",
        "user_id": "",
        "text": "今晚发布",
        "resolution_status": "resolved",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return decision(payload)

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary="cli command failed",
            error_code="permission_denied",
            payload={"domain": "message", "error": {"code": "permission_denied"}},
        )

    def fake_cua_execute_fallback(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=False,
            status=ExecutionStatus.FAILED,
            summary="cua fallback failed",
            payload={"mode": "cua_fallback", "error": {"message": "window not found"}},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]
    service.cua_service.execute_fallback = fake_cua_execute_fallback  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request()))

    assert response.execution_status == ExecutionStatus.FAILED
    assert response.cua_should_trigger is True
    assert response.execution_payload["mode"] == "cua_fallback"
    assert response.execution_payload["error"]["message"] == "window not found"


def test_should_trigger_cua_aligns_with_trigger_rule_evaluator() -> None:
    assert OrchestratorService._load_trigger_rule_evaluator() is not None
    for error_code in LarkCliErrorCode:
        assert OrchestratorService._should_trigger_cua(
            error_code.value,
            execution_payload={"error": {"code": error_code.value}},
            success=False,
        )

    assert (
        OrchestratorService._should_trigger_cua(
            "",
            execution_payload={"steps": [{"exit_code": 0}]},
            success=True,
        )
        is False
    )
