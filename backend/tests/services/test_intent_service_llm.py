import asyncio
import json

from app.domain.enums import CapabilityId, ExecutorType, IntentType
from app.services.intent_service import IntentService


def _make_service() -> IntentService:
    service = IntentService()
    service.settings.dashscope_api_key = "test-key"
    service.settings.intent_require_llm = True
    return service


def test_llm_message_send_structures_payload_and_runs_resolver() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        payload["chat_id"] = "oc_proj"
        payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "user wants to send a message",
                    "action_plan": ["resolve recipient", "send message"],
                    "payload": {"chat_hint": "项目群", "text": "今晚九点发布"},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("跟项目群说今晚九点发布"))

    assert decision.parse_source == "qwen"
    assert decision.intent_type == IntentType.MESSAGE_SEND
    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.executor_hint == ExecutorType.CLI
    assert decision.standard_action.payload["chat_id"] == "oc_proj"
    assert decision.standard_action.payload["text"] == "今晚九点发布"
    assert decision.raw_llm_payload["capability_id"] == "im.message_send"


def test_llm_message_search_structures_payload() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])
        payload["chat_id"] = "oc_proj"
        payload["resolution_status"] = "resolved"
        return payload

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.messages_search",
                    "reason": "search messages in one chat",
                    "action_plan": ["resolve chat", "search messages"],
                    "payload": {"chat_hint": "项目群", "query": "发布"},
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("搜索项目群里关于发布的消息"))

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGES_SEARCH
    assert decision.standard_action.payload["chat_id"] == "oc_proj"
    assert decision.standard_action.payload["query"] == "发布"
    assert decision.standard_action.payload["identity"] == "user"


def test_llm_json_repair_path() -> None:
    service = _make_service()

    responses = [
        "<think>not json</think>",
        json.dumps(
            {
                "capability_id": "docs.create",
                "reason": "create a doc",
                "action_plan": ["draft title", "create doc"],
                "payload": {"title": "项目复盘"},
                "missing_fields": [],
            },
            ensure_ascii=False,
        ),
    ]

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return responses.pop(0), None

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("帮我创建一个项目复盘文档"))

    assert decision.parse_source == "qwen"
    assert decision.standard_action.capability_id == CapabilityId.DOC_CREATE
    assert decision.standard_action.payload["title"] == "项目复盘"


def test_unknown_capability_stays_unknown() -> None:
    service = _make_service()

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "unknown",
                    "reason": "cannot determine the task",
                    "action_plan": ["ask for clarification"],
                    "payload": {},
                    "missing_fields": [],
                }
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("帮我处理一下"))

    assert decision.intent_type == IntentType.UNKNOWN
    assert decision.standard_action.capability_id == CapabilityId.UNKNOWN
    assert decision.selected_executor == ExecutorType.NONE


def test_missing_fields_are_preserved_without_rule_guessing() -> None:
    service = _make_service()

    async def fake_resolve(*_: object, **kwargs: object) -> dict[str, object]:
        return dict(kwargs["payload"])

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "im.message_send",
                    "reason": "target is missing",
                    "action_plan": ["ask user for recipient"],
                    "payload": {"chat_hint": "", "text": "今晚九点发布"},
                    "missing_fields": ["chat_hint"],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service.recipient_resolver.resolve = fake_resolve  # type: ignore[method-assign]
    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("发个今晚九点发布"))

    assert decision.standard_action.capability_id == CapabilityId.IM_MESSAGE_SEND
    assert decision.standard_action.payload["text"] == "今晚九点发布"
    assert decision.missing_fields == ["chat_hint"]


def test_calendar_create_is_structured_by_llm() -> None:
    service = _make_service()

    async def fake_chat_completion(*_: object, **__: object) -> tuple[str, str | None]:
        return (
            json.dumps(
                {
                    "capability_id": "calendar.create",
                    "reason": "create a meeting",
                    "action_plan": ["confirm time", "create event"],
                    "payload": {
                        "title": "项目复盘",
                        "start_time": "2026-05-01T15:00:00+08:00",
                        "end_time": "2026-05-01T16:00:00+08:00",
                        "attendees": ["张三"],
                        "location": "会议室A",
                    },
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            None,
        )

    service._chat_completion = fake_chat_completion  # type: ignore[method-assign]

    decision = asyncio.run(service.parse("安排今天下午三点到四点的项目复盘会议"))

    assert decision.standard_action.capability_id == CapabilityId.CALENDAR_CREATE
    assert decision.standard_action.payload["title"] == "项目复盘"
    assert decision.standard_action.payload["attendees"] == ["张三"]


def test_llm_unavailable_returns_unknown() -> None:
    service = IntentService()
    service.settings.dashscope_api_key = ""

    decision = asyncio.run(service.parse("跟项目群说今晚九点发布"))

    assert decision.parse_source == "llm_unavailable"
    assert decision.standard_action.capability_id == CapabilityId.UNKNOWN
