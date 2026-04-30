import subprocess

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import StandardAction
from app.services.lark_cli_service import LarkCliService


def test_execute_success_uses_unified_payload(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+messages-send"],
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute(
        intent=IntentType.MESSAGE_SEND,
        payload={"chat_id": "oc_demo", "user_id": "", "text": "hello"},
        dry_run=True,
    )
    assert result.success is True
    assert result.error_code is None
    assert set(result.payload.keys()) == {"domain", "dry_run", "steps", "error"}
    assert result.payload["domain"] == "message"
    assert result.payload["dry_run"] is True
    assert isinstance(result.payload["steps"], list) and len(result.payload["steps"]) == 1
    assert result.payload["error"] is None


def test_execute_action_returns_executor_result(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+messages-send"],
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.IM_MESSAGE_SEND,
            payload={"chat_id": "oc_demo", "user_id": "", "text": "hello"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        ),
        dry_run=True,
    )

    assert result.executor == ExecutorType.CLI
    assert result.status == ExecutionStatus.COMPLETED
    assert result.success is True
    assert result.payload["domain"] == "message"
    assert result.payload["steps"][0]["exit_code"] == 0


def test_execute_invalid_payload_returns_result_invalid() -> None:
    service = LarkCliService()
    result = service.execute(
        intent=IntentType.MESSAGE_SEND,
        payload={"chat_id": "", "user_id": "", "text": "hello"},
        dry_run=True,
    )
    assert result.success is False
    assert result.error_code == LarkCliErrorCode.RESULT_INVALID
    assert result.payload["steps"] == []
    assert result.payload["error"]["code"] == LarkCliErrorCode.RESULT_INVALID.value


def test_execute_non_zero_exit_maps_error_code(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+messages-send"],
            returncode=2,
            stdout=b"",
            stderr=b"permission denied",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute(
        intent=IntentType.MESSAGE_SEND,
        payload={"chat_id": "oc_demo", "user_id": "", "text": "hello"},
        dry_run=True,
    )
    assert result.success is False
    assert result.error_code == LarkCliErrorCode.PERMISSION_DENIED
    assert len(result.payload["steps"]) == 1
    assert result.payload["error"]["code"] == LarkCliErrorCode.PERMISSION_DENIED.value
    assert "permission denied" in result.payload["error"]["detail"]["last_error"]


def test_execute_timeout_returns_rate_limit(monkeypatch) -> None:
    service = LarkCliService()
    service.settings.lark_cli_timeout_seconds = 1

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=["lark-cli"], timeout=1, stderr=b"timeout")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute(
        intent=IntentType.MESSAGE_SEND,
        payload={"chat_id": "oc_demo", "user_id": "", "text": "hello"},
        dry_run=True,
    )
    assert result.success is False
    assert result.error_code == LarkCliErrorCode.RATE_LIMIT
    assert result.payload["error"]["code"] == LarkCliErrorCode.RATE_LIMIT.value
    assert result.payload["error"]["detail"]["timeout"] == 1
