import asyncio

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import ExecutorResult, StandardAction
from app.schemas.chat import ExecuteCommandRequest
from app.services.intent_service import IntentDecision
from app.services.orchestrator import OrchestratorService
from shared.error_codes import UnifiedErrorCode


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
            error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
            payload={
                "domain": "message",
                "dry_run": False,
                "steps": [{"exit_code": 2}],
                "error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"},
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
    assert response.cli_error_code == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert response.cua_error_code is None
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
            error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
            payload={"domain": "message", "error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"}},
        )

    def fake_cua_execute_fallback(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=False,
            status=ExecutionStatus.FAILED,
            summary="cua fallback failed",
            payload={
                "mode": "cua_fallback",
                "error": {
                    "code": int(UnifiedErrorCode.EXECUTION_ERROR),
                    "name": "cua_execution_error",
                    "message": "window not found",
                },
            },
            error_code=int(UnifiedErrorCode.EXECUTION_ERROR),
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]
    service.cua_service.execute_fallback = fake_cua_execute_fallback  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request()))

    assert response.execution_status == ExecutionStatus.FAILED
    assert response.cua_should_trigger is True
    assert response.cli_error_code == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert response.cua_error_code == int(UnifiedErrorCode.EXECUTION_ERROR)
    assert response.execution_payload["mode"] == "cua_fallback"
    assert response.execution_payload["error"]["message"] == "window not found"


def test_should_trigger_cua_uses_standard_error_or_failure_status() -> None:
    assert OrchestratorService._should_trigger_cua(
        int(UnifiedErrorCode.PERMISSION_DENIED),
        execution_payload={"error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED)}},
        success=False,
    )
    assert (
        OrchestratorService._should_trigger_cua(
            None,
            execution_payload={"steps": [{"exit_code": 0}]},
            success=True,
        )
        is False
    )
    assert OrchestratorService._should_trigger_cua(
        None,
        execution_payload={"summary": "executor failed without a standard code"},
        success=False,
    )
    assert (
        OrchestratorService._should_trigger_cua(
            int(UnifiedErrorCode.NONE),
            execution_payload={},
            success=False,
        )
        is False
    )


def test_orchestrator_structured_error_code_hands_off_to_cua_without_cli() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "刚刚那个人",
        "chat_id": "",
        "user_id": "",
        "text": "hello",
        "resolution_status": "resolved",
    }
    action = StandardAction(
        capability_id=CapabilityId.IM_MESSAGE_SEND,
        payload=payload,
        executor_hint=ExecutorType.CLI,
        intent_type=IntentType.MESSAGE_SEND,
        handoff_error_code=int(UnifiedErrorCode.HANDOFF_REQUIRED),
        handoff_reason="target must be selected from recent Feishu UI context",
    )
    cli_called = False
    cua_calls: list[dict[str, object]] = []

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="requires UI context",
            action_plan=["handoff to CUA"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_plan",
            standard_action=action,
            structured_command={"intent_type": IntentType.MESSAGE_SEND.value, "payload": payload},
        )

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        nonlocal cli_called
        cli_called = True
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="should not run",
        )

    def fake_cua_execute_fallback(*_: object, **kwargs: object) -> ExecutorResult:
        cua_calls.append(dict(kwargs))
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="cua fallback executed",
            payload={"mode": "cua_fallback"},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]
    service.cua_service.execute_fallback = fake_cua_execute_fallback  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request(message="给刚刚那个人发消息：hello")))
    task = service.get_task(response.task_id)

    assert cli_called is False
    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.cua_should_trigger is True
    assert response.cli_error_code is None
    assert response.handoff_error_code == int(UnifiedErrorCode.HANDOFF_REQUIRED)
    assert response.execution_payload["mode"] == "cua_fallback"
    assert cua_calls[0]["cli_error_code"] == int(UnifiedErrorCode.HANDOFF_REQUIRED)
    assert cua_calls[0]["trigger_source"] == "structured"
    assert cua_calls[0]["cli_payload"]["mode"] == "structured_handoff"
    assert task is not None
    assert [step.name for step in task.steps] == [
        "task_created",
        "intent_parsed",
        "cua_started",
        "cua_finished",
    ]


