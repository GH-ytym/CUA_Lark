from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import StandardAction
from app.services.cua_service import CuaService
from shared.error_codes import UnifiedErrorCode


class _FakeRequest:
    def __init__(self, **_: object) -> None:
        pass


def _action() -> StandardAction:
    return StandardAction(
        capability_id=CapabilityId.IM_MESSAGE_SEND,
        payload={"chat_hint": "项目群", "text": "今晚发布"},
        executor_hint=ExecutorType.CLI,
        intent_type=IntentType.MESSAGE_SEND,
    )


def test_cua_service_maps_timeout_failures(monkeypatch) -> None:
    class FakeResponse:
        success = False
        message = "operation timeout after waiting"

        def model_dump(self) -> dict[str, object]:
            return {"success": False, "message": self.message}

    class FakeExecutor:
        def run(self, request: _FakeRequest) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        CuaService,
        "_load_executor_components",
        staticmethod(lambda: (FakeExecutor, _FakeRequest)),
    )

    result = CuaService().execute_fallback(
        action=_action(),
        raw_message="给项目群发今晚发布",
        task_id="task-1",
        cli_error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
        cli_payload={"error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"}},
    )

    assert result.status == ExecutionStatus.FAILED
    assert result.error_code == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["fallback_request"]["task_id"] == "task-1"


def test_cua_service_maps_security_failures(monkeypatch) -> None:
    class FakeResponse:
        success = False
        message = "security risk detected"

        def model_dump(self) -> dict[str, object]:
            return {
                "success": False,
                "message": self.message,
                "diagnosis_report": {"error_type": "PERMISSION_BLOCKED"},
            }

    class FakeExecutor:
        def run(self, request: _FakeRequest) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        CuaService,
        "_load_executor_components",
        staticmethod(lambda: (FakeExecutor, _FakeRequest)),
    )

    result = CuaService().execute_fallback(
        action=_action(),
        raw_message="给项目群发今晚发布",
        task_id="task-2",
        cli_error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
        cli_payload={"error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"}},
    )

    assert result.error_code == int(UnifiedErrorCode.SECURITY_BLOCKED)
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.SECURITY_BLOCKED)
    assert result.payload["error"]["name"] == "security_risk_detected"


def test_cua_service_maps_unknown_failures_to_execution_error(monkeypatch) -> None:
    class FakeResponse:
        success = False
        message = "window not found"

        def model_dump(self) -> dict[str, object]:
            return {"success": False, "message": self.message}

    class FakeExecutor:
        def run(self, request: _FakeRequest) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        CuaService,
        "_load_executor_components",
        staticmethod(lambda: (FakeExecutor, _FakeRequest)),
    )

    result = CuaService().execute_fallback(
        action=_action(),
        raw_message="给项目群发今晚发布",
        task_id="task-3",
        cli_error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
        cli_payload={"error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"}},
    )

    assert result.error_code == int(UnifiedErrorCode.EXECUTION_ERROR)
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.EXECUTION_ERROR)
    assert result.payload["triggered_by"]["cli_error_code"] == int(UnifiedErrorCode.PERMISSION_DENIED)
