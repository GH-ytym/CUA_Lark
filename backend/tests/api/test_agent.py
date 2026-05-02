from fastapi.testclient import TestClient

from app.domain.enums import ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult
from app.main import create_app
from app.services.intent_service import IntentDecision


def test_execute_returns_confirmation_candidates(monkeypatch) -> None:
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
                        {"name": "王小明", "entity_type": "contact", "entity_id": "ou_b", "score": 0.88},
                    ],
                },
            },
        )

    from app.api.routes import agent

    monkeypatch.setattr(agent.intent_service, "parse", fake_parse)
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
    assert data["needs_confirmation"] is True
    assert len(data["resolution_candidates"]) == 2
    assert data["structured_payload"]["resolution_status"] == "needs_confirmation"


def test_execute_applies_confirmed_entity_id(monkeypatch) -> None:
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
                    "chat_hint": "项目",
                    "chat_id": "",
                    "user_id": "",
                    "text": "今晚发布",
                    "resolution_status": "needs_confirmation",
                    "resolution_candidates": [
                        {"name": "项目群", "entity_type": "chat", "entity_id": "oc_proj", "score": 0.93},
                    ],
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
            payload={"domain": "message", "dry_run": False, "steps": [], "error": None},
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
    assert data["needs_confirmation"] is False
    assert data["structured_payload"]["chat_id"] == "oc_proj"
    assert data["structured_payload"]["resolution_status"] == "resolved"
    assert data["structured_payload"]["resolution_method"] == "user_confirmation"
    assert data["execution_status"] == "completed"
    assert data["cua_should_trigger"] is False


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
    assert data["execution_status"] == "completed"
    assert data["execution_summary"] == "executed 1 cli invocation(s)"
    assert data["cua_should_trigger"] is False


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
            error_code="permission_denied",
            payload={
                "domain": "message",
                "dry_run": False,
                "steps": [{"exit_code": 2}],
                "error": {"code": "permission_denied"},
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
    assert data["execution_status"] == "completed"
    assert data["cli_error_code"] == "permission_denied"
    assert data["cua_should_trigger"] is True
    assert data["execution_summary"] == "cua fallback executed"
    assert data["execution_payload"]["mode"] == "cua_fallback"