def test_orchestrator_multitask_success_auto_advances_in_order() -> None:
    service = OrchestratorService()
    payload_1 = {
        "chat_hint": "梅家济",
        "chat_id": "",
        "user_id": "ou_mei",
        "text": "mjj",
        "resolution_status": "resolved",
    }
    payload_2 = {
        "chat_hint": "刘海俊",
        "chat_id": "",
        "user_id": "ou_liu",
        "text": "快写代码",
        "resolution_status": "resolved",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        action_1 = StandardAction(
            capability_id=CapabilityId.IM_MESSAGE_SEND,
            payload=payload_1,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
        action_2 = StandardAction(
            capability_id=CapabilityId.IM_MESSAGE_SEND,
            payload=payload_2,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
        return IntentDecision(
            intent_type=IntentType.MULTI_TASK,
            reason="按顺序发送两条消息",
            action_plan=["发给梅家济", "发给刘海俊"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_multi_plan",
            standard_action=action_1,
            structured_command={
                "intent_type": IntentType.MULTI_TASK.value,
                "tasks": [
                    {"raw_message": "给梅家济发mjj", "capability_id": "im.message_send", "payload": payload_1},
                    {"raw_message": "给刘海俊发快写代码", "capability_id": "im.message_send", "payload": payload_2},
                ],
            },
            planned_actions=[action_1, action_2],
            task_clauses=["给梅家济发mjj", "给刘海俊发快写代码"],
        )

    execute_calls: list[dict[str, object]] = []

    def fake_execute_action(*_: object, **kwargs: object) -> ExecutorResult:
        action = kwargs["action"]
        assert isinstance(action, StandardAction)
        execute_calls.append(dict(action.payload))
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={"domain": "message", "dry_run": False, "steps": [{"exit_code": 0}], "error": None},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("给梅家济发mjj，然后给刘海俊发快写代码")))

    assert response.execution_status == ExecutionStatus.COMPLETED
    assert len(execute_calls) == 2
    assert execute_calls[0]["text"] == "mjj"
    assert execute_calls[1]["text"] == "快写代码"
    assert str(execute_calls[0]["idempotency_key"]).startswith("fsagent-")
    assert str(execute_calls[1]["idempotency_key"]).startswith("fsagent-")
    assert execute_calls[0]["idempotency_key"] != execute_calls[1]["idempotency_key"]


def test_orchestrator_cli_failure_does_not_retry_and_hands_off_once_to_cua() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "项目群",
        "chat_id": "oc_proj",
        "user_id": "",
        "text": "今晚发布",
        "resolution_status": "resolved",
    }
    cua_calls: list[dict[str, object]] = []
    cli_call_count = 0

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return decision(payload)

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        nonlocal cli_call_count
        cli_call_count += 1
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary="cli command failed",
            error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
            payload={
                "domain": "message",
                "dry_run": False,
                "steps": [{"exit_code": 2}],
                "error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"},
            },
        )

    def fake_cua_execute_fallback(*_: object, **kwargs: object) -> ExecutorResult:
        cua_calls.append(
            {
                "cli_error_code": kwargs.get("cli_error_code"),
                "raw_message": kwargs.get("raw_message"),
                "session_id": kwargs.get("session_id"),
                "chain_id": kwargs.get("chain_id"),
                "retry_attempts": kwargs.get("retry_attempts"),
            }
        )
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

    assert cli_call_count == 1
    assert len(cua_calls) == 1
    assert cua_calls[0]["cli_error_code"] == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert cua_calls[0]["session_id"] == "s1"
    assert isinstance(cua_calls[0]["chain_id"], str)
    assert cua_calls[0]["retry_attempts"] == service.retry_service.policy.max_attempts
    assert response.cua_should_trigger is True
    assert response.execution_status == ExecutionStatus.COMPLETED


