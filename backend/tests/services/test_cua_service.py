from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import StandardAction
from app.services.cua_service import CuaService
from shared.error_codes import UnifiedErrorCode


class _FakeRequest:
    last_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


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
        session_id="session-1",
        chain_id="chain-1",
        cli_error_code=int(UnifiedErrorCode.PERMISSION_DENIED),
        cli_payload={"error": {"code": int(UnifiedErrorCode.PERMISSION_DENIED), "name": "permission_denied"}},
        retry_attempts=2,
    )

    assert result.status == ExecutionStatus.FAILED
    assert result.error_code == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["fallback_request"]["task_id"] == "task-1"
    assert result.payload["fallback_request"]["session_id"] == "session-1"
    assert result.payload["fallback_request"]["chain_id"] == "chain-1"
    assert result.payload["fallback_request"]["capability_id"] == CapabilityId.IM_MESSAGE_SEND.value
    assert result.payload["fallback_request"]["cli_error_name"] == "permission_denied"
    assert _FakeRequest.last_kwargs == {
        "instruction": "请在飞书中向项目群发送消息：今晚发布",
        "app": "飞书",
        "task": {"id": "task-1", "session": "session-1", "chain": "chain-1"},
        "action": {
            "id": CapabilityId.IM_MESSAGE_SEND.value,
            "payload": {"chat_hint": "项目群", "text": "今晚发布"},
        },
        "trigger": {
            "source": "cli",
            "code": int(UnifiedErrorCode.PERMISSION_DENIED),
            "name": "permission_denied",
            "attempts": 2,
            "summary": "permission_denied",
        },
        "memory": {
            "session": "session-1",
            "app": "飞书",
            "action": CapabilityId.IM_MESSAGE_SEND.value,
        },
    }


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
    assert result.payload["triggered_by"]["source"] == "cli"
    assert result.payload["triggered_by"]["cli_error_code"] == int(UnifiedErrorCode.PERMISSION_DENIED)


def test_cua_service_accepts_structured_trigger_source(monkeypatch) -> None:
    class FakeResponse:
        success = True
        message = "done"

        def model_dump(self) -> dict[str, object]:
            return {"success": True, "message": self.message}

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
        raw_message="给刚刚那个人发消息：hello",
        task_id="task-structured",
        cli_error_code=int(UnifiedErrorCode.HANDOFF_REQUIRED),
        cli_payload={"mode": "structured_handoff"},
        trigger_source="structured",
    )

    assert result.success is True
    assert _FakeRequest.last_kwargs["trigger"]["source"] == "structured"
    assert result.payload["triggered_by"]["source"] == "structured"
    assert result.payload["fallback_request"]["triggered_by"]["source"] == "structured"


def test_cua_service_accepts_parse_trigger_source(monkeypatch) -> None:
    class FakeResponse:
        success = True
        message = "done"

        def model_dump(self) -> dict[str, object]:
            return {"success": True, "message": self.message}

    class FakeExecutor:
        def run(self, request: _FakeRequest) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        CuaService,
        "_load_executor_components",
        staticmethod(lambda: (FakeExecutor, _FakeRequest)),
    )

    result = CuaService().execute_fallback(
        action=StandardAction(
            capability_id=CapabilityId.UNKNOWN,
            payload={"raw_message": "复杂自然语言任务"},
            executor_hint=ExecutorType.CUA,
            intent_type=IntentType.UNKNOWN,
        ),
        raw_message="复杂自然语言任务",
        task_id="task-parse",
        cli_error_code=int(UnifiedErrorCode.HANDOFF_REQUIRED),
        cli_payload={"mode": "parse_fallback"},
        trigger_source="parse",
    )

    assert result.success is True
    assert _FakeRequest.last_kwargs["trigger"]["source"] == "parse"
    assert _FakeRequest.last_kwargs["instruction"] == "复杂自然语言任务"
    assert result.payload["triggered_by"]["source"] == "parse"
    assert result.payload["fallback_request"]["triggered_by"]["source"] == "parse"


def test_cua_service_passes_through_memory_metadata(monkeypatch) -> None:
    class FakeResponse:
        success = True
        message = "done"

        def model_dump(self) -> dict[str, object]:
            return {
                "success": True,
                "message": self.message,
                "memory": {
                    "scope": {
                        "session_id": "session-9",
                        "app_name": "飞书",
                        "capability_id": CapabilityId.IM_MESSAGE_SEND.value,
                    },
                    "used": ["mem-old"],
                    "written": ["mem-new"],
                    "summary": "scoped memory used",
                },
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
        task_id="task-9",
        session_id="session-9",
        chain_id="chain-9",
        cli_error_code=int(UnifiedErrorCode.EXECUTION_ERROR),
        cli_payload={"error": {"code": int(UnifiedErrorCode.EXECUTION_ERROR)}},
        retry_attempts=2,
    )

    assert result.success is True
    assert result.payload["cua"]["memory"]["used"] == ["mem-old"]
    assert result.payload["cua"]["memory"]["written"] == ["mem-new"]
    assert result.payload["cua"]["memory"]["summary"] == "scoped memory used"


def test_cua_service_loads_real_stable_executor_contract() -> None:
    executor_cls, request_cls = CuaService._load_executor_components()

    assert executor_cls.__name__ == "CuaExecutor"
    request = request_cls(
        instruction="打开飞书",
        app="飞书",
        task={"id": "task-smoke", "session": "session-smoke", "chain": "chain-smoke"},
        action={"id": CapabilityId.IM_MESSAGE_SEND.value, "payload": {}},
        trigger={"source": "cli", "code": 3, "name": "permission_denied", "attempts": 1},
        memory={
            "session": "session-smoke",
            "app": "飞书",
            "action": CapabilityId.IM_MESSAGE_SEND.value,
        },
    )
    assert request.task["id"] == "task-smoke"
    assert request.memory["session"] == "session-smoke"
