import subprocess

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType, LarkCliErrorCode
from app.domain.models import StandardAction
from app.services.lark_cli_service import LarkCliService
from shared.error_codes import UnifiedErrorCode


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


def test_message_search_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.IM_MESSAGES_SEARCH,
            payload={"query": "发布", "chat_id": "oc_demo", "limit": 3},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "im", "+messages-search", "--as"]
    assert "--query" in argv
    assert "发布" in argv
    assert "--chat-id" in argv
    assert "oc_demo" in argv
    assert "--dry-run" in argv


def test_message_reply_requires_message_target() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.IM_MESSAGES_REPLY,
            payload={"text": "收到"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
    )

    try:
        service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)
    except ValueError as exc:
        assert "missing message_id/thread_id" in str(exc)
    else:
        raise AssertionError("reply without message_id/thread_id should fail")


def test_chat_messages_list_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.IM_CHAT_MESSAGES_LIST,
            payload={"chat_id": "oc_demo", "limit": 10, "identity": "user"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "im", "+chat-messages-list", "--as"]
    assert "--chat-id" in argv
    assert "oc_demo" in argv
    assert "--page-size" in argv
    assert "10" in argv
    assert "--dry-run" in argv


def test_chat_search_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.IM_CHAT_SEARCH,
            payload={"query": "项目群", "limit": 5, "identity": "user"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "im", "+chat-search", "--as"]
    assert "--query" in argv
    assert "项目群" in argv
    assert "--page-size" in argv
    assert "5" in argv
    assert "--dry-run" in argv


def test_chat_create_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.IM_CHAT_CREATE,
            payload={"name": "发布小组", "description": "发布同步群", "identity": "bot"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "im", "+chat-create", "--as"]
    assert "--name" in argv
    assert "发布小组" in argv
    assert "--description" in argv
    assert "发布同步群" in argv
    assert "--dry-run" in argv


def test_doc_create_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.DOC_CREATE,
            payload={"title": "小组消息跟进", "content": "记录群消息重点"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.DOC_CREATE,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "docs", "+create", "--as"]
    assert "--title" in argv
    assert "小组消息跟进" in argv
    assert "--markdown" in argv
    assert "记录群消息重点" in argv
    assert "--dry-run" in argv


def test_doc_update_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.DOC_UPDATE,
            payload={"doc_token": "doccn123", "title": "小组消息跟进", "content": "补充同步结论"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.DOC_CREATE,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "docs", "+update", "--as"]
    assert "--doc" in argv
    assert "doccn123" in argv
    assert "--mode" in argv
    assert "append" in argv
    assert "--markdown" in argv
    assert "补充同步结论" in argv
    assert "--new-title" in argv
    assert "小组消息跟进" in argv
    assert "--dry-run" in argv


def test_doc_search_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.DOC_SEARCH,
            payload={"query": "小组消息跟进"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.DOC_CREATE,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "docs", "+search", "--as"]
    assert "--query" in argv
    assert "小组消息跟进" in argv
    assert "--dry-run" in argv


def test_calendar_create_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload={
                "title": "项目复盘",
                "start_time": "2026-05-06T15:00:00+08:00",
                "end_time": "2026-05-06T16:00:00+08:00",
                "attendee_ids": ["ou_mei", "oc_proj"],
                "calendar_id": "primary",
                "description": "复盘发布流程",
                "rrule": "FREQ=WEEKLY;INTERVAL=1",
                "identity": "user",
            },
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "calendar", "+create", "--as"]
    assert "--summary" in argv
    assert "项目复盘" in argv
    assert "--start" in argv
    assert "2026-05-06T15:00:00+08:00" in argv
    assert "--end" in argv
    assert "2026-05-06T16:00:00+08:00" in argv
    assert "--attendee-ids" in argv
    assert "ou_mei,oc_proj" in argv
    assert "--calendar-id" in argv
    assert "--description" in argv
    assert "--rrule" in argv
    assert "--dry-run" in argv


def test_calendar_agenda_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.CALENDAR_AGENDA,
            payload={
                "start_time": "2026-05-06T00:00:00+08:00",
                "end_time": "2026-05-06T23:59:59+08:00",
                "calendar_id": "primary",
                "format": "json",
                "identity": "user",
            },
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "calendar", "+agenda", "--as"]
    assert "--start" in argv
    assert "--end" in argv
    assert "--calendar-id" in argv
    assert "--format" in argv
    assert "--dry-run" in argv


