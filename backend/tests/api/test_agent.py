from fastapi.testclient import TestClient
import time

from app.domain.enums import ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult
from app.main import create_app
from app.services.cli_failure_diagnosis_service import CliFailureDiagnosis
from app.services.intent_service import IntentDecision
from shared.error_codes import UnifiedErrorCode


def wait_for_terminal_detail(client: TestClient, task_id: str, timeout_seconds: float = 2.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_detail: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/executions/{task_id}")
        assert response.status_code == 200
        last_detail = response.json()
        if last_detail["status"] in {"completed", "failed", "canceled"}:
            return last_detail
        time.sleep(0.02)
    assert last_detail is not None
    return last_detail


def test_execute_hands_off_ambiguous_target_to_cua(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="候选存在，需要切换到 CUA",
            action_plan=["定位接收对象", "切换到 CUA", "发送消息"],
            selected_executor=ExecutorType.CLI,
            parse_source="rules_resolve_first",
            structured_command={
                "intent_type": IntentType.MESSAGE_SEND.value,
                "payload": {
                    "chat_hint": "王",
                    "chat_id": "",
                    "user_id": "",
                    "text": "你好",
                    "resolution_status": "handoff_required",
                    "handoff_error_code": int(UnifiedErrorCode.HANDOFF_REQUIRED),
                    "handoff_reason": "recipient resolution requires current Feishu UI context",
                    "resolution_candidates": [
                        {"name": "王建国", "entity_type": "contact", "entity_id": "ou_a", "score": 0.91},
                        {"name": "王小明", "entity_type": "contact", "entity_id": "ou_b", "score": 0.88},
                    ],
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
    async def fake_diagnose(*_: object, **__: object) -> CliFailureDiagnosis:
        return CliFailureDiagnosis(
            category="requires_ui_context",
            should_fallback_to_cua=True,
            confidence=0.95,
            reason="ambiguous recipient requires current Feishu UI context",
            user_message="模型判断需要当前飞书界面确认目标对象，准备切换到 CUA 接管。",
        )

    monkeypatch.setattr(agent.orchestrator_service.diagnosis_service, "diagnose", fake_diagnose)
    monkeypatch.setattr(
        agent.orchestrator_service.cua_service,
        "execute_fallback",
        lambda *_, **__: ExecutorResult(
            executor=ExecutorType.CUA,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="cua fallback executed",
            payload={"mode": "cua_fallback"},
        ),
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/agent/execute",
        json={
            "message": "给王发你好",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "queued"
    detail = wait_for_terminal_detail(client, data["task_id"])
    assert detail["needs_confirmation"] is False
    assert detail["status"] == "completed"
    assert detail["executor_result"]["payload"]["mode"] == "cua_fallback"


def test_get_cua_boundary_returns_integer_catalog() -> None:
    client = TestClient(create_app())
    response = client.get("/api/agent/cua-boundary")

    assert response.status_code == 200
    data = response.json()
    assert data["cua_abort_error_codes"] == [6, 8, 9]
    assert any(item["code"] == 3 and item["name"] == "PERMISSION_DENIED" for item in data["error_code_catalog"])


def test_execute_does_not_support_confirmed_entity_id_resume(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="候选存在，需要切换到 CUA",
            action_plan=["定位接收对象", "切换到 CUA", "发送消息"],
            selected_executor=ExecutorType.CLI,
            parse_source="rules_resolve_first",
            structured_command={
                "intent_type": IntentType.MESSAGE_SEND.value,
                "payload": {
                    "chat_hint": "项目",
                    "chat_id": "",
                    "user_id": "",
                    "text": "今晚发布",
                    "resolution_status": "handoff_required",
                    "handoff_error_code": int(UnifiedErrorCode.HANDOFF_REQUIRED),
                    "resolution_candidates": [
                        {"name": "项目群", "entity_type": "chat", "entity_id": "oc_proj", "score": 0.93},
                    ],
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
    async def fake_diagnose(*_: object, **__: object) -> CliFailureDiagnosis:
        return CliFailureDiagnosis(
            category="requires_ui_context",
            should_fallback_to_cua=True,
            confidence=0.95,
            reason="confirmed entity resume is not supported, current Feishu UI context is required",
            user_message="模型判断需要当前飞书界面上下文，准备切换到 CUA 接管。",
        )

    monkeypatch.setattr(agent.orchestrator_service.diagnosis_service, "diagnose", fake_diagnose)
    monkeypatch.setattr(
        agent.orchestrator_service.cua_service,
        "execute_fallback",
        lambda *_, **__: ExecutorResult(
            executor=ExecutorType.CUA,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="cua fallback executed",
            payload={"mode": "cua_fallback"},
        ),
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/agent/execute",
        json={
            "message": "给项目发今晚发布",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
            "confirmed_entity_id": "oc_proj",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "queued"
    detail = wait_for_terminal_detail(client, data["task_id"])
    assert detail["needs_confirmation"] is False
    assert detail["status"] == "completed"
    assert detail["executor_result"]["payload"]["mode"] == "cua_fallback"


def test_execute_runs_cli_when_already_resolved(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="对象已解析，可直接发送",
            action_plan=["定位接收对象", "发送消息", "回执"],
            selected_executor=ExecutorType.CLI,
            parse_source="rules_resolve_first",
            structured_command={
                "intent_type": IntentType.MESSAGE_SEND.value,
                "payload": {
                    "chat_hint": "项目群",
                    "chat_id": "oc_proj",
                    "user_id": "",
                    "text": "今晚发布",
                    "resolution_status": "resolved",
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
    monkeypatch.setattr(
        agent.lark_cli_service,
        "execute_action",
        lambda *_, **__: ExecutorResult(
            executor=ExecutorType.CLI,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="executed 1 cli invocation(s)",
            payload={"domain": "message", "dry_run": False, "steps": [{"exit_code": 0}], "error": None},
        ),
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/agent/execute",
        json={
            "message": "给项目群发今晚发布",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "queued"
    detail = wait_for_terminal_detail(client, data["task_id"])
    assert detail["status"] == "completed"
    assert detail["executor_result"]["summary"] == "executed 1 cli invocation(s)"
    assert detail["executor_result"]["executor"] == "cli"


def test_execute_runs_cua_fallback_when_cli_failed(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="对象已解析，可直接发送",
            action_plan=["定位接收对象", "发送消息", "回执"],
            selected_executor=ExecutorType.CLI,
            parse_source="rules_resolve_first",
            structured_command={
                "intent_type": IntentType.MESSAGE_SEND.value,
                "payload": {
                    "chat_hint": "项目群",
                    "chat_id": "oc_proj",
                    "user_id": "",
                    "text": "今晚发布",
                    "resolution_status": "resolved",
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
    monkeypatch.setattr(
        agent.lark_cli_service,
        "execute_action",
        lambda *_, **__: ExecutorResult(
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
        ),
    )
    async def fake_diagnose(*_: object, **__: object) -> CliFailureDiagnosis:
        return CliFailureDiagnosis(
            category="permission_denied",
            should_fallback_to_cua=True,
            confidence=0.91,
            reason="permission failure can be retried through Feishu desktop UI",
            user_message="模型判断 CLI 权限不足，准备切换到 CUA 接管桌面飞书继续尝试。",
        )

    monkeypatch.setattr(agent.orchestrator_service.diagnosis_service, "diagnose", fake_diagnose)
    monkeypatch.setattr(
        agent.orchestrator_service.cua_service,
        "execute_fallback",
        lambda *_, **__: ExecutorResult(
            executor=ExecutorType.CUA,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="cua fallback executed",
            payload={
                "mode": "cua_fallback",
                "cua_response": {"success": True, "message": "ok"},
            },
        ),
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/agent/execute",
        json={
            "message": "给项目群发今晚发布",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "queued"
    detail = wait_for_terminal_detail(client, data["task_id"])
    assert detail["status"] == "completed"
    assert detail["executor_result"]["error_code"] is None
    assert detail["executor_result"]["summary"] == "cua fallback executed"
    assert detail["executor_result"]["payload"]["mode"] == "cua_fallback"
    assert detail["executor_result"]["payload"]["cli_failure_diagnosis"]["category"] == "permission_denied"


def test_execute_stops_when_model_diagnoses_input_error(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="对象已解析，可直接发送",
            action_plan=["定位接收对象", "发送消息", "回执"],
            selected_executor=ExecutorType.CLI,
            parse_source="rules_resolve_first",
            structured_command={
                "intent_type": IntentType.MESSAGE_SEND.value,
                "payload": {
                    "chat_hint": "项目群",
                    "chat_id": "oc_proj",
                    "user_id": "",
                    "text": "",
                    "resolution_status": "resolved",
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
    monkeypatch.setattr(
        agent.lark_cli_service,
        "execute_action",
        lambda *_, **__: ExecutorResult(
            executor=ExecutorType.CLI,
            success=False,
            status=ExecutionStatus.CLI_FAILED,
            summary="invalid cli payload: missing message text for lark-im +messages-send",
            error_code=int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT),
            payload={
                "domain": "message",
                "dry_run": False,
                "steps": [],
                "error": {
                    "code": int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT),
                    "name": "result_invalid",
                    "message": "missing message text",
                },
            },
        ),
    )

    async def fake_diagnose(*_: object, **__: object) -> CliFailureDiagnosis:
        return CliFailureDiagnosis(
            category="input_or_syntax_error",
            should_fallback_to_cua=False,
            confidence=0.94,
            reason="message text is empty, user input must be corrected",
            user_message="模型判断消息内容为空，请补充要发送的内容后重试。",
        )

    called = {"cua": False}

    def fake_cua(*_: object, **__: object) -> ExecutorResult:
        called["cua"] = True
        return ExecutorResult(
            executor=ExecutorType.CUA,
            success=True,
            status=ExecutionStatus.COMPLETED,
            summary="should not run",
            payload={},
        )

    monkeypatch.setattr(agent.orchestrator_service.diagnosis_service, "diagnose", fake_diagnose)
    monkeypatch.setattr(agent.orchestrator_service.cua_service, "execute_fallback", fake_cua)

    client = TestClient(create_app())
    response = client.post(
        "/api/agent/execute",
        json={
            "message": "给项目群发",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["execution_status"] == "queued"
    detail = wait_for_terminal_detail(client, data["task_id"])
    assert detail["status"] == "failed"
    assert called["cua"] is False
    assert detail["executor_result"]["summary"] == "模型判断消息内容为空，请补充要发送的内容后重试。"
    assert detail["executor_result"]["payload"]["cli_failure_diagnosis"]["category"] == "input_or_syntax_error"