def test_orchestrator_preserves_retry_context_when_handing_off_to_cua() -> None:
    service = OrchestratorService()
    payload = {
        "chat_hint": "项目群",
        "chat_id": "oc_proj",
        "user_id": "",
        "text": "今晚发布",
        "resolution_status": "resolved",
    }
    cli_call_count = 0
    cua_calls: list[dict[str, object]] = []

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return decision(payload)

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        nonlocal cli_call_count
        cli_call_count += 1
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary="cli timeout",
            error_code=int(UnifiedErrorCode.TIMEOUT),
            payload={
                "domain": "message",
                "dry_run": False,
                "steps": [],
                "error": {"code": int(UnifiedErrorCode.TIMEOUT), "name": "operation_timeout"},
            },
        )

    def fake_cua_execute_fallback(*_: object, **kwargs: object) -> ExecutorResult:
        cua_calls.append(dict(kwargs))
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=False,
            status=ExecutionStatus.FAILED,
            summary="cua fallback failed",
            payload={"mode": "cua_fallback"},
            error_code=int(UnifiedErrorCode.EXECUTION_ERROR),
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]
    service.cua_service.execute_fallback = fake_cua_execute_fallback  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request()))

    assert cli_call_count == service.retry_service.policy.max_attempts
    assert len(cua_calls) == 1
    assert cua_calls[0]["cli_error_code"] == int(UnifiedErrorCode.TIMEOUT)
    assert cua_calls[0]["retry_attempts"] == service.retry_service.policy.max_attempts
    assert cua_calls[0]["session_id"] == "s1"
    assert response.execution_status == ExecutionStatus.FAILED


