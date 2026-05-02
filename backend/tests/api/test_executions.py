from fastapi.testclient import TestClient

from app.domain.enums import ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult
from app.main import create_app
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
        "cua_started",
        "cua_finished",
    ]


def test_get_execution_detail_returns_404_for_unknown_task() -> None:
    client = TestClient(create_app())
    response = client.get("/api/executions/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "task not found: not-found"
