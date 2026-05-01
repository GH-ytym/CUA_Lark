import asyncio
import json
import subprocess

from app.domain.enums import CapabilityId, ExecutionStatus, ExecutorType, IntentType
from app.domain.models import StandardAction
from app.services.intent_service import IntentService
from app.services.lark_cli_service import LarkCliService


def _command_contains_prefix(command: str, expected: str) -> bool:
    return expected in command


def test_message_send_clear_natural_language_reaches_cli(monkeypatch) -> None:
    intent_service = IntentService()
    intent_service.settings.dashscope_api_key = "test-key"

    async def fake_resolve(*_: object, **__: object) -> dict[str, object]:
        return {
            "chat_hint": "项目群",
            "chat_id": "oc_proj",
            "user_id": "",
            "text": "今晚九点发布，注意回归验证。",
            "identity": "user",
            "resolution_status": "resolved",
        }

    intent_service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "Qwen parsed send message",
                    "action_plan": ["解析接收对象", "发送消息"],
                    "payload": {"chat_hint": "项目群", "chat_id": "", "user_id": "", "text": "今晚九点发布，注意回归验证。"},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    intent_service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(intent_service.parse("请在项目群里发：今晚九点发布，注意回归验证。"))

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
        action=decision.standard_action.model_copy(update={"payload": dict(decision.standard_action.payload) | {"dry_run": True}}),
        dry_run=True,
    )

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.payload["chat_id"] == "oc_proj"
    assert decision.standard_action.payload["text"] == "今晚九点发布，注意回归验证。"
    assert result.success is True
    assert result.status == ExecutionStatus.COMPLETED
    assert _command_contains_prefix(result.payload["steps"][0]["command"], "im +messages-send")


def test_message_search_clear_natural_language_reaches_cli(monkeypatch) -> None:
    intent_service = IntentService()
    intent_service.settings.dashscope_api_key = "test-key"

    async def fake_resolve(*_: object, **__: object) -> dict[str, object]:
        return {
            "query": "发布",
            "chat_hint": "项目群",
            "chat_id": "oc_proj",
            "sender_hint": "",
            "start_time": "",
            "end_time": "",
            "limit": 20,
            "identity": "user",
            "resolution_status": "resolved",
        }

    intent_service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.messages_search",
                    "reason": "Qwen parsed message search",
                    "action_plan": ["解析搜索范围", "搜索消息"],
                    "payload": {
                        "query": "发布",
                        "chat_hint": "项目群",
                        "chat_id": "",
                        "sender_hint": "",
                        "start_time": "",
                        "end_time": "",
                        "limit": 20,
                        "identity": "user",
                    },
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    intent_service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(intent_service.parse("搜索项目群里关于发布的消息"))

    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+messages-search"],
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=decision.standard_action.model_copy(update={"payload": dict(decision.standard_action.payload) | {"dry_run": True}}),
        dry_run=True,
    )

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGES_SEARCH
    assert decision.standard_action.payload["chat_id"] == "oc_proj"
    assert decision.standard_action.payload["query"] == "发布"
    assert result.success is True
    assert _command_contains_prefix(result.payload["steps"][0]["command"], "im +messages-search")


def test_chat_messages_list_clear_natural_language_reaches_cli(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+chat-messages-list"],
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.IM_CHAT_MESSAGES_LIST,
            payload={"chat_id": "oc_proj", "user_id": "", "limit": 10, "identity": "user", "dry_run": True},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        ),
        dry_run=True,
    )

    assert result.success is True
    assert _command_contains_prefix(result.payload["steps"][0]["command"], "im +chat-messages-list")


def test_chat_search_clear_natural_language_reaches_cli(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+chat-search"],
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.IM_CHAT_SEARCH,
            payload={"query": "项目群", "limit": 5, "identity": "user", "dry_run": True},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        ),
        dry_run=True,
    )

    assert result.success is True
    assert _command_contains_prefix(result.payload["steps"][0]["command"], "im +chat-search")


def test_chat_create_clear_natural_language_reaches_cli(monkeypatch) -> None:
    service = LarkCliService()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=["lark-cli", "im", "+chat-create"],
            returncode=0,
            stdout=b'{"ok":true}',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = service.execute_action(
        action=StandardAction(
            capability_id=CapabilityId.IM_CHAT_CREATE,
            payload={"name": "发布小组", "description": "发布同步群", "identity": "bot", "dry_run": True},
            executor_hint=ExecutorType.CLI,
            intent_type=IntentType.MESSAGE_SEND,
        ),
        dry_run=True,
    )

    assert result.success is True
    assert _command_contains_prefix(result.payload["steps"][0]["command"], "im +chat-create")