def test_orchestrator_docs_failure_reuses_existing_fallback_flow() -> None:
    service = OrchestratorService()
    payload = {
        "title": "小组消息跟进",
        "content": "记录群消息重点",
        "folder_token": "",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.DOC_CREATE,
            reason="docs create request",
            action_plan=["draft title", "create doc"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_plan",
            standard_action=StandardAction(
                capability_id=CapabilityId.DOC_CREATE,
                payload=payload,
                executor_hint=ExecutorType.CLI,
                intent_type=IntentType.DOC_CREATE,
            ),
            structured_command={"intent_type": IntentType.DOC_CREATE.value, "payload": payload},
        )

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary="cli command failed",
            error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
            payload={
                "domain": "doc_sheet",
                "dry_run": False,
                "steps": [{"exit_code": 2}],
                "error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"},
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

    response = asyncio.run(service.execute_command(request("创建文档《小组消息跟进》")))
    task = service.get_task(response.task_id)

    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.cli_error_code == int(UnifiedErrorCode.PERMISSION_DENIED)
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


def test_orchestrator_executes_calendar_create_cli() -> None:
    service = OrchestratorService()
    payload = {
        "title": "Project review",
        "start_time": "2026-05-06T15:00:00+08:00",
        "end_time": "2026-05-06T16:00:00+08:00",
        "attendee_ids": ["ou_alex"],
        "identity": "user",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        action = StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload=payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
        return IntentDecision(
            intent_type=IntentType.CALENDAR_RESCHEDULE,
            reason="calendar create request",
            action_plan=["extract fields", "create calendar event"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_plan",
            standard_action=action,
            planned_actions=[action],
            structured_command={"intent_type": IntentType.CALENDAR_RESCHEDULE.value, "payload": payload},
        )

    execute_calls: list[StandardAction] = []

    def fake_execute_action(*_: object, **kwargs: object) -> ExecutorResult:
        action = kwargs["action"]
        assert isinstance(action, StandardAction)
        execute_calls.append(action)
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={
                "domain": "calendar",
                "dry_run": False,
                "steps": [{"exit_code": 0, "parsed": {"event_id": "evt_123"}}],
                "error": None,
            },
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("create project review tomorrow at 15:00")))
    task = service.get_task(response.task_id)

    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.standard_action.capability_id == CapabilityId.CALENDAR_CREATE
    assert execute_calls[0].capability_id == CapabilityId.CALENDAR_CREATE
    assert response.execution_payload["domain"] == "calendar"
    assert task is not None
    assert [step.name for step in task.steps] == ["task_created", "intent_parsed", "cli_started", "cli_finished"]


def test_orchestrator_calendar_reschedule_without_event_id_stays_structured_only() -> None:
    service = OrchestratorService()
    payload = {
        "event_hint": "Project review",
        "source_time": "2026-05-06T15:00:00+08:00",
        "target_time": "2026-05-06T16:00:00+08:00",
        "target_start_time": "2026-05-06T16:00:00+08:00",
        "target_end_time": "2026-05-06T17:00:00+08:00",
        "event_id": "",
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        action = StandardAction(
            capability_id=CapabilityId.CALENDAR_RESCHEDULE,
            payload=payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
        return IntentDecision(
            intent_type=IntentType.CALENDAR_RESCHEDULE,
            reason="calendar reschedule request",
            action_plan=["extract event hint", "hold for safe event lookup"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_plan",
            standard_action=action,
            planned_actions=[action],
            structured_command={"intent_type": IntentType.CALENDAR_RESCHEDULE.value, "payload": payload},
        )

    def should_not_execute(*_: object, **__: object) -> ExecutorResult:
        raise AssertionError("calendar.reschedule without event_id should stay structured-only")

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = should_not_execute  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("move project review to 16:00")))

    assert response.execution_status == ExecutionStatus.QUEUED
    assert response.execution_payload["mode"] == "structured_only"
    assert response.execution_payload["capability_id"] == CapabilityId.CALENDAR_RESCHEDULE.value


def test_orchestrator_retries_transient_cli_failure_then_succeeds() -> None:
    service = OrchestratorService()
    payload = {
        "title": "Project review",
        "start_time": "2026-05-06T15:00:00+08:00",
        "end_time": "2026-05-06T16:00:00+08:00",
    }
    cli_call_count = 0

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        action = StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload=payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
        return IntentDecision(
            intent_type=IntentType.CALENDAR_RESCHEDULE,
            reason="calendar create request",
            action_plan=["create calendar event"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_plan",
            standard_action=action,
            planned_actions=[action],
            structured_command={"intent_type": IntentType.CALENDAR_RESCHEDULE.value, "payload": payload},
        )

    def fake_execute_action(*_: object, **__: object) -> ExecutorResult:
        nonlocal cli_call_count
        cli_call_count += 1
        if cli_call_count == 1:
            return ExecutorResult(
                executor=ExecutorType.CLI,
                success=False,
                status=ExecutionStatus.CLI_FAILED,
                summary="cli execution timeout: 30s",
                error_code=int(UnifiedErrorCode.TIMEOUT),
                payload={
                    "domain": "calendar",
                    "dry_run": False,
                    "steps": [],
                    "error": {"code": int(UnifiedErrorCode.TIMEOUT), "name": "operation_timeout"},
                },
            )
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={"domain": "calendar", "dry_run": False, "steps": [{"exit_code": 0}], "error": None},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("create project review tomorrow at 15:00")))

    assert cli_call_count == 2
    assert response.execution_status == ExecutionStatus.COMPLETED
    assert response.cli_error_code is None


def test_orchestrator_blocks_calendar_confirmation_before_cli() -> None:
    service = OrchestratorService()
    payload = {
        "title": "Project review",
        "start_time": "2026-05-06T15:00:00+08:00",
        "end_time": "2026-05-06T16:00:00+08:00",
        "attendees": ["Alex"],
        "attendee_ids": [],
        "resolution_status": "needs_confirmation",
        "resolution_candidates": [
            {"name": "Alex Chen", "entity_type": "contact", "entity_id": "ou_alex", "score": 0.8},
        ],
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        action = StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload=payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
        return IntentDecision(
            intent_type=IntentType.CALENDAR_RESCHEDULE,
            reason="calendar create request needs attendee confirmation",
            action_plan=["resolve attendee"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_plan",
            standard_action=action,
            planned_actions=[action],
            structured_command={"intent_type": IntentType.CALENDAR_RESCHEDULE.value, "payload": payload},
        )

    def should_not_execute(*_: object, **__: object) -> ExecutorResult:
        raise AssertionError("calendar create should not run before attendee confirmation")

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = should_not_execute  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("create project review with Alex")))

    assert response.needs_confirmation is True
    assert response.execution_status == ExecutionStatus.QUEUED
    assert response.resolution_candidates[0].entity_id == "ou_alex"


def test_orchestrator_multitask_message_doc_calendar_executes_in_order() -> None:
    service = OrchestratorService()
    message_payload = {
        "chat_hint": "Alex",
        "chat_id": "",
        "user_id": "ou_alex",
        "text": "Reminder sent.",
        "resolution_status": "resolved",
    }
    doc_payload = {"title": "Review notes", "content": "Agenda", "folder_token": ""}
    calendar_payload = {
        "title": "Project review",
        "start_time": "2026-05-06T15:00:00+08:00",
        "end_time": "2026-05-06T16:00:00+08:00",
        "attendee_ids": ["ou_alex"],
    }

    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        action_1 = StandardAction(
            capability_id=CapabilityId.IM_MESSAGE_SEND,
            payload=message_payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
        action_2 = StandardAction(
            capability_id=CapabilityId.DOC_CREATE,
            payload=doc_payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.DOC_CREATE,
        )
        action_3 = StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload=calendar_payload,
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
        return IntentDecision(
            intent_type=IntentType.MULTI_TASK,
            reason="plan message, doc, and calendar in order",
            action_plan=["send message", "create doc", "create event"],
            selected_executor=ExecutorType.CLI,
            parse_source="qwen_multi_plan",
            standard_action=action_1,
            planned_actions=[action_1, action_2, action_3],
            task_clauses=[
                "send Alex a reminder",
                "create Review notes",
                "schedule Project review tomorrow at 3pm",
            ],
            structured_command={
                "intent_type": IntentType.MULTI_TASK.value,
                "tasks": [
                    {"raw_message": "send Alex a reminder", "capability_id": "im.message_send", "payload": message_payload},
                    {"raw_message": "create Review notes", "capability_id": "docs.create", "payload": doc_payload},
                    {"raw_message": "schedule Project review tomorrow at 3pm", "capability_id": "calendar.create", "payload": calendar_payload},
                ],
            },
        )

    executed: list[CapabilityId] = []

    def fake_execute_action(*_: object, **kwargs: object) -> ExecutorResult:
        action = kwargs["action"]
        assert isinstance(action, StandardAction)
        executed.append(action.capability_id)
        return ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={"domain": "mixed", "dry_run": False, "steps": [{"exit_code": 0}], "error": None},
        )

    service.intent_service.parse = fake_parse  # type: ignore[method-assign]
    service.cli_service.execute_action = fake_execute_action  # type: ignore[method-assign]

    response = asyncio.run(service.execute_command(request("send Alex, create doc, schedule review")))
    task = service.get_task(response.task_id)

    assert response.execution_status == ExecutionStatus.COMPLETED
    assert executed == [CapabilityId.IM_MESSAGE_SEND, CapabilityId.DOC_CREATE, CapabilityId.CALENDAR_CREATE]
    assert response.execution_payload["mode"] == "multi_task"
    assert response.execution_payload["completed_count"] == 3
    assert task is not None
    assert task.executor_result is not None
    assert task.executor_result.summary == "planned 3 tasks; 3 completed, 0 structured-only"
    assert task.executor_result.payload["mode"] == "multi_task"
