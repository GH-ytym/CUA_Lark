import asyncio
import json

from app.domain.enums import CapabilityId, ExecutorType
from app.services.intent_service import IntentService


def test_llm_two_stage_message_parse() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    responses = [
        json.dumps(
            {
                "capability_id": "im.message_send",
                "reason": "用户要发消息",
                "action_plan": ["定位接收对象", "整理消息正文", "发送消息"],
                "payload": {"chat_hint": "梅家济", "chat_id": "", "user_id": "", "text": "hello"},
                "missing_fields": [],
            },
            ensure_ascii=False,
        ),
    ]

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "qwen"
    assert decision.intent_type.value == "message_send"
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "hello"


def test_llm_skips_second_stage_when_entities_complete() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    call_count = {"n": 0}

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        call_count["n"] += 1
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "用户要发消息",
                    "action_plan": ["定位接收对象", "整理消息正文", "发送消息"],
                    "payload": {"chat_hint": "梅家济", "chat_id": "", "user_id": "", "text": "hello"},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "qwen"
    assert payload.get("text") == "hello"
    assert call_count["n"] == 1


def test_llm_accepts_legacy_action_format() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    responses = [
        json.dumps({"action": "greeting", "target": "梅家济", "message": "hello"}, ensure_ascii=False),
    ]

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "qwen"
    assert decision.intent_type.value == "message_send"
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "hello"


def test_llm_json_repair_path() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"

    responses = [
        "<think>not json</think>",
        json.dumps(
            {
                "intent_type": "doc_create",
                "reason": "用户要创建文档",
                "action_plan": ["确认主题", "创建文档"],
                "entities": {},
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("帮我创建一个文档"))
    assert decision.parse_source == "qwen"
    assert decision.intent_type.value == "doc_create"


def test_qwen_takes_priority_over_message_fastpath() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = True

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "Qwen parsed send message",
                    "action_plan": ["解析收件人", "发送消息"],
                    "payload": {
                        "chat_hint": "梅家济",
                        "chat_id": "",
                        "user_id": "",
                        "text": "hello",
                    },
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("跟梅家济说hello"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "qwen"
    assert decision.intent_type.value == "message_send"
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "hello"
    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.executor_hint == ExecutorType.CLI
    assert decision.standard_action.payload.get("text") == "hello"


def test_qwen_unknown_is_repaired_to_message_search() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "unknown",
                    "reason": "parsed by qwen",
                    "action_plan": ["调用 lark-cli 执行并返回结果"],
                    "payload": {},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("搜索项目群里关于发布的消息"))

    assert decision.parse_source == "qwen"
    assert decision.standard_action.capability_id == CapabilityId.UNKNOWN
    assert decision.intent_type.value == "unknown"


def test_qwen_unknown_is_repaired_to_message_reply() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "unknown",
                    "reason": "用户要回复上一条消息",
                    "action_plan": ["确定要回复的消息", "发送回复内容"],
                    "payload": {},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("回复上一条消息：收到"))

    assert decision.parse_source == "qwen"
    assert decision.standard_action.capability_id == CapabilityId.UNKNOWN
    assert decision.intent_type.value == "unknown"


def test_message_fastpath_strips_send_message_verb() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""
    message = "给梅家济发消息：“hello”"

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    decision = asyncio.run(service.parse(message))
    payload = decision.structured_command.get("payload", {})

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert payload.get("chat_hint") == "梅家济"
    assert payload.get("text") == "“hello”"


def test_message_fastpath_handles_casual_say_pattern() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""
    message = "跟项目群说今晚九点发布"

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    decision = asyncio.run(service.parse(message))
    payload = decision.structured_command.get("payload", {})

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert payload.get("chat_hint") == "项目群"
    assert payload.get("text") == "今晚九点发布"


def test_message_payload_uses_local_fallback_when_llm_returns_empty_target() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_message_fastpath_enabled = False

    async def unresolved_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = kwargs.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else {}

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "Qwen parsed send message",
                    "action_plan": ["解析收件人", "发送消息"],
                    "payload": {"chat_hint": "", "chat_id": "", "user_id": "", "text": ""},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = unresolved_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("发送消息给项目群：今晚九点发布"))
    payload = decision.structured_command.get("payload", {})

    assert decision.parse_source == "qwen"
    assert payload.get("chat_hint") == ""
    assert payload.get("text") == ""
    assert payload.get("identity") == "bot"


def test_mail_and_task_are_not_classified_as_message_send() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""

    mail_decision = asyncio.run(service.parse("给李四发邮件，主题是会议纪要，内容是请查收附件"))
    task_decision = asyncio.run(service.parse("给张三创建一个任务：明天下午三点前提交周报"))

    assert mail_decision.standard_action.capability_id == CapabilityId.MAIL_SEND
    assert mail_decision.standard_action.payload.get("subject") == "会议纪要"
    assert mail_decision.standard_action.payload.get("body") == "请查收附件"
    assert task_decision.standard_action.capability_id == CapabilityId.TASK_CREATE
    assert task_decision.standard_action.payload.get("title") == "明天下午三点前提交周报"


def test_local_resolution_skips_llm() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""
    service.settings.intent_message_fastpath_enabled = False

    async def fake_resolve(*_: object, **__: object) -> dict[str, str]:
        return {
            "chat_hint": "项目群",
            "chat_id": "oc_proj",
            "user_id": "",
            "text": "今晚发布",
            "resolved_name": "项目群",
            "resolution_status": "resolved",
            "resolution_method": "rules",
            "resolution_score": "1.0",
        }

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("给项目群发今晚发布"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "rules"
    assert payload.get("chat_id") == "oc_proj"
    assert payload.get("resolution_status") == "resolved"


def test_local_confirmation_skips_llm() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""
    service.settings.intent_message_fastpath_enabled = False

    async def fake_resolve(*_: object, **__: object) -> dict[str, object]:
        return {
            "chat_hint": "王",
            "chat_id": "",
            "user_id": "",
            "text": "你好",
            "resolution_status": "needs_confirmation",
            "resolution_candidates": [
                {"name": "王建国", "entity_type": "contact", "entity_id": "ou_a", "score": 0.91},
                {"name": "王小明", "entity_type": "contact", "entity_id": "ou_b", "score": 0.88},
            ],
        }

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    decision = asyncio.run(service.parse("给王发你好"))
    payload = decision.structured_command.get("payload", {})
    assert decision.parse_source == "rules"
    assert payload.get("resolution_status") == "needs_confirmation"
    assert len(payload.get("resolution_candidates", [])) == 2
