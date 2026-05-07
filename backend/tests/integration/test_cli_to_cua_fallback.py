from fastapi.testclient import TestClient
import time

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import ExecutorResult, StandardAction
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


def test_execute_command_automatically_falls_back_to_cua(monkeypatch) -> None:
    async def fake_parse(*_: object, **__: object) -> IntentDecision:
        payload = {
            "chat_hint": "项目群",
            "chat_id": "oc_proj",
            "user_id": "",
            "text": "今晚发布",
            "resolution_status": "resolved",
        }
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
    assert detail["executor_result"]["payload"]["mode"] == "cua_fallback"