def test_calendar_freebusy_builds_cli_command() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.CALENDAR_FREEBUSY,
            payload={
                "start_time": "2026-05-06T09:00:00+08:00",
                "end_time": "2026-05-06T18:00:00+08:00",
                "user_id": "ou_mei",
                "format": "json",
                "identity": "user",
            },
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        )
    )

    argv = service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)

    assert argv[:4] == ["lark-cli", "calendar", "+freebusy", "--as"]
    assert "--start" in argv
    assert "2026-05-06T09:00:00+08:00" in argv
    assert "--end" in argv
    assert "2026-05-06T18:00:00+08:00" in argv
    assert "--user-id" in argv
    assert "ou_mei" in argv
    assert "--format" in argv
    assert "--dry-run" in argv


def test_execute_calendar_create_success(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "calendar", "+create"],
            returncode=0,
            stdout=b'{"event_id":"evt_123"}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload={
                "title": "项目复盘",
                "start_time": "2026-05-06T15:00:00+08:00",
                "end_time": "2026-05-06T16:00:00+08:00",
            },
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        ),
        dry_run=True,
    )

    assert result.success is True
    assert result.status == ExecutionStatus.COMPLETED
    assert result.payload["domain"] == "calendar"
    assert result.payload["steps"][0]["parsed"]["event_id"] == "evt_123"


def test_calendar_create_requires_start_and_end() -> None:
    service = LarkCliService()
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload={"title": "项目复盘", "start_time": "", "end_time": ""},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        ),
        dry_run=True,
    )

    assert result.success is False
    assert result.error_code == int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)
    assert result.payload["error"]["name"] == "result_invalid"


def test_execute_calendar_create_timeout_returns_timeout(monkeypatch) -> None:
    service = LarkCliService()
    service.settings.lark_cli_timeout_seconds = 1

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=["lark-cli", "calendar", "+create"], timeout=1, stderr=b"timeout")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload={
                "title": "Project review",
                "start_time": "2026-05-06T15:00:00+08:00",
                "end_time": "2026-05-06T16:00:00+08:00",
            },
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        ),
        dry_run=True,
    )

    assert result.success is False
    assert result.error_code == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["domain"] == "calendar"
    assert result.payload["error"]["name"] == "operation_timeout"


def test_execute_calendar_create_non_zero_exit_maps_error_code(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "calendar", "+create"],
            returncode=2,
            stdout=b"",
            stderr=b"permission denied",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.CALENDAR_CREATE,
            payload={
                "title": "Project review",
                "start_time": "2026-05-06T15:00:00+08:00",
                "end_time": "2026-05-06T16:00:00+08:00",
            },
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.CALENDAR_RESCHEDULE,
        ),
        dry_run=True,
    )

    assert result.success is False
    assert result.error_code == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert result.payload["domain"] == "calendar"
    assert result.payload["steps"][0]["exit_code"] == 2


def test_doc_update_requires_doc_token() -> None:
    service = LarkCliService()
    plan = service.plan_action(
        StandardAction(
            capability_id=CapabilityId.DOC_UPDATE,
            payload={"title": "小组消息跟进", "content": "补充同步结论"},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.DOC_CREATE,
        )
    )

    try:
        service.adapter.build_command(plan.invocations[0], cli_bin="lark-cli", dry_run=True)
    except ValueError as exc:
        assert "missing doc_token" in str(exc)
    else:
        raise AssertionError("docs update without doc_token should fail")


def test_execute_invalid_payload_returns_result_invalid() -> None:
    service = LarkCliService()
    result = service.execute(
        intent=IntentType.MESSAGE_SEND,
        payload={"chat_id": "", "user_id": "", "text": "hello"},
        dry_run=True,
    )
    assert result.success is False
    assert result.error_code == int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)
    assert result.payload["steps"] == []
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.INVALID_INPUT_OR_RESULT)
    assert result.payload["error"]["name"] == "result_invalid"


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
    assert result.error_code == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert len(result.payload["steps"]) == 1
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.PERMISSION_DENIED)
    assert result.payload["error"]["name"] == "permission_denied"
    assert "permission denied" in result.payload["error"]["detail"]["last_error"]


def test_execute_timeout_returns_timeout(monkeypatch) -> None:
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
    assert result.error_code == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["error"]["code"] == int(UnifiedErrorCode.TIMEOUT)
    assert result.payload["error"]["name"] == "operation_timeout"
    assert result.payload["error"]["detail"]["timeout"] == 1
