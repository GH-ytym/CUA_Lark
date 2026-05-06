from fastapi.testclient import TestClient

from app.domain.enums import ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult, OrchestrationTask
from app.main import create_app
from app.services.cli_failure_diagnosis_service import CliFailureDiagnosis
from app.services.intent_service import IntentDecision
from shared.error_codes import UnifiedErrorCode


def test_get_execution_detail_returns_recorded_steps(monkeypatch) -> None:
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
                "steps": [{"exit_code": 2}],
                "error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"},
            },
        ),
    )
    async def fake_diagnose(*_: object, **__: object) -> CliFailureDiagnosis:
        return CliFailureDiagnosis(
            category="permission_denied",
            should_fallback_to_cua=True,
            confidence=0.9,
            reason="permission failure can be retried through CUA",
            user_message="模型判断 CLI 权限不足，准备切换到 CUA 接管。",
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
            payload={"mode": "cua_fallback", "cua_response": {"success": True}},
        ),
    )

    client = TestClient(create_app())
    execute_response = client.post(
        "/api/agent/execute",
        json={
            "message": "给项目群发今晚发布",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )

    task_id = execute_response.json()["task_id"]
    detail_response = client.get(f"/api/executions/{task_id}")

    assert detail_response.status_code == 200
    data = detail_response.json()
    assert data["task_id"] == task_id
    assert data["status"] == "completed"
    assert [step["name"] for step in data["steps"]] == [
        "task_created",
        "intent_parsed",
        "cli_started",
        "cli_finished",
        "cli_diagnosed",
        "cua_started",
        "cua_finished",
    ]


def test_get_execution_detail_returns_404_for_unknown_task() -> None:
    client = TestClient(create_app())
    response = client.get("/api/executions/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "task not found: not-found"


def test_cancel_execution_marks_non_terminal_task_canceled() -> None:
    from app.api.routes import agent

    task = OrchestrationTask(session_id="s-cancel", user_id="u1", raw_message="pending task")
    task.status = ExecutionStatus.QUEUED
    agent.orchestrator_service._tasks[task.task_id] = task  # type: ignore[attr-defined]

    client = TestClient(create_app())
    response = client.post(f"/api/executions/{task.task_id}/cancel")

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == task.task_id
    assert data["status"] == "canceled"
    assert data["canceled"] is True
    assert data["detail"]["status"] == "canceled"
    assert agent.orchestrator_service.get_task(task.task_id).status == ExecutionStatus.CANCELED


def test_cancel_execution_does_not_rewrite_completed_task() -> None:
    from app.api.routes import agent

    task = OrchestrationTask(session_id="s-done", user_id="u1", raw_message="completed task")
    task.status = ExecutionStatus.COMPLETED
    agent.orchestrator_service._tasks[task.task_id] = task  # type: ignore[attr-defined]

    client = TestClient(create_app())
    response = client.post(f"/api/executions/{task.task_id}/cancel")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["canceled"] is False
    assert data["detail"]["status"] == "completed"
    assert agent.orchestrator_service.get_task(task.task_id).status == ExecutionStatus.COMPLETED


def test_get_execution_stream_replays_steps_and_terminal_event(monkeypatch) -> None:
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
    execute_response = client.post(
        "/api/agent/execute",
        json={
            "message": "给项目群发今晚发布",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )
    task_id = execute_response.json()["task_id"]

    with client.stream("GET", f"/api/executions/{task_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        stream_body = "".join(stream_response.iter_text())

    assert "event: snapshot" in stream_body
    assert "event: step" in stream_body
    assert "event: terminal" in stream_body
    assert "cli_finished" in stream_body
    assert '"status": "completed"' in stream_body


def test_get_execution_stream_returns_404_for_unknown_task() -> None:
    client = TestClient(create_app())
    response = client.get("/api/executions/not-found/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == "task not found: not-found"


def test_cancel_execution_marks_confirmation_task_canceled(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        return IntentDecision(
            intent_type=IntentType.MESSAGE_SEND,
            reason="候选存在，需要前端确认",
            action_plan=["定位接收对象", "等待确认", "发送消息"],
            selected_executor=ExecutorType.CLI,
            parse_source="rules_resolve_first",
            structured_command={
                "intent_type": IntentType.MESSAGE_SEND.value,
                "payload": {
                    "chat_hint": "王",
                    "chat_id": "",
                    "user_id": "",
                    "text": "你好",
                    "resolution_status": "needs_confirmation",
                    "resolution_candidates": [
                        {"name": "王建国", "entity_type": "contact", "entity_id": "ou_a", "score": 0.91},
                    ],
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
    async def fake_diagnose(*_: object, **__: object) -> CliFailureDiagnosis:
        return CliFailureDiagnosis(
            category="input_or_syntax_error",
            should_fallback_to_cua=False,
            confidence=0.9,
            reason="candidate confirmation is incomplete",
            user_message="模型判断需要先确认目标对象，请补充明确接收人后重试。",
        )

    monkeypatch.setattr(agent.orchestrator_service.diagnosis_service, "diagnose", fake_diagnose)
    client = TestClient(create_app())
    execute_response = client.post(
        "/api/agent/execute",
        json={
            "message": "给王发你好",
            "session_id": "s1",
            "user_id": "u1",
            "conversation_type": "chat",
            "context_hint": "",
        },
    )
    task_id = execute_response.json()["task_id"]

    response = client.post(f"/api/executions/{task_id}/cancel")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "canceled"
    assert data["detail"]["status"] == "canceled"
    assert data["detail"]["steps"][-1]["name"] == "user_canceled"


def test_cancel_execution_returns_404_for_unknown_task() -> None:
    client = TestClient(create_app())
    response = client.post("/api/executions/not-found/cancel")

    assert response.status_code == 404
    assert response.json()["detail"] == "task not found: not-found"
